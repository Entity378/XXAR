# Strips conflicting WEM entries from Patch.pck / Hotfix.pck so the game
# falls back to the modded copies in the regular SoundBank PCKs.
# Uses patching mode to keep the file size unchanged (avoids game validation nuke).
# Originals are backed up as .xxar_backup and restored on mod removal.

import shutil
from pathlib import Path
from collections import defaultdict

OVERRIDE_PCK_NAMES = {"Patch.pck", "Hotfix.pck"}
BACKUP_SUFFIX = ".xxar_backup"


def patch_override_pcks(persistent_root, replacements, progress_callback=None):
    from src.wwise.pck_packer import PCKPacker
    from src.wwise.pck_indexer import PCKIndexer

    persistent_root = Path(persistent_root) if persistent_root else None
    if not persistent_root or not persistent_root.exists():
        return _empty_result()

    # Collect all BNK WEM IDs that the user is modding
    bnk_wem_ids = defaultdict(set)
    for _pck_name, files in (replacements or {}).items():
        for tracker_key, repl_info in files.items():
            bnk_id = repl_info.get("bnk_id")
            if not bnk_id:
                continue

            raw_id = repl_info.get("file_id") or (
                str(tracker_key).split("|")[-1]
                if "|" in str(tracker_key)
                else tracker_key
            )
            try:
                wem_id = int(raw_id)
            except (ValueError, TypeError):
                continue

            bnk_wem_ids[int(bnk_id)].add(wem_id)

    if not bnk_wem_ids:
        return _empty_result()

    override_pcks = [
        p for p in persistent_root.rglob("*.pck")
        if p.name in OVERRIDE_PCK_NAMES
    ]
    if not override_pcks:
        return _empty_result()

    target_bnk_ids = set(bnk_wem_ids.keys())
    patched_pcks = 0
    all_stripped_bnk_ids = set()
    total_stripped_wems = 0

    for override_pck in override_pcks:
        try:
            indexer = PCKIndexer(str(override_pck))
            index = indexer.build_index()
        except Exception as e:
            print(f"[Override Patcher] Failed to index {override_pck}: {e}")
            continue

        pck_bnk_ids = {entry["id"] for entry in index["banks"]}
        conflicting_bnks = pck_bnk_ids & target_bnk_ids

        if not conflicting_bnks:
            continue

        print(
            f"[Override Patcher] {override_pck.parent.name}/{override_pck.name}: "
            f"{len(conflicting_bnks)} BNK(s) conflicting with mods"
        )
        if progress_callback:
            progress_callback(f"Stripping conflicts from {override_pck.name}...")

        backup_path = override_pck.with_name(override_pck.name + BACKUP_SUFFIX)
        if not backup_path.exists():
            try:
                shutil.copy2(override_pck, backup_path)
                print(f"[Override Patcher] Backed up {override_pck.name}")
            except Exception as e:
                print(f"[Override Patcher] Failed to back up {override_pck.name}: {e}")
                continue

        # Always rebuild from the clean backup
        source_pck = backup_path

        try:
            if override_pck.exists():
                override_pck.chmod(0o644)

            packer = PCKPacker(str(source_pck), str(override_pck))
            packer.load_original_pck()

            stripped_in_pck = 0
            for bnk_id in conflicting_bnks:
                wem_ids = bnk_wem_ids[bnk_id]

                lang_id = 0
                for search_lang, bnks in packer.soundbank_titles.items():
                    if bnk_id in bnks:
                        lang_id = search_lang
                        break

                removed = packer.remove_wems_from_bnk(bnk_id, wem_ids, lang_id=lang_id)
                if removed > 0:
                    all_stripped_bnk_ids.add(bnk_id)
                    stripped_in_pck += removed

            if stripped_in_pck == 0:
                packer.close()
                continue

            # Patching mode keeps the file size unchanged
            packer.pack(use_patching=True)
            packer.close()

            patched_pcks += 1
            total_stripped_wems += stripped_in_pck
            print(f"[Override Patcher] Stripped {stripped_in_pck} WEM(s) from {override_pck.name}")

        except Exception as e:
            print(f"[Override Patcher] Failed to patch {override_pck.name}: {e}")
            if backup_path.exists():
                try:
                    shutil.copy2(backup_path, override_pck)
                except Exception:
                    pass

    if patched_pcks > 0:
        summary = (
            f"Stripped {total_stripped_wems} conflicting WEM(s) from "
            f"{patched_pcks} override PCK(s)"
        )
        print(f"[Override Patcher] {summary}")
        if progress_callback:
            progress_callback(summary)

    return {
        "patched_pcks": patched_pcks,
        "patched_bnk_ids": all_stripped_bnk_ids,
        "stripped_wems": total_stripped_wems,
    }


def restore_override_pck_backups(persistent_root):
    persistent_root = Path(persistent_root) if persistent_root else None
    if not persistent_root or not persistent_root.exists():
        return 0

    restored = 0
    for backup_file in persistent_root.rglob(f"*{BACKUP_SUFFIX}"):
        original_name = backup_file.name.replace(BACKUP_SUFFIX, "")
        if original_name not in OVERRIDE_PCK_NAMES:
            continue

        target = backup_file.with_name(original_name)
        try:
            if target.exists():
                target.chmod(0o644)
            shutil.copy2(backup_file, target)
            backup_file.unlink()
            restored += 1
            print(f"[Override Patcher] Restored original {original_name}")
        except Exception as e:
            print(f"[Override Patcher] Failed to restore {original_name}: {e}")

    return restored


def _empty_result():
    return {"patched_pcks": 0, "patched_bnk_ids": set(), "stripped_wems": 0}
