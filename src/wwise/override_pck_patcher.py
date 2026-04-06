# Handles Patch.pck / Hotfix.pck conflicts with modded SoundBank PCKs.
# 1. Finds BNK IDs in override PCKs that conflict with modded BNKs
# 2. Injects any extra WEMs (added by game updates) from the override BNK
#    into the modded SoundBank BNK so no audio is lost
# 3. Nulls the conflicting BNK file_id in the override PCK file table
#    so Wwise skips it and loads the modded SoundBank version instead
# File size of override PCKs stays identical (only 4 bytes changed per BNK).
# Originals are backed up as .xxar_backup and restored on mod removal.

import struct
import shutil
from pathlib import Path
from io import BytesIO

from src.core.game_registry import get_game, DEFAULT_GAME_ID

BACKUP_SUFFIX = ".xxar_backup"


def patch_override_pcks(persistent_root, replacements, streaming_root=None, progress_callback=None):
    persistent_root = Path(persistent_root) if persistent_root else None
    if not persistent_root or not persistent_root.exists():
        return _empty_result()

    # Collect BNK IDs and which PCK they belong to
    bnk_to_pck = {}
    for pck_name, files in (replacements or {}).items():
        for tracker_key, repl_info in files.items():
            bnk_id = repl_info.get("bnk_id")
            if bnk_id:
                bnk_to_pck[int(bnk_id)] = pck_name

    if not bnk_to_pck:
        return _empty_result()

    protected = get_game(DEFAULT_GAME_ID).protected_pcks
    override_pcks = [
        p for p in persistent_root.rglob("*.pck")
        if p.name in protected
    ]
    if not override_pcks:
        return _empty_result()

    target_bnk_ids = set(bnk_to_pck.keys())
    patched_pcks = 0
    all_nulled_bnk_ids = set()

    for override_pck in override_pcks:
        # Back up the original
        backup_path = override_pck.with_name(override_pck.name + BACKUP_SUFFIX)
        if not backup_path.exists():
            try:
                shutil.copy2(override_pck, backup_path)
                print(f"[Override Patcher] Backed up {override_pck.name}")
            except Exception as e:
                print(f"[Override Patcher] Failed to back up {override_pck.name}: {e}")
                continue

        # Restore from clean backup before patching
        try:
            if override_pck.exists():
                override_pck.chmod(0o644)
            backup_path.chmod(0o644)
            shutil.copy2(backup_path, override_pck)
            override_pck.chmod(0o644)
        except Exception as e:
            print(f"[Override Patcher] Failed to restore from backup: {e}")
            continue

        # Find which BNK IDs in this override PCK conflict with mods
        try:
            from src.wwise.pck_indexer import PCKIndexer
            indexer = PCKIndexer(str(override_pck))
            index = indexer.build_index()
        except Exception as e:
            print(f"[Override Patcher] Failed to index {override_pck.name}: {e}")
            continue

        pck_bnk_ids = {entry["id"] for entry in index["banks"]}
        conflicting = pck_bnk_ids & target_bnk_ids
        if not conflicting:
            continue

        # Inject extra WEMs from override BNK into the modded SoundBank
        if streaming_root:
            _inject_extra_wems(
                override_pck, conflicting, bnk_to_pck,
                persistent_root, Path(streaming_root)
            )

        # Null the BNK IDs in the file table
        try:
            nulled = _null_bnk_ids_in_file_table(override_pck, conflicting)
        except Exception as e:
            print(f"[Override Patcher] Failed to null BNK IDs in {override_pck.name}: {e}")
            try:
                shutil.copy2(backup_path, override_pck)
            except Exception:
                pass
            continue

        if nulled:
            patched_pcks += 1
            all_nulled_bnk_ids.update(nulled)
            print(f"[Override Patcher] Nulled {len(nulled)} BNK ID(s) in {override_pck.name}: {nulled}")
            if progress_callback:
                progress_callback(f"Patched {override_pck.name} ({len(nulled)} BNK conflicts)")

    return {
        "patched_pcks": patched_pcks,
        "patched_bnk_ids": all_nulled_bnk_ids,
    }


def _inject_extra_wems(override_pck, conflicting_bnk_ids, bnk_to_pck, persistent_root, streaming_root):
    from src.wwise.pck_packer import PCKPacker
    from src.wwise.bnk_handler import BNKFile

    for bnk_id in conflicting_bnk_ids:
        pck_name = bnk_to_pck.get(bnk_id)
        if not pck_name:
            continue

        # Find the modded SoundBank in Persistent
        sb_persistent = _find_pck(persistent_root, pck_name)
        if not sb_persistent:
            continue

        # Load the override BNK to get its WEM IDs
        try:
            override_packer = PCKPacker(str(override_pck), "dummy")
            override_packer.load_original_pck()
            override_bnk = _extract_bnk(override_packer, bnk_id)
            override_packer.close()
            if not override_bnk:
                continue
        except Exception as e:
            print(f"[Override Patcher] Failed to read BNK {bnk_id} from {override_pck.name}: {e}")
            continue

        # Load the SoundBank BNK to compare
        try:
            sb_packer = PCKPacker(str(sb_persistent), "dummy")
            sb_packer.load_original_pck()
            sb_bnk = _extract_bnk(sb_packer, bnk_id)
            sb_packer.close()
            if not sb_bnk:
                continue
        except Exception as e:
            print(f"[Override Patcher] Failed to read BNK {bnk_id} from {sb_persistent.name}: {e}")
            continue

        override_wems = set(override_bnk.list_wems())
        sb_wems = set(sb_bnk.list_wems())
        extras = override_wems - sb_wems

        if not extras:
            continue

        # Inject the extra WEMs into the SoundBank BNK and rewrite
        print(f"[Override Patcher] Injecting {len(extras)} extra WEM(s) from "
              f"{override_pck.name} into {sb_persistent.name} BNK {bnk_id}")

        for wem_id in extras:
            data = override_bnk.extract_wem(wem_id)
            sb_bnk.add_wem(wem_id, data)

        # Repack the SoundBank with the updated BNK
        try:
            sb_packer2 = PCKPacker(str(sb_persistent), str(sb_persistent))
            sb_packer2.load_original_pck()

            modified_bytes = sb_bnk.get_bytes()
            new_fi = len(sb_packer2.file_list)
            sb_packer2.file_list.append(BytesIO(modified_bytes))

            lang_id = 0
            for lid, bnks in sb_packer2.soundbank_titles.items():
                if bnk_id in bnks:
                    lang_id = lid
                    break
            sb_packer2.soundbank_titles[lang_id][bnk_id] = [(new_fi, len(modified_bytes), 0)]

            sb_persistent.chmod(0o644)

            # Find the original streaming PCK to rebuild from (avoids input=output issue)
            sb_streaming = _find_pck(streaming_root, pck_name)
            if sb_streaming:
                # Rebuild from streaming with the modified BNK
                sb_packer2.close()
                sb_packer3 = PCKPacker(str(sb_streaming), str(sb_persistent))
                sb_packer3.load_original_pck()

                # Transfer the modified BNK
                new_fi3 = len(sb_packer3.file_list)
                sb_packer3.file_list.append(BytesIO(modified_bytes))
                for lid, bnks in sb_packer3.soundbank_titles.items():
                    if bnk_id in bnks:
                        sb_packer3.soundbank_titles[lid][bnk_id] = [(new_fi3, len(modified_bytes), 0)]
                        break

                sb_packer3.pack(use_patching=False)
                sb_packer3.close()
            else:
                sb_packer2.pack(use_patching=False)
                sb_packer2.close()

            print(f"[Override Patcher] SoundBank {pck_name} updated with {len(extras)} extra WEM(s)")
        except Exception as e:
            print(f"[Override Patcher] Failed to update SoundBank {pck_name}: {e}")


def _extract_bnk(packer, bnk_id):
    from src.wwise.bnk_handler import BNKFile
    for lang_id, bnks in packer.soundbank_titles.items():
        if bnk_id in bnks:
            fi, sz, off = bnks[bnk_id][0]
            f = packer.file_list[fi]
            f.seek(off)
            return BNKFile(bnk_bytes=f.read(sz))
    return None


def _find_pck(root, pck_name):
    if not root or not root.exists():
        return None
    direct = root / pck_name
    if direct.exists():
        return direct
    for p in root.rglob(pck_name):
        return p
    return None


def _null_bnk_ids_in_file_table(pck_path, target_bnk_ids):
    nulled = set()
    with open(pck_path, 'r+b') as f:
        magic = f.read(4)
        if magic != b'AKPK':
            return nulled

        header_size = struct.unpack('<I', f.read(4))[0]
        f.read(4)  # version
        sec1_size = struct.unpack('<I', f.read(4))[0]
        sec2_size = struct.unpack('<I', f.read(4))[0]
        sec3_size = struct.unpack('<I', f.read(4))[0]
        sec_sum = sec1_size + sec2_size + sec3_size + 0x10
        if sec_sum < header_size:
            f.read(4)

        banks_start = f.tell() + sec1_size
        f.seek(banks_start)
        if sec2_size == 0:
            return nulled

        file_count = struct.unpack('<I', f.read(4))[0]
        for _ in range(file_count):
            entry_pos = f.tell()
            file_id = struct.unpack('<I', f.read(4))[0]
            f.read(16)
            if file_id in target_bnk_ids:
                f.seek(entry_pos)
                f.write(struct.pack('<I', 0))
                f.seek(entry_pos + 20)
                nulled.add(file_id)

    return nulled


def restore_override_pck_backups(persistent_root):
    persistent_root = Path(persistent_root) if persistent_root else None
    if not persistent_root or not persistent_root.exists():
        return 0

    protected = get_game(DEFAULT_GAME_ID).protected_pcks
    restored = 0
    for backup_file in persistent_root.rglob(f"*{BACKUP_SUFFIX}"):
        original_name = backup_file.name.replace(BACKUP_SUFFIX, "")
        if original_name not in protected:
            continue

        target = backup_file.with_name(original_name)
        try:
            backup_file.chmod(0o644)
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
    return {"patched_pcks": 0, "patched_bnk_ids": set()}
