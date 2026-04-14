# Resolves mod entries that target protected override PCKs (Patch.pck/Hotfix.pck)
# by remapping them to the corresponding SoundBank/Streamed PCK in StreamingAssets
# (the one that originally contains the same bnk_id / wem_id). Also pre-extracts
# pristine BNK content from Patch.pck for BNKs that the main rebuild loop will
# need to merge with mod WEMs.
#
# Assumption of domain: every BNK/WEM id present in Patch.pck also exists in a
# SoundBank_SFX_*.pck / Streamed_SFX_*.pck (or equivalent per game) under
# StreamingAssets — Patch.pck is an override, not a source of new ids.

from pathlib import Path

from src.wwise.pck_indexer import PCKIndexer

BACKUP_SUFFIX = ".xxar_backup"


def resolve_and_extract(resolved, streaming_root, persistent_root, game):
    """Remap protected-PCK entries in `resolved` to their StreamingAssets
    counterpart and extract pristine BNK content from Patch.pck/Hotfix.pck for
    every BNK id that appears in `resolved` (after remap) AND in any override.

    `resolved` is mutated in place: protected-PCK keys are removed and their
    entries are moved under the discovered target pck_name.

    Returns:
        {
            "remapped": int,                # number of entries remapped
            "dropped":  int,                # entries that could not be resolved
            "patch_bnk_content": {
                bnk_id: {
                    "source": "Patch.pck"|"Hotfix.pck",
                    "wems": {wem_id: wem_bytes, ...},   # pristine
                },
                ...
            },
        }
    """
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
        return {"remapped": 0, "dropped": 0, "patch_bnk_content": {}}

    # Lazily-built streaming indexes.
    soundbank_bnk_index = None  # {bnk_id: pck_name}
    streamed_wem_index = None   # {wem_id: pck_name}

    def _build_bnk_index():
        result = {}
        if not streaming_root or not streaming_root.exists():
            return result
        for pck_file in streaming_root.rglob(game.soundbank_pck_glob):
            try:
                idx = PCKIndexer(str(pck_file)).build_index()
            except Exception as e:
                print(f"[Patch Resolver] Warning: failed to index {pck_file.name}: {e}")
                continue
            for bank in idx.get("banks", []):
                result.setdefault(bank["id"], pck_file.name)
        return result

    def _build_wem_index():
        result = {}
        if not streaming_root or not streaming_root.exists():
            return result
        for pck_file in streaming_root.rglob(game.streamed_pck_glob):
            try:
                idx = PCKIndexer(str(pck_file)).build_index()
            except Exception as e:
                print(f"[Patch Resolver] Warning: failed to index {pck_file.name}: {e}")
                continue
            for sound in idx.get("sounds", []):
                result.setdefault(sound["id"], pck_file.name)
            for ext in idx.get("externals", []):
                result.setdefault(ext["id"], pck_file.name)
        return result

    remapped = 0
    dropped = 0

    for pck_name in [n for n in list(resolved.keys()) if n in protected_names]:
        entries = resolved.pop(pck_name)
        for key, info in entries.items():
            file_type = str(info.get("file_type", "wem")).lower()
            target_pck = None

            if file_type == "bnk":
                bnk_id = info.get("bnk_id")
                if bnk_id is None:
                    print(f"[Patch Resolver] Entry {key} in {pck_name} has no bnk_id, dropping")
                    dropped += 1
                    continue
                if soundbank_bnk_index is None:
                    soundbank_bnk_index = _build_bnk_index()
                target_pck = soundbank_bnk_index.get(int(bnk_id))
                if not target_pck:
                    print(f"[Patch Resolver] BNK {bnk_id} not found in any {game.soundbank_pck_glob} of StreamingAssets, dropping entry {key}")
                    dropped += 1
                    continue
            else:
                raw_wid = info.get("file_id")
                if raw_wid is None:
                    raw_wid = str(key).split("|")[-1] if "|" in str(key) else key
                try:
                    wem_id = int(raw_wid)
                except (TypeError, ValueError):
                    print(f"[Patch Resolver] Cannot parse WEM id for {key}, dropping")
                    dropped += 1
                    continue
                if streamed_wem_index is None:
                    streamed_wem_index = _build_wem_index()
                target_pck = streamed_wem_index.get(wem_id)
                if not target_pck:
                    print(f"[Patch Resolver] WEM {wem_id} not found in any {game.streamed_pck_glob} of StreamingAssets, dropping entry {key}")
                    dropped += 1
                    continue

            dest = resolved.setdefault(target_pck, {})
            if key in dest:
                print(f"[Patch Resolver] Conflict on key {key}: entry already exists in {target_pck}, keeping existing (load order precedence)")
                continue
            dest[key] = info
            remapped += 1

    # Collect every bnk_id that will be rebuilt so we can extract pristine
    # content for merging. Includes BNKs targeted by remapped entries AND any
    # BNK a non-protected mod already targets that also exists in an override.
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
        return {"remapped": remapped, "dropped": dropped, "patch_bnk_content": patch_bnk_content}

    from src.wwise.bnk_handler import BNKFile

    for override_pck in persistent_overrides:
        backup_path = override_pck.with_name(override_pck.name + BACKUP_SUFFIX)
        source_path = backup_path if backup_path.exists() else override_pck

        try:
            idx = PCKIndexer(str(source_path)).build_index()
        except Exception as e:
            print(f"[Patch Resolver] Warning: failed to index {source_path.name}: {e}")
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
                    print(f"[Patch Resolver] Warning: failed to parse BNK {bank['id']} from {source_path.name}: {e}")
                    continue
                patch_bnk_content[bank["id"]] = {
                    "source": override_pck.name,
                    "wems": wem_map,
                }

    return {
        "remapped": remapped,
        "dropped": dropped,
        "patch_bnk_content": patch_bnk_content,
    }
