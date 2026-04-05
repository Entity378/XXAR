# Patches Patch.pck / Hotfix.pck when they contain BNK/WEM entries
# that would override the user's mod replacements.
# Originals are backed up as .xxar_backup and restored on mod removal.

import shutil
import tempfile
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

    # Collect all BNK and direct WEM replacements
    bnk_replacements = defaultdict(dict)
    direct_replacements = {}

    for _pck_name, files in (replacements or {}).items():
        for tracker_key, repl_info in files.items():
            wem_path = repl_info.get("wem_path", "")
            if not wem_path or not Path(wem_path).exists():
                continue

            bnk_id = repl_info.get("bnk_id")
            raw_id = repl_info.get("file_id") or (
                str(tracker_key).split("|")[-1]
                if "|" in str(tracker_key)
                else tracker_key
            )
            try:
                wem_id = int(raw_id)
            except (ValueError, TypeError):
                continue

            if bnk_id:
                bnk_replacements[int(bnk_id)][wem_id] = wem_path
            else:
                direct_replacements[wem_id] = wem_path

    if not bnk_replacements and not direct_replacements:
        return _empty_result()

    override_pcks = [
        p
        for p in persistent_root.rglob("*.pck")
        if p.name in OVERRIDE_PCK_NAMES
    ]
    if not override_pcks:
        return _empty_result()

    target_bnk_ids = set(bnk_replacements.keys())
    target_wem_ids = set(direct_replacements.keys())
    patched_pcks = 0
    all_patched_bnk_ids = set()
    all_patched_wem_ids = set()

    for override_pck in override_pcks:
        try:
            indexer = PCKIndexer(str(override_pck))
            index = indexer.build_index()
        except Exception as e:
            print(f"[Override Patcher] Failed to index {override_pck}: {e}")
            continue

        pck_bnk_ids = {entry["id"] for entry in index["banks"]}
        pck_wem_ids = {
            entry["id"]
            for entry in index["sounds"] + index["externals"]
        }

        conflicting_bnks = pck_bnk_ids & target_bnk_ids
        conflicting_wems = pck_wem_ids & target_wem_ids

        if not conflicting_bnks and not conflicting_wems:
            continue

        parts = []
        if conflicting_bnks:
            parts.append(f"{len(conflicting_bnks)} BNK(s)")
        if conflicting_wems:
            parts.append(f"{len(conflicting_wems)} WEM(s)")
        conflict_desc = " + ".join(parts)

        print(
            f"[Override Patcher] {override_pck.parent.name}/{override_pck.name}: "
            f"{conflict_desc} conflicting with mods"
        )
        if progress_callback:
            progress_callback(f"Patching {override_pck.name} ({conflict_desc})...")

        # Back up the original before patching
        backup_path = override_pck.with_name(override_pck.name + BACKUP_SUFFIX)
        if not backup_path.exists():
            try:
                shutil.copy2(override_pck, backup_path)
                print(
                    f"[Override Patcher] Backed up {override_pck.name} "
                    f"-> {backup_path.name}"
                )
            except Exception as e:
                print(
                    f"[Override Patcher] Failed to back up "
                    f"{override_pck.name}: {e}"
                )
                continue

        source_pck = backup_path

        temp_dir = None
        try:
            try:
                from ZZAR import get_temp_dir
                temp_dir = Path(
                    tempfile.mkdtemp(
                        prefix="xxar_override_", dir=str(get_temp_dir())
                    )
                )
            except Exception:
                temp_dir = Path(tempfile.mkdtemp(prefix="xxar_override_"))

            if override_pck.exists():
                override_pck.chmod(0o644)

            packer = PCKPacker(str(source_pck), str(override_pck))
            packer.load_original_pck()

            for bnk_id in conflicting_bnks:
                wem_map = bnk_replacements[bnk_id]
                bnk_dir = temp_dir / str(bnk_id)
                bnk_dir.mkdir(parents=True, exist_ok=True)

                for wem_id, wem_path in wem_map.items():
                    shutil.copy2(wem_path, bnk_dir / f"{wem_id}.wem")

                lang_id = 0
                for search_lang, bnks in packer.soundbank_titles.items():
                    if bnk_id in bnks:
                        lang_id = search_lang
                        break

                packer.replace_bnk_wems(bnk_id, str(bnk_dir), lang_id=lang_id)
                all_patched_bnk_ids.add(bnk_id)

            for wem_id in conflicting_wems:
                packer.replace_file(wem_id, direct_replacements[wem_id])
                all_patched_wem_ids.add(wem_id)

            packer.pack(use_patching=False)
            packer.close()

            patched_pcks += 1
            print(f"[Override Patcher] Patched {override_pck.name}")

        except Exception as e:
            print(f"[Override Patcher] Failed to patch {override_pck.name}: {e}")
            if backup_path.exists():
                try:
                    shutil.copy2(backup_path, override_pck)
                except Exception:
                    pass
        finally:
            if temp_dir and temp_dir.exists():
                shutil.rmtree(temp_dir, ignore_errors=True)

    if patched_pcks > 0:
        summary = (
            f"Patched {patched_pcks} override PCK(s) "
            f"({len(all_patched_bnk_ids)} BNK + "
            f"{len(all_patched_wem_ids)} WEM conflicts resolved)"
        )
        print(f"[Override Patcher] {summary}")
        if progress_callback:
            progress_callback(summary)

    return {
        "patched_pcks": patched_pcks,
        "patched_bnk_ids": all_patched_bnk_ids,
        "patched_wem_ids": all_patched_wem_ids,
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
    return {"patched_pcks": 0, "patched_bnk_ids": set(), "patched_wem_ids": set()}
