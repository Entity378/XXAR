# Heals mod targets after a game update relocates a sound's WEM id to a different PCK.

from pathlib import Path

from src.core.logger import get_logger
from src.wwise import patch_backup
from src.wwise.bnk_handler import BNKFile
from src.wwise.bnk_indexer import BNKIndexer
from src.wwise.patch_target_resolver import find_patch_pck_sources, plain_wem_id
from src.wwise.pck_indexer import PCKIndexer

logger = get_logger(__name__)


def _is_broken(index, pck, file_type, bnk_id, wem_id):
    # A verification error means we can't be sure, so we leave the entry untouched.
    try:
        return not index.entry_is_valid(pck, file_type, bnk_id, wem_id)
    except Exception as e:
        logger.warning(f"[Relink] Could not verify {wem_id} in {pck}: {e}")
        return False


class GameAudioIndex:
    # Lazily-built view of where every sound id currently lives in the live game audio.

    def __init__(self, game_audio_dir, game, persistent_audio_dir=None):
        self.game_audio_dir = Path(game_audio_dir)
        # The live Patch.pck lives under Persistent (StreamingAssets holds only a stub); derive it when not given.
        if persistent_audio_dir:
            self.persistent_audio_dir = Path(persistent_audio_dir)
        elif "StreamingAssets" in str(self.game_audio_dir):
            self.persistent_audio_dir = Path(str(self.game_audio_dir).replace("StreamingAssets", "Persistent"))
        else:
            self.persistent_audio_dir = None
        self.game = game
        self._pck_cache = {}        # path -> PCKIndexer (index built)
        self._bnk_wems = {}         # (path, bnk_id) -> set(wem_id)
        self._direct_index = None   # wem_id -> [pck_basename]
        self._embedded_index = None  # wem_id -> [(pck_basename, bnk_id)]
        self._patch_index = None    # wem_id -> (override_name, bnk_id)

    def _indexer(self, path):
        path = str(path)
        if path not in self._pck_cache:
            indexer = PCKIndexer(path)
            indexer.build_index()
            self._pck_cache[path] = indexer
        return self._pck_cache[path]

    def _bnk_wem_ids(self, pck_path, bnk_id, lang_id):
        cache_key = (str(pck_path), bnk_id)
        if cache_key not in self._bnk_wems:
            bnk_bytes = self._indexer(pck_path).extract_single_file(bnk_id, "bnk", lang_id)
            self._bnk_wems[cache_key] = set(BNKFile(bnk_bytes=bnk_bytes).list_wems())
        return self._bnk_wems[cache_key]

    def find_live_pck(self, pck_name):
        # Mirror apply_mods: prefer the audio root, fall back to the matching subdir.
        base = Path(pck_name).name
        direct = self.game_audio_dir / pck_name
        if direct.exists():
            return direct
        for subdir in sorted(p for p in self.game_audio_dir.iterdir() if p.is_dir()):
            candidate = subdir / base
            if candidate.exists():
                return candidate
        return None

    def _build_patch_index(self):
        # wem_id -> (override_name, bnk_id) for WEMs embedded in Patch.pck/Hotfix.pck BNKs (the copy the game plays).
        # Reads only each bnk's leading bytes: DIDX sits near the start, so we skip its (large) DATA payload.
        if self._patch_index is not None:
            return
        self._patch_index = {}
        if not self.persistent_audio_dir:
            return
        for live_path, override_name in find_patch_pck_sources(self.persistent_audio_dir, self.game):
            read_path = patch_backup.pristine_path(live_path, self.persistent_audio_dir, self.game)
            try:
                banks = self._indexer(read_path).index_data["banks"]
                with open(read_path, "rb") as f:
                    for bank in banks:
                        f.seek(bank["offset"])
                        didx = BNKIndexer(f.read(min(bank["size"], 131072)))
                        didx.parse_didx()
                        for wem_id in didx.get_wem_ids():
                            self._patch_index.setdefault(wem_id, (override_name, bank["id"]))
            except Exception as e:
                logger.warning(f"[Relink] Could not scan {Path(read_path).name}: {e}")

    def patch_home(self, wem_id):
        # (override_name, bnk_id) if the wem is embedded in a Patch.pck BNK, else None.
        self._build_patch_index()
        return self._patch_index.get(int(wem_id))

    def entry_is_valid(self, pck_name, file_type, bnk_id, wem_id):
        # A Patch-shadowed wem is only valid from its Patch BNK; the override copy is what the game plays.
        home = self.patch_home(wem_id)
        if home is not None:
            override_name, patch_bnk_id = home
            return Path(pck_name).name == override_name and file_type == "bnk" and bnk_id is not None and int(bnk_id) == patch_bnk_id

        live = self.find_live_pck(pck_name)
        if not live:
            return False
        data = self._indexer(live).index_data

        if file_type == "bnk" and bnk_id is not None:
            bank = next((b for b in data["banks"] if b["id"] == bnk_id), None)
            if not bank:
                return False
            return wem_id in self._bnk_wem_ids(live, bnk_id, bank["lang_id"])

        sound_ids = {e["id"] for e in data["sounds"] + data["externals"]}
        return wem_id in sound_ids

    def _build_direct_index(self):
        if self._direct_index is not None:
            return
        self._direct_index = {}
        for pck in sorted(self.game_audio_dir.rglob("*.pck")):
            if self.game.is_protected_pck(pck.name):
                continue
            try:
                data = self._indexer(pck).index_data
            except Exception as e:
                logger.warning(f"[Relink] Could not index {pck.name}: {e}")
                continue
            for entry in data["sounds"] + data["externals"]:
                self._direct_index.setdefault(entry["id"], []).append(pck.name)

    def _build_embedded_index(self, progress_callback=None):
        if self._embedded_index is not None:
            return
        self._embedded_index = {}
        soundbank_pcks = sorted(self.game_audio_dir.rglob(self.game.soundbank_pck_glob))
        for idx, pck in enumerate(soundbank_pcks):
            if self.game.is_protected_pck(pck.name):
                continue
            if progress_callback:
                progress_callback(f"Scanning {pck.name} for relocated sounds...")
            try:
                indexer = self._indexer(pck)
                for bank in indexer.index_data["banks"]:
                    bnk_bytes = indexer.extract_single_file(bank["id"], "bnk", bank["lang_id"])
                    wem_ids = set(BNKFile(bnk_bytes=bnk_bytes).list_wems())
                    self._bnk_wems[(str(pck), bank["id"])] = wem_ids
                    for wem_id in wem_ids:
                        self._embedded_index.setdefault(wem_id, []).append((pck.name, bank["id"]))
            except Exception as e:
                logger.warning(f"[Relink] Could not scan bnks in {pck.name}: {e}")

    def _prefer_pck(self, names):
        # Authoritative target first: a SoundBank container, then a Streamed one, then anything.
        sb = self.game.soundbank_pck_filter_prefix
        st = self.game.streamed_pck_prefix
        for prefix in (sb, st):
            if prefix:
                match = next((n for n in names if n.startswith(prefix)), None)
                if match:
                    return match
        return names[0]

    def locate(self, wem_id, progress_callback=None):
        # Returns {'pck_name','file_type','bnk_id'} for the id's current home, or None.
        # Priority Patch.pck > SoundBank > Streamed: a Patch-embedded copy is what the game plays, so it wins.
        # The target stays Patch.pck/bnk; the apply remaps it (add whole BNK to a host SoundBank + null).
        home = self.patch_home(wem_id)
        if home is not None:
            override_name, patch_bnk_id = home
            return {"pck_name": override_name, "file_type": "bnk", "bnk_id": patch_bnk_id}

        self._build_direct_index()
        direct = self._direct_index.get(wem_id)
        if direct:
            return {"pck_name": self._prefer_pck(direct), "file_type": "wem", "bnk_id": None}

        self._build_embedded_index(progress_callback)
        embedded = self._embedded_index.get(wem_id)
        if embedded:
            pck_name = self._prefer_pck([p for p, _ in embedded])
            bnk_id = next(b for p, b in embedded if p == pck_name)
            return {"pck_name": pck_name, "file_type": "bnk", "bnk_id": bnk_id}

        return None


def relink_replacements(replacements, game_audio_dir, game, progress_callback=None, index=None):
    # Relink a flat {pck: {key: info}} dict in place (tracker / export-staging shape).
    # Each info keeps its wem_path, so the physical audio follows the moved reference.
    index = index or GameAudioIndex(game_audio_dir, game)
    broken = []

    for pck_name, entries in list(replacements.items()):
        if index.game.is_protected_pck(pck_name):
            continue
        for key, info in list(entries.items()):
            if info.get("is_add"):
                continue
            wem_id = plain_wem_id(info, key)
            if wem_id is None:
                continue
            file_type = str(info.get("file_type", "wem")).lower()
            bnk_id = info.get("bnk_id")
            if _is_broken(index, pck_name, file_type, bnk_id, wem_id):
                broken.append((pck_name, key, wem_id, file_type, bnk_id))

    if not broken:
        return {"relinked": 0, "unresolved": []}

    if progress_callback:
        progress_callback(f"Repairing {len(broken)} mod target(s) for the current game version...")

    relinked = 0
    unresolved = []

    for old_pck, key, wem_id, file_type, old_bnk_id in broken:
        loc = index.locate(wem_id, progress_callback)
        if not loc:
            unresolved.append((old_pck, wem_id))
            logger.warning(f"[Relink] WEM {wem_id} not found in any PCK, leaving unchanged")
            continue

        info = replacements[old_pck].pop(key)
        if not replacements[old_pck]:
            del replacements[old_pck]
        info["file_type"] = loc["file_type"]
        info["bnk_id"] = loc["bnk_id"]
        new_key = f"{loc['bnk_id']}|{wem_id}" if loc["bnk_id"] is not None else str(wem_id)
        replacements.setdefault(loc["pck_name"], {})[new_key] = info
        relinked += 1
        logger.info(
            f"[Relink] WEM {wem_id}: {old_pck} ({file_type}/{old_bnk_id}) -> "
            f"{loc['pck_name']} ({loc['file_type']}/{loc['bnk_id']})"
        )

    return {"relinked": relinked, "unresolved": unresolved}


def relink_tracker(mod_manager, game_audio_dir, game, progress_callback=None):
    # Repair staged replacements after a game update so a re-export carries the fix.
    result = relink_replacements(
        mod_manager.get_all_replacements(), game_audio_dir, game, progress_callback,
    )
    if result["relinked"]:
        mod_manager.save_tracker()
    return result


def _bnk_key_id(bnk_key):
    try:
        return int(str(bnk_key).replace(".bnk", ""))
    except (TypeError, ValueError):
        return None


def _metadata_entries(metadata):
    # (pck, bnk_id, file_key, info) for each replacement, regardless of format version.
    replacements = metadata.get("replacements", {})
    nested = metadata.get("format_version", "1.0") in ("2.0", "3.0")
    entries = []
    for pck, bucket in replacements.items():
        if nested:
            for bnk_key, files in bucket.items():
                bnk_id = None if bnk_key == "direct" else _bnk_key_id(bnk_key)
                for file_key, info in files.items():
                    entries.append((pck, bnk_id, file_key, info))
        else:
            for file_key, info in bucket.items():
                entries.append((pck, info.get("bnk_id"), file_key, info))
    return entries


def _relocate_metadata_entry(metadata, old_pck, old_bnk_id, file_key, new_pck, new_bnk_id, new_file_type):
    replacements = metadata["replacements"]
    nested = metadata.get("format_version", "1.0") in ("2.0", "3.0")

    if nested:
        old_bnk_key = "direct" if old_bnk_id is None else f"{old_bnk_id}.bnk"
        bucket = replacements.get(old_pck, {}).get(old_bnk_key, {})
        if file_key not in bucket:
            return
        info = bucket.pop(file_key)
        info["file_type"] = new_file_type
        new_bnk_key = "direct" if new_bnk_id is None else f"{new_bnk_id}.bnk"
        replacements.setdefault(new_pck, {}).setdefault(new_bnk_key, {})[file_key] = info
        if not bucket:
            replacements[old_pck].pop(old_bnk_key, None)
        if not replacements.get(old_pck):
            replacements.pop(old_pck, None)
        return

    bucket = replacements.get(old_pck, {})
    if file_key not in bucket:
        return
    info = bucket.pop(file_key)
    info["file_type"] = new_file_type
    info["bnk_id"] = new_bnk_id
    replacements.setdefault(new_pck, {})[file_key] = info
    if not bucket:
        replacements.pop(old_pck, None)


def relink_metadata(metadata, game_audio_dir, game, progress_callback=None, index=None):
    # Repair one installed mod's stored references against the current game version.
    # Mutates metadata["replacements"] in place; caller persists it.
    index = index or GameAudioIndex(game_audio_dir, game)
    broken = []

    for pck, bnk_id, file_key, info in _metadata_entries(metadata):
        if index.game.is_protected_pck(pck) or info.get("is_add"):
            continue
        wem_id = plain_wem_id(info, file_key)
        if wem_id is None:
            continue
        file_type = str(info.get("file_type", "wem")).lower()
        if _is_broken(index, pck, file_type, bnk_id, wem_id):
            broken.append((pck, bnk_id, file_key, wem_id, file_type))

    if not broken:
        return {"relinked": 0, "unresolved": []}

    if progress_callback:
        progress_callback(f"Repairing {len(broken)} mod target(s) for the current game version...")

    relinked = 0
    unresolved = []

    for old_pck, old_bnk_id, file_key, wem_id, file_type in broken:
        loc = index.locate(wem_id, progress_callback)
        if not loc:
            unresolved.append((old_pck, wem_id))
            logger.warning(f"[Relink] WEM {wem_id} not found in any PCK, leaving unchanged")
            continue

        _relocate_metadata_entry(
            metadata, old_pck, old_bnk_id, file_key,
            loc["pck_name"], loc["bnk_id"], loc["file_type"],
        )
        relinked += 1
        logger.info(
            f"[Relink] WEM {wem_id}: {old_pck} ({file_type}/{old_bnk_id}) -> "
            f"{loc['pck_name']} ({loc['file_type']}/{loc['bnk_id']})"
        )

    return {"relinked": relinked, "unresolved": unresolved}
