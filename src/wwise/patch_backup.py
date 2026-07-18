# Pristine backups of Patch.pck/Hotfix.pck, kept in the state dir so they survive the game wiping Persistent.
# A per-override tag from the game's audio_version_persist manifest triggers recapture when the game updates one.

import json
import shutil
from pathlib import Path

from src.core.config_manager import get_game_state_dir
from src.core.logger import get_logger

logger = get_logger(__name__)

BACKUP_SUFFIX = ".xxar_backup"
_MANIFEST_NAME = "audio_version_persist"

# {manifest_path: (mtime, {remoteName: md5})} so a manifest is parsed once per change.
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


def _manifest_md5_map(persistent_root, game):
    # {remoteName: md5} from audio_version_persist at the Persistent root, cached by mtime.
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
        result = {f["remoteName"]: f.get("md5") for f in data.get("files", [])}
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


def _current_tag(live_pck, persistent_root, game):
    # The game's own md5 for this override, or None when the manifest can't answer.
    name = _remote_name(live_pck, persistent_root, game)
    if name is None:
        return None
    return _manifest_md5_map(persistent_root, game).get(name)


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
    if bpath.exists() and not _is_stale(rel_key, _current_tag(live_pck, persistent_root, game), _load_ledger(game.id)):
        return str(bpath)
    return live_pck


def ensure_backup(live_pck, persistent_root, game):
    # Write side: capture a pristine backup when missing, or recapture when the game's tag says the override changed.
    # Callers invoke this while the live file is pristine (before nulling, or after the game re-downloaded it).
    _migrate_legacy_backup(live_pck, persistent_root, game)
    bpath = backup_path(live_pck, persistent_root, game.id)
    if bpath is None:
        return None
    rel_key = _rel(live_pck, persistent_root).as_posix()
    current_tag = _current_tag(live_pck, persistent_root, game)
    ledger = _load_ledger(game.id)
    if bpath.exists() and not _is_stale(rel_key, current_tag, ledger):
        return bpath
    try:
        bpath.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(live_pck, bpath)
        ledger[rel_key] = current_tag
        _save_ledger(game.id, ledger)
        logger.info(f"[Patch Backup] Captured pristine {Path(live_pck).name} (tag={current_tag})")
    except Exception as e:
        logger.error(f"[Patch Backup] Failed to capture {Path(live_pck).name}: {e}")
        return bpath if bpath.exists() else None
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
    protected = set(game.protected_pcks)
    moved = 0
    for old in persistent_root.rglob(f"*{BACKUP_SUFFIX}"):
        original_name = old.name[:-len(BACKUP_SUFFIX)]
        if original_name not in protected:
            continue
        _migrate_legacy_backup(old.with_name(original_name), persistent_root, game)
        moved += 1
    return moved
