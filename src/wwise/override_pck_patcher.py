# Nulls conflicting BNK file_ids in the Patch.pck / Hotfix.pck file table
# so Wwise skips them and falls back to the modded SoundBank PCKs.
# Only 4 bytes per BNK are changed, file size stays identical.
# Originals are backed up as .xxar_backup and restored on mod removal.

import struct
import shutil
from pathlib import Path
from collections import defaultdict

from src.core.game_registry import get_game, DEFAULT_GAME_ID

BACKUP_SUFFIX = ".xxar_backup"


def patch_override_pcks(persistent_root, replacements, progress_callback=None):
    persistent_root = Path(persistent_root) if persistent_root else None
    if not persistent_root or not persistent_root.exists():
        return _empty_result()

    # Collect all BNK IDs that the user is modding
    target_bnk_ids = set()
    for _pck_name, files in (replacements or {}).items():
        for tracker_key, repl_info in files.items():
            bnk_id = repl_info.get("bnk_id")
            if bnk_id:
                target_bnk_ids.add(int(bnk_id))

    if not target_bnk_ids:
        return _empty_result()

    protected = get_game(DEFAULT_GAME_ID).protected_pcks
    override_pcks = [
        p for p in persistent_root.rglob("*.pck")
        if p.name in protected
    ]
    if not override_pcks:
        return _empty_result()

    patched_pcks = 0
    all_nulled_bnk_ids = set()

    for override_pck in override_pcks:
        backup_path = override_pck.with_name(override_pck.name + BACKUP_SUFFIX)
        if not backup_path.exists():
            try:
                shutil.copy2(override_pck, backup_path)
                print(f"[Override Patcher] Backed up {override_pck.name}")
            except Exception as e:
                print(f"[Override Patcher] Failed to back up {override_pck.name}: {e}")
                continue

        # Always start from the clean backup
        try:
            if override_pck.exists():
                override_pck.chmod(0o644)
            backup_path.chmod(0o644)
            shutil.copy2(backup_path, override_pck)
            override_pck.chmod(0o644)
        except Exception as e:
            print(f"[Override Patcher] Failed to restore from backup: {e}")
            continue

        try:
            nulled = _null_bnk_ids_in_file_table(override_pck, target_bnk_ids)
        except Exception as e:
            print(f"[Override Patcher] Failed to patch {override_pck.name}: {e}")
            try:
                shutil.copy2(backup_path, override_pck)
            except Exception:
                pass
            continue

        if nulled:
            patched_pcks += 1
            all_nulled_bnk_ids.update(nulled)
            print(f"[Override Patcher] Nulled {len(nulled)} BNK ID(s) in {override_pck.name}: {nulled}")

            # Verify the null actually stuck
            verify = _verify_bnk_ids_nulled(override_pck, nulled)
            if verify:
                print(f"[Override Patcher] VERIFY FAILED - these BNK IDs are still present: {verify}")
            else:
                print(f"[Override Patcher] Verified: all nulled BNK IDs confirmed as 0")

            if progress_callback:
                progress_callback(f"Patched {override_pck.name} ({len(nulled)} BNK conflicts)")

    return {
        "patched_pcks": patched_pcks,
        "patched_bnk_ids": all_nulled_bnk_ids,
    }


def _null_bnk_ids_in_file_table(pck_path, target_bnk_ids):
    # Parse the PCK header to find the banks file table, then null matching file_ids
    nulled = set()

    with open(pck_path, 'r+b') as f:
        magic = f.read(4)
        if magic != b'AKPK':
            return nulled

        header_size = struct.unpack('<I', f.read(4))[0]
        _version = struct.unpack('<I', f.read(4))[0]
        sec1_size = struct.unpack('<I', f.read(4))[0]
        sec2_size = struct.unpack('<I', f.read(4))[0]
        sec3_size = struct.unpack('<I', f.read(4))[0]

        sec_sum = sec1_size + sec2_size + sec3_size + 0x10
        if sec_sum < header_size:
            f.read(4)  # sec4_size

        strings_start = f.tell()
        banks_start = strings_start + sec1_size

        f.seek(banks_start)
        if sec2_size == 0:
            return nulled

        file_count = struct.unpack('<I', f.read(4))[0]

        # Each entry: file_id(4) + blocksize(4) + size(4) + offset_block(4) + lang_id(4) = 20 bytes
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


def _verify_bnk_ids_nulled(pck_path, expected_nulled):
    # Re-read the file table and check that the nulled IDs are actually 0
    still_present = set()
    with open(pck_path, 'rb') as f:
        magic = f.read(4)
        if magic != b'AKPK':
            return expected_nulled

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
            return expected_nulled

        file_count = struct.unpack('<I', f.read(4))[0]
        for _ in range(file_count):
            file_id = struct.unpack('<I', f.read(4))[0]
            f.read(16)
            if file_id in expected_nulled:
                still_present.add(file_id)

    return still_present


def _empty_result():
    return {"patched_pcks": 0, "patched_bnk_ids": set()}
