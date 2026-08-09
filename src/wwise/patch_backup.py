# Pristine backups of Patch.pck/Hotfix.pck, kept in the state dir so they survive the game wiping Persistent.
# A per-override tag from the game's audio_version_persist manifest triggers recapture when the game updates one.

import json
import shutil
from pathlib import Path
import xxhash

from src.core.config_manager import get_game_state_dir
from src.core.logger import get_logger

logger = get_logger(__name__)

BACKUP_SUFFIX = ".xxar_backup"
_MANIFEST_NAME = "audio_version_persist"

# {manifest_path: (mtime, {remoteName: entry})} so a manifest is parsed once per change.
_manifest_cache = {}


def _backup_root(game_id):
    return get_game_state_dir(game_id) / "patch_backups"


def _rel(live_pck, persistent_root):
    # Live override's path relative to the Persistent audio root, or None when it is outside.
    try:
        return Path(live_pck).relative_to(Path(persistent_root))
    except ValueError:
        return None


def backup_path(live_pck, persistent_root, game_id):
    # Mirror the live override's subpath into the backup dir, keeping the .xxar_backup suffix.
    rel = _rel(live_pck, persistent_root)
    if rel is None:
        return None
    return _backup_root(game_id) / rel.with_name(rel.name + BACKUP_SUFFIX)


def _ledger_path(game_id):
    return _backup_root(game_id) / "backup_index.json"


def _load_ledger(game_id):
    path = _ledger_path(game_id)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_ledger(game_id, ledger):
    path = _ledger_path(game_id)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(ledger, indent=2), encoding="utf-8")
    except Exception as e:
        logger.error(f"[Patch Backup] Failed to write ledger: {e}")


def _manifest_entry_map(persistent_root, game):
    # {remoteName: manifest entry} from audio_version_persist at the Persistent root, cached by mtime.
    # The manifest sits above the audio subpath, e.g. Persistent/audio_version_persist.
    persistent_root = Path(persistent_root)
    top = persistent_root
    for _ in range(len(game.persistent_audio_subpath) - 1):
        top = top.parent
    manifest = top / _MANIFEST_NAME
    if not manifest.exists():
        return {}
    try:
        mtime = manifest.stat().st_mtime
    except OSError:
        return {}
    cached = _manifest_cache.get(str(manifest))
    if cached and cached[0] == mtime:
        return cached[1]
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
        result = {f["remoteName"]: f for f in data.get("files", [])}
    except Exception as e:
        logger.error(f"[Patch Backup] Failed to parse {manifest.name}: {e}")
        result = {}
    _manifest_cache[str(manifest)] = (mtime, result)
    return result


def _remote_name(live_pck, persistent_root, game):
    # The manifest keys overrides by their path under the Persistent root, e.g. "Audio/Windows/Full/En/Patch.pck".
    rel = _rel(live_pck, persistent_root)
    if rel is None:
        return None
    prefix = game.persistent_audio_subpath[1:]
    return "/".join([*prefix, *rel.parts])


def _manifest_entry(live_pck, persistent_root, game):
    name = _remote_name(live_pck, persistent_root, game)
    if name is None:
        return {}
    return _manifest_entry_map(persistent_root, game).get(name) or {}


def _current_tag(live_pck, persistent_root, game):
    # The game's own content tag for this override (decimal xxh64 in a field named "md5"), or None.
    return _manifest_entry(live_pck, persistent_root, game).get("md5")


def _expected_size(live_pck, persistent_root, game):
    try:
        return int(_manifest_entry(live_pck, persistent_root, game).get("fileSize"))
    except (TypeError, ValueError):
        return None


def _size_matches(path, expected_size):
    if expected_size is None:
        return True
    try:
        return Path(path).stat().st_size == expected_size
    except OSError:
        return False


def _capture_backup(live_pck, bpath, tag):
    # Copy while hashing so the live file is read once; a decimal-tag mismatch discards the capture.
    h = xxhash.xxh64()
    with open(live_pck, "rb") as src, open(bpath, "wb") as dst:
        for chunk in iter(lambda: src.read(1 << 20), b""):
            h.update(chunk)
            dst.write(chunk)
    if str(tag).isdigit() and h.intdigest() != int(tag):
        bpath.unlink()
        return False
    shutil.copystat(live_pck, bpath)
    return True


def _drop_backup(bpath, rel_key, game_id, ledger):
    try:
        bpath.chmod(0o644)
        bpath.unlink()
    except OSError as e:
        logger.error(f"[Patch Backup] Failed to drop invalid backup {bpath.name}: {e}")
        return
    ledger.pop(rel_key, None)
    _save_ledger(game_id, ledger)


def _migrate_legacy_backup(live_pck, persistent_root, game):
    # Move a legacy co-located Persistent backup into the state dir before any read or capture.
    # Runs on access so no entry point can act on a missing state-dir backup while the live is nulled.
    bpath = backup_path(live_pck, persistent_root, game.id)
    if bpath is None or bpath.exists():
        return
    legacy = Path(live_pck).with_name(Path(live_pck).name + BACKUP_SUFFIX)
    if not legacy.exists():
        return
    try:
        bpath.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(legacy), str(bpath))
        ledger = _load_ledger(game.id)
        ledger[_rel(live_pck, persistent_root).as_posix()] = _current_tag(live_pck, persistent_root, game)
        _save_ledger(game.id, ledger)
        logger.info(f"[Patch Backup] Migrated legacy backup {legacy.name} into the state dir")
    except Exception as e:
        logger.error(f"[Patch Backup] Failed to migrate legacy backup {legacy.name}: {e}")


def _is_stale(rel_key, current_tag, ledger):
    # Stale only when both the stored and current tags are known and differ.
    # An unknown tag on either side keeps the existing backup, never recapturing from a possibly-nulled live file.
    stored = ledger.get(rel_key)
    return current_tag is not None and stored is not None and stored != current_tag


def pristine_path(live_pck, persistent_root, game):
    # Read side: the valid backup when present, else the live file (itself pristine for a fresh version).
    live_pck = str(live_pck)
    _migrate_legacy_backup(live_pck, persistent_root, game)
    bpath = backup_path(live_pck, persistent_root, game.id)
    if bpath is None:
        return live_pck
    rel = _rel(live_pck, persistent_root)
    rel_key = rel.as_posix()
    if (bpath.exists()
            and not _is_stale(rel_key, _current_tag(live_pck, persistent_root, game), _load_ledger(game.id))
            and _size_matches(bpath, _expected_size(live_pck, persistent_root, game))):
        return str(bpath)
    return live_pck


def ensure_backup(live_pck, persistent_root, game):
    # Write side: capture a pristine backup when missing, or recapture when the game's tag says the override changed.
    # The live file is verified against the manifest (size, then xxh64 while copying), so a non-pristine live is never enshrined.
    _migrate_legacy_backup(live_pck, persistent_root, game)
    bpath = backup_path(live_pck, persistent_root, game.id)
    if bpath is None:
        return None
    rel_key = _rel(live_pck, persistent_root).as_posix()
    current_tag = _current_tag(live_pck, persistent_root, game)
    expected_size = _expected_size(live_pck, persistent_root, game)
    ledger = _load_ledger(game.id)
    if bpath.exists() and not _is_stale(rel_key, current_tag, ledger):
        if _size_matches(bpath, expected_size):
            return bpath
        logger.error(f"[Patch Backup] Backup of {Path(live_pck).name} has the wrong size; discarding it")
        _drop_backup(bpath, rel_key, game.id, ledger)
    if not _size_matches(live_pck, expected_size):
        logger.error(f"[Patch Backup] Live {Path(live_pck).name} has the wrong size vs the manifest; refusing capture")
        return None
    try:
        bpath.parent.mkdir(parents=True, exist_ok=True)
        if not _capture_backup(live_pck, bpath, current_tag):
            logger.error(f"[Patch Backup] Live {Path(live_pck).name} does not match the manifest tag; refusing capture")
            return None
        ledger[rel_key] = current_tag
        _save_ledger(game.id, ledger)
        logger.info(f"[Patch Backup] Captured pristine {Path(live_pck).name} (tag={current_tag})")
    except Exception as e:
        logger.error(f"[Patch Backup] Failed to capture {Path(live_pck).name}: {e}")
        try:
            bpath.unlink()
        except OSError:
            pass
        return None
    return bpath


def restore_backups(persistent_root, game):
    # Copy every backup back over its live override in Persistent, then drop the backup and its ledger entry.
    root = _backup_root(game.id)
    if not root.exists():
        return 0
    persistent_root = Path(persistent_root)
    ledger = _load_ledger(game.id)
    restored = 0
    for bfile in root.rglob(f"*{BACKUP_SUFFIX}"):
        rel = bfile.relative_to(root)
        live_rel = rel.with_name(rel.name[:-len(BACKUP_SUFFIX)])
        target = persistent_root / live_rel
        if not _size_matches(bfile, _expected_size(target, persistent_root, game)):
            logger.error(f"[Patch Backup] Backup of {live_rel.as_posix()} has the wrong size; dropping it without restore")
            _drop_backup(bfile, live_rel.as_posix(), game.id, ledger)
            continue
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                target.chmod(0o644)
            bfile.chmod(0o644)
            shutil.copy2(bfile, target)
            bfile.unlink()
            ledger.pop(live_rel.as_posix(), None)
            restored += 1
            logger.info(f"[Patch Backup] Restored original {live_rel.as_posix()}")
        except Exception as e:
            logger.error(f"[Patch Backup] Failed to restore {live_rel.as_posix()}: {e}")
    _save_ledger(game.id, ledger)
    return restored


def migrate_persistent_backups(persistent_root, game):
    # Bulk move of any legacy co-located Persistent backups into the state dir (per-access migration is the safety net).
    persistent_root = Path(persistent_root) if persistent_root else None
    if not persistent_root or not persistent_root.exists():
        return 0
    moved = 0
    for old in persistent_root.rglob(f"*{BACKUP_SUFFIX}"):
        original_name = old.name[:-len(BACKUP_SUFFIX)]
        if not game.is_protected_pck(original_name):
            continue
        _migrate_legacy_backup(old.with_name(original_name), persistent_root, game)
        moved += 1
    return moved
