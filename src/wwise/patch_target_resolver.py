# Remaps mod entries targeting protected override PCKs (Patch.pck/Hotfix.pck) to the
# matching SoundBank/Streamed PCK in StreamingAssets, and pre-extracts pristine BNK content.

from pathlib import Path

from src.core.logger import get_logger
from src.wwise.bnk_handler import BNKFile
from src.wwise.bnk_indexer import BNKIndexer
from src.wwise.pck_indexer import PCKIndexer

logger = get_logger(__name__)

BACKUP_SUFFIX = ".xxar_backup"


def find_patch_pck_sources(persistent_root, game):
    # Returns [(pristine_path, override_pck_name), ...], preferring .xxar_backup for the pre-mod state.
    persistent_root = Path(persistent_root) if persistent_root else None
    if not persistent_root or not persistent_root.exists():
        return []

    protected = set(getattr(game, "protected_pcks", ()) or ())
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
    for pck_file in streaming_root.rglob(game.soundbank_pck_glob):
        try:
            idx = PCKIndexer(str(pck_file)).build_index()
        except Exception as e:
            logger.warning(f"[Patch Resolver] Could not index {pck_file.name}: {e}")
            continue
        result.update(b["id"] for b in idx.get("banks", []))
    return result


def streamed_wem_pcks(streaming_root, game):
    # wem_id -> (pck_name, lang_id) for every direct/external WEM in the Streamed_*.pck of StreamingAssets.
    result = {}
    streaming_root = Path(streaming_root) if streaming_root else None
    if not streaming_root or not streaming_root.exists():
        return result
    for pck_file in streaming_root.rglob(game.streamed_pck_glob):
        try:
            idx = PCKIndexer(str(pck_file)).build_index()
        except Exception as e:
            logger.warning(f"[Patch Resolver] Could not index {pck_file.name}: {e}")
            continue
        for entry in idx.get("sounds", []) + idx.get("externals", []):
            result.setdefault(entry["id"], (pck_file.name, entry.get("lang_id", 0)))
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
    # Returns stats + patch_bnk_content {bnk_id: {"source": override_pck_name, "wems": {wem_id: bytes}}} so the
    # main loop can transport pristine override WEMs into the dest BNK before applying mod replacements.
    streaming_root = Path(streaming_root) if streaming_root else None
    persistent_root = Path(persistent_root) if persistent_root else None
    protected_names = set(getattr(game, "protected_pcks", ()) or ())

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
    soundbank_bnk_index = None  # {bnk_id: (pck_path, indexer)}
    streamed_wem_index = streamed_index  # {wem_id: (pck_name, lang_id)}; reuse the caller's when provided
    soundbank_bnk_wems = {}     # (pck_path, bnk_id) -> set(wem_id)
    chosen_host = [None]        # smallest SoundBank pck, hosts an orphan Patch BNK (one host -> one rebuild)
    whole_bnk_ids = set()       # Patch BNKs brought in whole (no counterpart, or counterpart lacks the WEM)

    def _pick_host_soundbank():
        if chosen_host[0] is not None:
            return chosen_host[0]
        chosen_host[0] = ""
        if streaming_root and streaming_root.exists():
            candidates = []
            for pck_file in streaming_root.rglob(game.soundbank_pck_glob):
                try:
                    candidates.append((pck_file.stat().st_size, pck_file.name))
                except OSError:
                    continue
            if candidates:
                chosen_host[0] = min(candidates)[1]
        return chosen_host[0]

    def _build_bnk_index():
        result = {}
        if not streaming_root or not streaming_root.exists():
            return result
        for pck_file in streaming_root.rglob(game.soundbank_pck_glob):
            try:
                indexer = PCKIndexer(str(pck_file))
                indexer.build_index()
            except Exception as e:
                logger.error(f"[Patch Resolver] Warning: failed to index {pck_file.name}: {e}")
                continue
            for bank in indexer.index_data.get("banks", []):
                result.setdefault(bank["id"], (pck_file, indexer))
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
                counterpart = soundbank_bnk_index.get(bnk_id)

                if counterpart is not None and wem_id is not None and _counterpart_has_wem(counterpart, bnk_id, wem_id):
                    # The SoundBank copy already holds the WEM: a plain merge there suffices.
                    target_pck = counterpart[0].name
                else:
                    # Counterpart missing or lacking the WEM, so bring the whole Patch BNK into a SoundBank the game loads.
                    # Replace the counterpart's old copy, or add it to a host when there is none.
                    target_pck = counterpart[0].name if counterpart is not None else _pick_host_soundbank()
                    if not target_pck:
                        logger.info(f"[Patch Resolver] BNK {bnk_id} has no host SoundBank, dropping entry {key}")
                        dropped += 1
                        continue
                    whole_bnk_ids.add(bnk_id)
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
                    logger.info(f"[Patch Resolver] WEM {wem_id} not found in any {game.streamed_pck_glob} of StreamingAssets, dropping entry {key}")
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

    # Collect every bnk_id that will be rebuilt (remapped + non-protected targets) for pristine extraction.
    target_bnk_ids = set()
    for pck_name, entries in resolved.items():
        for info in entries.values():
            bid = info.get("bnk_id")
            if bid is not None:
                try:
                    target_bnk_ids.add(int(bid))
                except (TypeError, ValueError):
                    pass

    patch_bnk_content = {}
    if not target_bnk_ids or not persistent_overrides:
        return {"remapped": remapped, "orphan_added": orphan_added, "dropped": dropped, "patch_bnk_content": patch_bnk_content}

    for override_pck in persistent_overrides:
        backup_path = override_pck.with_name(override_pck.name + BACKUP_SUFFIX)
        source_path = backup_path if backup_path.exists() else override_pck

        try:
            idx = PCKIndexer(str(source_path)).build_index()
        except Exception as e:
            logger.error(f"[Patch Resolver] Warning: failed to index {source_path.name}: {e}")
            continue

        bank_entries = [b for b in idx.get("banks", []) if b["id"] in target_bnk_ids]
        if not bank_entries:
            continue

        with open(source_path, "rb") as f:
            for bank in bank_entries:
                if bank["id"] in patch_bnk_content:
                    continue
                f.seek(bank["offset"])
                bnk_bytes = f.read(bank["size"])
                try:
                    bnk = BNKFile(bnk_bytes=bnk_bytes)
                    wem_map = {wid: bnk.extract_wem(wid) for wid in bnk.list_wems()}
                except Exception as e:
                    logger.error(f"[Patch Resolver] Warning: failed to parse BNK {bank['id']} from {source_path.name}: {e}")
                    continue
                entry = {"source": override_pck.name, "wems": wem_map}
                if bank["id"] in whole_bnk_ids:
                    # Carry the whole pristine BNK so the host SoundBank can add or replace it wholesale.
                    entry["full_bnk_bytes"] = bnk_bytes
                    entry["host_lang_id"] = bank["lang_id"]
                patch_bnk_content[bank["id"]] = entry

    return {
        "remapped": remapped,
        "orphan_added": orphan_added,
        "dropped": dropped,
        "patch_bnk_content": patch_bnk_content,
    }
