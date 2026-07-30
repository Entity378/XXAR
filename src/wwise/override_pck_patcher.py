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
# Originals are backed up in the state dir (see patch_backup) and restored on mod removal.

import shutil
import struct
from pathlib import Path

from src.core.logger import get_logger
from src.wwise import patch_backup
from src.wwise.bnk_handler import BNKFile
from src.wwise.pck_indexer import PCKIndexer

logger = get_logger(__name__)


def _target_wems_by_bnk(replacements):
    # bnk_id -> set(wem_id) the mods replace.
    # The WEM id is unique per language, so it tells which language's override owns each colliding bnk.
    result = {}
    for files in (replacements or {}).values():
        for tracker_key, repl_info in files.items():
            bnk_id = repl_info.get("bnk_id")
            if bnk_id is None:
                continue
            wem_id = repl_info.get("file_id")
            if wem_id is None:
                wem_id = str(tracker_key).split("|")[-1] if "|" in str(tracker_key) else tracker_key
            try:
                result.setdefault(int(bnk_id), set()).add(int(wem_id))
            except (TypeError, ValueError):
                continue
    return result


def _owners_by_bnk(override_pcks, target_wems_by_bnk, persistent_root, game):
    # bnk_id -> set of override paths whose pristine copy of that bnk holds a modded WEM (its language).
    # Read from the pristine backup when valid, so a bnk already nulled by a prior apply is still seen.
    owners = {}
    for override_pck in override_pcks:
        read_path = patch_backup.pristine_path(override_pck, persistent_root, game)
        try:
            index = PCKIndexer(str(read_path)).build_index()
        except Exception as e:
            logger.error(f"[Override Patcher] Failed to index {read_path.name} for ownership: {e}")
            continue
        bank_by_id = {entry["id"]: entry for entry in index.get("banks", [])}
        with open(read_path, "rb") as handle:
            for bnk_id, wanted_wems in target_wems_by_bnk.items():
                bank = bank_by_id.get(bnk_id)
                if not bank or not wanted_wems:
                    continue
                try:
                    handle.seek(bank["offset"])
                    embedded_wems = set(BNKFile(bnk_bytes=handle.read(bank["size"])).list_wems())
                except Exception:
                    continue
                if embedded_wems & wanted_wems:
                    owners.setdefault(bnk_id, set()).add(override_pck)
    return owners


def patch_override_pcks(persistent_root, replacements, game, streaming_root=None, progress_callback=None):
    persistent_root = Path(persistent_root) if persistent_root else None
    if not persistent_root or not persistent_root.exists():
        return _empty_result()

    # Collect BNK IDs targeted by any mod, plus the modded WEMs per bnk for the per-language gate below.
    # A nulled override entry makes Wwise fall back to the modded SoundBank/Streamed PCK.
    target_wems_by_bnk = _target_wems_by_bnk(replacements)
    target_bnk_ids = set(target_wems_by_bnk)

    if not target_bnk_ids:
        return _empty_result()

    protected = game.protected_pcks
    override_pcks = [
        p for p in persistent_root.rglob("*.pck")
        if p.name in protected
    ]
    if not override_pcks:
        return _empty_result()

    # A voice bnk_id lives in both En\Patch.pck and Jp\Patch.pck with different audio.
    # Null it only in the override holding the modded WEM, so an En mod never disturbs the Jp copy.
    owners_by_bnk = _owners_by_bnk(override_pcks, target_wems_by_bnk, persistent_root, game)

    patched_pcks = 0
    all_nulled_bnk_ids = set()

    for override_pck in override_pcks:
        # Pristine backup lives in the machine-local state dir so it survives the game wiping Persistent.
        backup_path = patch_backup.ensure_backup(override_pck, persistent_root, game)
        if backup_path is None or not backup_path.exists():
            logger.error(f"[Override Patcher] No pristine backup for {override_pck.name}, skipping")
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
            indexer = PCKIndexer(str(override_pck))
            index = indexer.build_index()
        except Exception as e:
            logger.error(f"[Override Patcher] Failed to index {override_pck.name}: {e}")
            continue

        pck_bnk_ids = {entry["id"] for entry in index["banks"]}
        conflicting = pck_bnk_ids & target_bnk_ids
        # Null the bnk only in the override that owns it by WEM.
        # If no override owns it (WEM not embedded anywhere), fall back to nulling wherever it conflicts.
        to_null = {
            bnk_id for bnk_id in conflicting
            if not owners_by_bnk.get(bnk_id) or override_pck in owners_by_bnk[bnk_id]
        }
        if not to_null:
            continue

        try:
            nulled = _null_bnk_ids_in_file_table(override_pck, to_null)
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


def restore_override_pck_backups(persistent_root, game):
    # Restore originals from the state-dir backups, first sweeping any legacy co-located backup into it.
    patch_backup.migrate_persistent_backups(persistent_root, game)
    return patch_backup.restore_backups(persistent_root, game)


def _empty_result():
    return {"patched_pcks": 0, "patched_bnk_ids": set()}
