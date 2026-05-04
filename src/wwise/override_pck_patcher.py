# Handles Patch.pck / Hotfix.pck conflicts with modded SoundBank PCKs.
# Strategy: null the BNK file_id in the override PCK file table so Wwise skips
# it and falls back to the modded SoundBank/Streamed PCK in Persistent.
#
# The WEM transport (moving Patch.pck BNK content into the dest SoundBank so
# no audio is lost when the override BNK is nulled) is handled earlier in the
# rebuild pipeline — see PCKPacker.merge_bnk_wems() combined with pristine
# BNK extraction done by patch_target_resolver.resolve_and_extract().
#
# File size of override PCKs stays identical (only 4 bytes changed per BNK).
# Originals are backed up as .xxar_backup and restored on mod removal.

import struct
import shutil
from pathlib import Path

from src.core.game_registry import get_game, DEFAULT_GAME_ID

from src.core.logger import get_logger
logger = get_logger(__name__)

BACKUP_SUFFIX = ".xxar_backup"


def patch_override_pcks(persistent_root, replacements, streaming_root=None, progress_callback=None):
    persistent_root = Path(persistent_root) if persistent_root else None
    if not persistent_root or not persistent_root.exists():
        return _empty_result()

    # Collect BNK IDs targeted by any mod.
    # These are the ones whose override entry (if present) must be nulled so Wwise falls back to the modded PCK.
    target_bnk_ids = set()
    for pck_name, files in (replacements or {}).items():
        for tracker_key, repl_info in files.items():
            bnk_id = repl_info.get("bnk_id")
            if bnk_id:
                try:
                    target_bnk_ids.add(int(bnk_id))
                except (TypeError, ValueError):
                    pass

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
                logger.info(f"[Override Patcher] Backed up {override_pck.name}")
            except Exception as e:
                logger.error(f"[Override Patcher] Failed to back up {override_pck.name}: {e}")
                continue

        # Restore from clean backup before patching so repeated applies are idempotent.
        try:
            if override_pck.exists():
                override_pck.chmod(0o644)
            backup_path.chmod(0o644)
            shutil.copy2(backup_path, override_pck)
            override_pck.chmod(0o644)
        except Exception as e:
            logger.error(f"[Override Patcher] Failed to restore from backup: {e}")
            continue

        try:
            from src.wwise.pck_indexer import PCKIndexer
            indexer = PCKIndexer(str(override_pck))
            index = indexer.build_index()
        except Exception as e:
            logger.error(f"[Override Patcher] Failed to index {override_pck.name}: {e}")
            continue

        pck_bnk_ids = {entry["id"] for entry in index["banks"]}
        conflicting = pck_bnk_ids & target_bnk_ids
        if not conflicting:
            continue

        try:
            nulled = _null_bnk_ids_in_file_table(override_pck, conflicting)
        except Exception as e:
            logger.error(f"[Override Patcher] Failed to null BNK IDs in {override_pck.name}: {e}")
            try:
                shutil.copy2(backup_path, override_pck)
            except Exception:
                pass
            continue

        if nulled:
            patched_pcks += 1
            all_nulled_bnk_ids.update(nulled)
            logger.info(f"[Override Patcher] Nulled {len(nulled)} BNK ID(s) in {override_pck.name}: {nulled}")
            if progress_callback:
                progress_callback(f"Patched {override_pck.name} ({len(nulled)} BNK conflicts)")

    return {
        "patched_pcks": patched_pcks,
        "patched_bnk_ids": all_nulled_bnk_ids,
    }


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
            logger.info(f"[Override Patcher] Restored original {original_name}")
        except Exception as e:
            logger.error(f"[Override Patcher] Failed to restore {original_name}: {e}")

    return restored


def _empty_result():
    return {"patched_pcks": 0, "patched_bnk_ids": set()}
