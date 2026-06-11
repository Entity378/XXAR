# Unified management of game-original PCKs that may live in Persistent.
#
# Model: StreamingAssets is the home of the "true" originals. The game stages
# fresh originals into Persistent on in-game download (vs StreamingAssets on a
# launcher download) -- for ALL pcks, not just VO. This module PROMOTES any
# pristine original found in Persistent into StreamingAssets, keeping a
# hashes-only ledger (never pck bytes). The Persistent copy is then a pure
# overlay: reverting a mod is just deleting it and letting the game fall back to
# the StreamingAssets original.
#
# Pristine detection is per-file: if a "<stem>_<md5>.hash" sidecar sits next to
# the pck (HSR ships these for VO only) it is the ground truth; otherwise the
# mod_tracker is authoritative (XXAR is the only modder).
#
# Patch.pck / Hotfix.pck are out of scope -- they keep their own override
# handling in override_pck_patcher.py and are never promoted or deleted here.

import hashlib
import json
import shutil
from pathlib import Path

from src.core.config_manager import get_game_backup_dir
from src.core.game_registry import get_game
from src.core.logger import get_logger
from src.wwise.override_pck_patcher import restore_override_pck_backups

logger = get_logger(__name__)

_INDEX_FILE = "originals_index.json"
_CHUNK = 1 << 20  # 1 MB


def _md5(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def _parse_hash_sidecar(name):
    # "External0_826a...da.hash" -> ("External0.pck", "826a...da").
    if not name.endswith(".hash"):
        return None
    stem = name[:-5]
    parts = stem.rsplit("_", 1)
    if len(parts) != 2:
        return None
    pck_stem, md5_part = parts
    md5_part = md5_part.lower()
    if len(md5_part) != 32:
        return None
    try:
        int(md5_part, 16)
    except ValueError:
        return None
    return (f"{pck_stem}.pck", md5_part)


def _scan_sidecars(folder):
    # {pck_name: original_md5} from the *.hash sidecars in a single folder.
    out = {}
    try:
        for h in folder.glob("*.hash"):
            parsed = _parse_hash_sidecar(h.name)
            if parsed:
                out[parsed[0]] = parsed[1]
    except OSError:
        pass
    return out


def _load_index(backup_root):
    f = backup_root / _INDEX_FILE
    if not f.is_file():
        return {"schema": 1, "entries": {}}
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
        data.setdefault("entries", {})
        return data
    except Exception:
        return {"schema": 1, "entries": {}}


def _save_index(backup_root, index):
    try:
        backup_root.mkdir(parents=True, exist_ok=True)
        (backup_root / _INDEX_FILE).write_text(
            json.dumps(index, indent=2), encoding="utf-8"
        )
    except Exception as e:
        logger.error(f"[Persistent Originals] Failed to save index: {e}")


def _copy_original(src, dst):
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        dst.chmod(0o644)
    shutil.copy2(src, dst)
    dst.chmod(0o644)


def has_streaming_original(streaming_root, rel_path):
    return (Path(streaming_root) / rel_path).is_file()


def promote_originals(game_id, streaming_root, persistent_root, modded_keys, progress_cb=None):
    # Copy pristine originals found in Persistent up into StreamingAssets, so the
    # Persistent copy becomes a deletable overlay. Updates the hashes-only ledger.
    streaming_root = Path(streaming_root)
    persistent_root = Path(persistent_root)
    stats = {"promoted": 0, "updated": 0, "skipped_modded": 0, "orphan": 0}
    if not persistent_root.is_dir():
        return stats

    protected = get_game(game_id).protected_pcks
    modded_names = set(modded_keys or ())
    backup_root = get_game_backup_dir(game_id)
    index = _load_index(backup_root)
    entries = index["entries"]
    sidecar_cache = {}
    dirty = False

    for pck in persistent_root.rglob("*.pck"):
        if pck.name in protected:
            continue
        try:
            rel = pck.relative_to(persistent_root).as_posix()
        except ValueError:
            continue

        folder = pck.parent
        if folder not in sidecar_cache:
            sidecar_cache[folder] = _scan_sidecars(folder)
        sidecar_md5 = sidecar_cache[folder].get(pck.name)

        try:
            st = pck.stat()
        except OSError:
            continue
        size, mtime = st.st_size, int(st.st_mtime)
        s_path = streaming_root / rel

        # Fast-path: an unchanged file we already recorded as the original, with
        # the StreamingAssets copy in place -> nothing to do, skip the rehash.
        entry = entries.get(rel)
        if (entry and entry.get("size") == size and entry.get("mtime") == mtime
                and s_path.is_file()):
            continue

        # Decide pristine vs mod (hash only when a sidecar forces a comparison or
        # the file looks pristine -- never hash a tracker-flagged mod).
        if sidecar_md5 is not None:
            disk_md5 = _md5(pck)
            if disk_md5 != sidecar_md5:
                stats["skipped_modded"] += 1
                if not s_path.is_file():
                    stats["orphan"] += 1
                    if progress_cb:
                        progress_cb(f"Warning: no original for modded {rel}")
                continue
            original_md5, ground = sidecar_md5, "hash"
        else:
            if pck.name in modded_names:
                stats["skipped_modded"] += 1
                if not s_path.is_file():
                    stats["orphan"] += 1
                    if progress_cb:
                        progress_cb(f"Warning: no original for modded {rel}")
                continue
            disk_md5 = _md5(pck)
            original_md5, ground = disk_md5, "tracker"

        # P is pristine: fill a missing original, or update a differing one.
        if not s_path.is_file():
            try:
                _copy_original(pck, s_path)
                stats["promoted"] += 1
                logger.info(f"[Persistent Originals] Promoted {rel} into StreamingAssets")
                if progress_cb:
                    progress_cb(f"Secured original: {rel}")
            except Exception as e:
                logger.error(f"[Persistent Originals] Failed to promote {rel}: {e}")
                continue
        else:
            try:
                if _md5(s_path) != disk_md5:
                    _copy_original(pck, s_path)
                    stats["updated"] += 1
                    logger.info(f"[Persistent Originals] Updated original {rel} in StreamingAssets")
            except Exception as e:
                logger.error(f"[Persistent Originals] Failed to update {rel}: {e}")
                continue

        entries[rel] = {
            "original_md5": original_md5,
            "size": size,
            "mtime": mtime,
            "ground_truth": ground,
            "sidecar_md5": sidecar_md5,
        }
        dirty = True

    if dirty:
        _save_index(backup_root, index)
    return stats


def cleanup_persistent_overlay(game_id, streaming_root, persistent_root, modded_keys, progress_cb=None):
    # Shared replacement for the duplicated cleanup blocks: secure originals into
    # StreamingAssets, wipe the Persistent overlay (only where a StreamingAssets
    # original guarantees fallback), then restore protected-pck backups.
    streaming_root = Path(streaming_root)
    persistent_root = Path(persistent_root)
    result = {"promoted": 0, "updated": 0, "skipped_modded": 0, "orphan": 0,
              "deleted": 0, "kept_orphan": 0, "override_restored": 0}
    if not persistent_root.is_dir():
        return result

    result.update(promote_originals(
        game_id, streaming_root, persistent_root, modded_keys, progress_cb
    ))

    protected = get_game(game_id).protected_pcks
    deleted = kept = 0
    for pck in persistent_root.rglob("*.pck"):
        if pck.name in protected:
            continue
        try:
            rel = pck.relative_to(persistent_root).as_posix()
        except ValueError:
            continue
        if not has_streaming_original(streaming_root, rel):
            kept += 1  # orphan: no original to fall back to -> never delete
            continue
        try:
            pck.chmod(0o644)
            pck.unlink()
            deleted += 1
        except Exception as e:
            logger.error(f"[Persistent Originals] Failed to delete {rel}: {e}")
    result["deleted"] = deleted
    result["kept_orphan"] = kept

    try:
        result["override_restored"] = restore_override_pck_backups(persistent_root)
    except Exception as e:
        logger.error(f"[Persistent Originals] Failed to restore override backups: {e}")

    return result
