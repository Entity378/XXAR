# Remaps mod entries targeting protected override PCKs (Patch.pck/Hotfix.pck) to the
# matching SoundBank/Streamed PCK in StreamingAssets, and pre-extracts pristine BNK content.

from pathlib import Path

from src.core.logger import get_logger
from src.wwise.bnk_handler import BNKFile
from src.wwise.bnk_indexer import BNKIndexer
from src.wwise.pck_indexer import PCKIndexer

logger = get_logger(__name__)

BACKUP_SUFFIX = ".xxar_backup"


def _soundbank_scan_glob(game):
    # Filter prefix covers every language bank (SoundBank_En_* etc.), not only the SFX-only soundbank_pck_glob.
    return f"{game.soundbank_pck_filter_prefix}*.pck"


def _streamed_scan_glob(game):
    # Same broadening so Streamed_En_* (voices) are scanned, not only Streamed_SFX_*.
    return f"{game.streamed_pck_filter_prefix}*.pck"


def find_patch_pck_sources(persistent_root, game):
    # Returns [(pristine_path, override_pck_name), ...], preferring .xxar_backup for the pre-mod state.
    persistent_root = Path(persistent_root) if persistent_root else None
    if not persistent_root or not persistent_root.exists():
        return []

    protected = set(game.protected_pcks)
    sources = []
    for p in persistent_root.rglob("*.pck"):
        if p.name not in protected:
            continue
        backup = p.with_name(p.name + BACKUP_SUFFIX)
        sources.append((backup if backup.exists() else p, p.name))
    return sources


def plain_wem_id(info, key):
    # The bare integer WEM id from an entry's file_id, or the tail of a "bnk_id|wem_id" key.
    raw = info.get("file_id")
    if raw is None:
        raw = str(key).split("|")[-1] if "|" in str(key) else key
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def soundbank_bnk_ids(streaming_root, game):
    # Set of every bnk_id present in the StreamingAssets SoundBank pcks (the counterpart set for Patch BNKs).
    result = set()
    streaming_root = Path(streaming_root) if streaming_root else None
    if not streaming_root or not streaming_root.exists():
        return result
    for pck_file in streaming_root.rglob(_soundbank_scan_glob(game)):
        try:
            index = PCKIndexer(str(pck_file)).build_index()
        except Exception as e:
            logger.warning(f"[Patch Resolver] Could not index {pck_file.name}: {e}")
            continue
        result.update(bank["id"] for bank in index.get("banks", []))
    return result


def streamed_wem_pcks(streaming_root, game):
    # wem_id -> (pck_name, lang_id) for every direct/external WEM in the Streamed_*.pck of StreamingAssets.
    result = {}
    streaming_root = Path(streaming_root) if streaming_root else None
    if not streaming_root or not streaming_root.exists():
        return result
    for pck_file in streaming_root.rglob(_streamed_scan_glob(game)):
        try:
            index = PCKIndexer(str(pck_file)).build_index()
        except Exception as e:
            logger.warning(f"[Patch Resolver] Could not index {pck_file.name}: {e}")
            continue
        for streamed_wem in index.get("sounds", []) + index.get("externals", []):
            result.setdefault(streamed_wem["id"], (pck_file.name, streamed_wem.get("lang_id", 0)))
    return result


def add_streamed_duplicates(resolved, streaming_root, game, streamed_index=None):
    # Mirror each bnk-embedded replacement into the Streamed_*.pck holding the same WEM id, patching both copies.
    # Mutates `resolved` in place and returns the mirror count; a caller-provided index avoids re-indexing.
    if streamed_index is None:
        streamed_index = streamed_wem_pcks(streaming_root, game)
    if not streamed_index:
        return 0
    mirrored = 0
    for pck_name in list(resolved.keys()):
        for key, info in list(resolved[pck_name].items()):
            if str(info.get("file_type", "wem")).lower() != "bnk":
                continue
            wem_id = plain_wem_id(info, key)
            if wem_id is None:
                continue
            match = streamed_index.get(wem_id)
            if not match or match[0] == pck_name:
                continue
            streamed_pck, lang_id = match
            dest = resolved.setdefault(streamed_pck, {})
            dup_key = str(wem_id)
            if dup_key in dest:
                continue
            # A plain streamed copy of the same mod WEM: keep wem_path, drop the bnk binding.
            dup = dict(info)
            dup["file_type"] = "wem"
            dup["bnk_id"] = None
            dup["file_id"] = wem_id
            dup["lang_id"] = lang_id
            dest[dup_key] = dup
            mirrored += 1
            logger.info(f"[Patch Resolver] WEM {wem_id}: mirrored {pck_name} BNK patch into streamed {streamed_pck}")
    return mirrored


def install_whole_patch_bnks(packer, bnk_ids, patch_bnk_content, bnk_lang_ids):
    # Bring whole pristine Patch BNKs into a pck so a later merge has a target.
    # Replace the counterpart's old copy when it exists, or add it when this pck is the orphan host.
    for bnk_id in list(bnk_ids):
        content = patch_bnk_content.get(bnk_id)
        if not content or not content.get("full_bnk_bytes"):
            continue
        fallback_lang = content.get("host_lang_id") or bnk_lang_ids.get(bnk_id, 0)
        packer.add_or_replace_bnk_raw(bnk_id, content["full_bnk_bytes"], fallback_lang)


def resolve_and_extract(resolved, streaming_root, persistent_root, game, streamed_index=None):
    # Mutates `resolved` in place: removes protected pck_name keys, moves entries under the resolved dest_pck.
    # streamed_index, when given, is reused for the streamed-target lookup instead of indexing the pcks again.
    # Returns stats + patch_bnk_content {pck_name: {bnk_id: {source, wems, full_bnk_bytes?}}} for the main loop.
    # Pristine content comes per target pck from the language that owns it (the override holding the modded WEM).
    streaming_root = Path(streaming_root) if streaming_root else None
    persistent_root = Path(persistent_root) if persistent_root else None
    protected_names = set(game.protected_pcks)

    has_protected_targets = any(pck in protected_names for pck in resolved.keys())

    persistent_overrides = []
    if persistent_root and persistent_root.exists():
        persistent_overrides = [
            p for p in persistent_root.rglob("*.pck")
            if p.name in protected_names
        ]

    if not has_protected_targets and not persistent_overrides:
        return {"remapped": 0, "orphan_added": 0, "dropped": 0, "patch_bnk_content": {}}

    # Lazily-built streaming indexes.
    soundbank_bnk_index = None  # {bnk_id: [(pck_path, indexer), ...]} across languages
    streamed_wem_index = streamed_index  # {wem_id: (pck_name, lang_id)}; reuse the caller's when provided
    soundbank_bnk_wems = {}     # (pck_path, bnk_id) -> set(wem_id)
    host_by_folder = {}         # language folder -> SoundBank pck that hosts an orphan Patch BNK of that language
    whole_bnk_targets = set()   # (target_pck, bnk_id) brought in whole (no counterpart, or counterpart lacks the WEM)

    override_index_cache = {}    # override_path -> (read_path, index_dict)
    winning_override_cache = {}  # (bnk_id, wem_id) -> (override_path, bank_meta, bnk_bytes) | None

    def _override_index():
        if not override_index_cache:
            for override_pck in persistent_overrides:
                backup = override_pck.with_name(override_pck.name + BACKUP_SUFFIX)
                read_path = backup if backup.exists() else override_pck
                try:
                    override_index_cache[override_pck] = (read_path, PCKIndexer(str(read_path)).build_index())
                except Exception as e:
                    logger.error(f"[Patch Resolver] Warning: failed to index {read_path.name}: {e}")
        return override_index_cache

    def _winning_override(bnk_id, wem_id):
        # Override Patch.pck whose copy of this bnk holds the modded WEM, i.e. its owning language.
        # Falls back to any override containing the bnk when no WEM matches.
        cache_key = (bnk_id, wem_id)
        if cache_key in winning_override_cache:
            return winning_override_cache[cache_key]
        wanted_wems = {wem_id} if wem_id is not None else set()
        fallback = None
        chosen = None
        for override_pck, (read_path, index) in _override_index().items():
            bank = next((entry for entry in index.get("banks", []) if entry["id"] == bnk_id), None)
            if bank is None:
                continue
            try:
                with open(read_path, "rb") as handle:
                    handle.seek(bank["offset"])
                    bnk_bytes = handle.read(bank["size"])
                embedded_wems = set(BNKFile(bnk_bytes=bnk_bytes).list_wems())
            except Exception as e:
                logger.error(f"[Patch Resolver] Warning: failed to read BNK {bnk_id} from {read_path.name}: {e}")
                continue
            candidate = (override_pck, bank, bnk_bytes)
            if fallback is None:
                fallback = candidate
            if wanted_wems and (embedded_wems & wanted_wems):
                chosen = candidate
                break
        winning_override_cache[cache_key] = chosen or fallback
        return winning_override_cache[cache_key]

    def _soundbank_meta():
        # One {name, size, folder} per SoundBank pck; folder is the language subdir or the root name.
        # Scans pcks directly (not the bnk index, which dedups by bnk_id and would drop one language's pck).
        soundbank_pcks = []
        seen = set()
        if not streaming_root or not streaming_root.exists():
            return soundbank_pcks
        for pck_file in streaming_root.rglob(_soundbank_scan_glob(game)):
            if pck_file.name in seen:
                continue
            seen.add(pck_file.name)
            try:
                soundbank_pcks.append({
                    "name": pck_file.name,
                    "size": pck_file.stat().st_size,
                    "folder": pck_file.parent.name,
                })
            except OSError:
                continue
        return soundbank_pcks

    def _pick_host_soundbank(folder):
        # Smallest SoundBank pck in the orphan's language folder (En orphan -> En bank, SFX -> SFX bank).
        # Falls back to the globally smallest pck.
        if folder in host_by_folder:
            return host_by_folder[folder]
        soundbank_pcks = _soundbank_meta()
        in_folder = [pck for pck in soundbank_pcks if pck["folder"] == folder]
        candidates = in_folder or soundbank_pcks
        smallest = min(candidates, key=lambda pck: pck["size"], default=None)
        host_by_folder[folder] = smallest["name"] if smallest else ""
        return host_by_folder[folder]

    def _build_bnk_index():
        result = {}
        if not streaming_root or not streaming_root.exists():
            return result
        for pck_file in streaming_root.rglob(_soundbank_scan_glob(game)):
            try:
                indexer = PCKIndexer(str(pck_file))
                indexer.build_index()
            except Exception as e:
                logger.error(f"[Patch Resolver] Warning: failed to index {pck_file.name}: {e}")
                continue
            for bank in indexer.index_data.get("banks", []):
                # bnk_id -> list of (pck, indexer): En/Jp SoundBanks share every bnk_id, so a single entry
                # would hide one language. The right counterpart is the one whose copy holds the WEM.
                result.setdefault(bank["id"], []).append((pck_file, indexer))
        return result

    def _counterpart_has_wem(counterpart, bnk_id, wem_id):
        # Does the SoundBank copy of this bnk already contain the WEM (so a plain merge suffices)?
        # Reuses the indexer built in _build_bnk_index so the pck isn't parsed twice.
        pck_file, indexer = counterpart
        cache_key = (str(pck_file), bnk_id)
        if cache_key not in soundbank_bnk_wems:
            try:
                bank = next(b for b in indexer.index_data["banks"] if b["id"] == bnk_id)
                didx = BNKIndexer(indexer.extract_single_file(bnk_id, "bnk", bank["lang_id"]))
                didx.parse_didx()
                soundbank_bnk_wems[cache_key] = set(didx.get_wem_ids())
            except Exception:
                soundbank_bnk_wems[cache_key] = set()
        return wem_id in soundbank_bnk_wems[cache_key]

    remapped = 0
    orphan_added = 0
    dropped = 0

    for pck_name in [n for n in list(resolved.keys()) if n in protected_names]:
        entries = resolved.pop(pck_name)
        for key, info in entries.items():
            file_type = str(info.get("file_type", "wem")).lower()
            target_pck = None
            is_whole = False

            if file_type == "bnk":
                bnk_id = info.get("bnk_id")
                if bnk_id is None:
                    logger.info(f"[Patch Resolver] Entry {key} in {pck_name} has no bnk_id, dropping")
                    dropped += 1
                    continue
                bnk_id = int(bnk_id)
                wem_id = plain_wem_id(info, key)

                if soundbank_bnk_index is None:
                    soundbank_bnk_index = _build_bnk_index()
                counterparts = soundbank_bnk_index.get(bnk_id, [])

                # The right counterpart is the SoundBank copy (of any language) that already holds this WEM.
                chosen_counterpart = next(
                    (counterpart for counterpart in counterparts
                     if wem_id is not None and _counterpart_has_wem(counterpart, bnk_id, wem_id)),
                    None,
                )
                if chosen_counterpart is not None:
                    # The SoundBank copy already holds the WEM: a plain merge there suffices.
                    target_pck = chosen_counterpart[0].name
                else:
                    # No SoundBank copy holds the WEM, so bring the whole Patch BNK in.
                    # Target a counterpart in the WEM's language, else a fresh host in that folder.
                    winner = _winning_override(bnk_id, wem_id)
                    folder = winner[0].parent.name if winner else ""
                    counterpart_in_folder = next(
                        (counterpart for counterpart in counterparts if counterpart[0].parent.name == folder),
                        None,
                    )
                    target_pck = counterpart_in_folder[0].name if counterpart_in_folder else _pick_host_soundbank(folder)
                    if not target_pck:
                        logger.info(f"[Patch Resolver] BNK {bnk_id} has no host SoundBank, dropping entry {key}")
                        dropped += 1
                        continue
                    whole_bnk_targets.add((target_pck, bnk_id))
                    is_whole = True
            else:
                wem_id = plain_wem_id(info, key)
                if wem_id is None:
                    logger.info(f"[Patch Resolver] Cannot parse WEM id for {key}, dropping")
                    dropped += 1
                    continue
                if streamed_wem_index is None:
                    streamed_wem_index = streamed_wem_pcks(streaming_root, game)
                match = streamed_wem_index.get(wem_id)
                if not match:
                    logger.info(f"[Patch Resolver] WEM {wem_id} not found in any {_streamed_scan_glob(game)} of StreamingAssets, dropping entry {key}")
                    dropped += 1
                    continue
                target_pck = match[0]

            dest = resolved.setdefault(target_pck, {})
            if key in dest:
                logger.info(f"[Patch Resolver] Conflict on key {key}: entry already exists in {target_pck}, keeping existing (load order precedence)")
                continue
            dest[key] = info
            if is_whole:
                orphan_added += 1
                logger.info(f"[Patch Resolver] BNK {info.get('bnk_id')} -> whole BNK into {target_pck}")
            else:
                remapped += 1

    patch_bnk_content = {}
    if not persistent_overrides:
        return {"remapped": remapped, "orphan_added": orphan_added, "dropped": dropped, "patch_bnk_content": patch_bnk_content}

    # Take pristine WEMs per (target pck, bnk_id) from the language that owns the WEM.
    # So an En SoundBank never gets Jp audio under the same colliding bnk_id, and En+Jp mods feed each rebuild.
    for pck_name, entries in resolved.items():
        for key, info in entries.items():
            bnk_id = info.get("bnk_id")
            if bnk_id is None:
                continue
            try:
                bnk_id = int(bnk_id)
            except (TypeError, ValueError):
                continue
            if bnk_id in patch_bnk_content.get(pck_name, {}):
                continue
            winner = _winning_override(bnk_id, plain_wem_id(info, key))
            if winner is None:
                continue
            override_pck, bank, bnk_bytes = winner
            try:
                bnk_file = BNKFile(bnk_bytes=bnk_bytes)
                wem_map = {wem_id: bnk_file.extract_wem(wem_id) for wem_id in bnk_file.list_wems()}
            except Exception as e:
                logger.error(f"[Patch Resolver] Warning: failed to parse BNK {bnk_id} from {override_pck.name}: {e}")
                continue
            entry = {"source": f"{override_pck.parent.name}/{override_pck.name}", "wems": wem_map}
            if (pck_name, bnk_id) in whole_bnk_targets:
                # Carry the whole pristine BNK so the host SoundBank can add or replace it wholesale.
                entry["full_bnk_bytes"] = bnk_bytes
                entry["host_lang_id"] = bank["lang_id"]
            patch_bnk_content.setdefault(pck_name, {})[bnk_id] = entry

    return {
        "remapped": remapped,
        "orphan_added": orphan_added,
        "dropped": dropped,
        "patch_bnk_content": patch_bnk_content,
    }
