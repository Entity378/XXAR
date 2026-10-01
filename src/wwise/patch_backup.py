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


def _rel(live_pck, persistent_root: Path):
    # Live override's path relative to the Persistent audio root, or None when it is outside.
    try:
        return Path(live_pck).relative_to(persistent_root)
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


def _persistent_top(persistent_root: Path, game):
    # The Persistent folder itself, however deep below it the caller's audio root sits.
    for folder in (persistent_root, *persistent_root.parents):
        if folder.name == game.persistent_audio_subpath[0]:
            return folder
    return None


def _manifest_entry_map(persistent_root: Path, game):
    # {remoteName: manifest entry} from audio_version_persist at the Persistent root, cached by mtime.
    top = _persistent_top(persistent_root, game)
    if top is None:
        return {}
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
    top = _persistent_top(persistent_root, game)
    if top is None:
        return None
    try:
        return Path(live_pck).relative_to(top).as_posix()
    except ValueError:
        return None


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


def _size_matches(path: Path, expected_size):
    if expected_size is None:
        return True
    try:
        return path.stat().st_size == expected_size
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


def ensure_backup(live_pck: Path, persistent_root, game):
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
        logger.error(f"[Patch Backup] Backup of {live_pck.name} has the wrong size; discarding it")
        _drop_backup(bpath, rel_key, game.id, ledger)
    if not _size_matches(live_pck, expected_size):
        logger.error(f"[Patch Backup] Live {live_pck.name} has the wrong size vs the manifest; refusing capture")
        return None
    try:
        bpath.parent.mkdir(parents=True, exist_ok=True)
        if not _capture_backup(live_pck, bpath, current_tag):
            logger.error(f"[Patch Backup] Live {live_pck.name} does not match the manifest tag; refusing capture")
            return None
        ledger[rel_key] = current_tag
        _save_ledger(game.id, ledger)
        logger.info(f"[Patch Backup] Captured pristine {live_pck.name} (tag={current_tag})")
    except Exception as e:
        logger.error(f"[Patch Backup] Failed to capture {live_pck.name}: {e}")
        try:
            bpath.unlink()
        except OSError:
            pass
        return None
    return bpath


def restore_backups(persistent_root: Path, game):
    # Copy every backup back over its live override in Persistent, then drop the backup and its ledger entry.
    root = _backup_root(game.id)
    if not root.exists():
        return 0
    ledger = _load_ledger(game.id)
    restored = 0
    for bfile in root.rglob(f"*{BACKUP_SUFFIX}"):
        rel = bfile.relative_to(root)
        live_rel = rel.with_name(rel.name[:-len(BACKUP_SUFFIX)])
        target = persistent_root / live_rel
        if _is_stale(live_rel.as_posix(), _current_tag(target, persistent_root, game), ledger):
            logger.info(f"[Patch Backup] Backup of {live_rel.as_posix()} predates the game's update; dropping it without restore")
            _drop_backup(bfile, live_rel.as_posix(), game.id, ledger)
            continue
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


def _xxh64_tag(path):
    # The decimal xxh64 that audio_version_persist stores as an override's content tag.
    h = xxhash.xxh64()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return str(h.intdigest())


def _listed_override_tags(persistent_root: Path, game):
    # {path under persistent_root: current tag} of every protected override the game's manifest lists.
    top = _persistent_top(persistent_root, game)
    listed = {}
    for name, entry in _manifest_entry_map(persistent_root, game).items():
        tag = str(entry.get("md5", ""))
        if not game.is_protected_pck(name) or not tag.isdigit():
            continue
        try:
            listed[(top / name).relative_to(persistent_root).as_posix()] = tag
        except ValueError:
            continue
    return listed


def _adopt_pristine_copy(copy_path, listed, persistent_root, game, ledger):
    # Moves a copy into the empty backup slot of the override whose current tag its content hashes to.
    tag = _xxh64_tag(copy_path)
    for rel_key, current_tag in listed.items():
        slot = backup_path(persistent_root / rel_key, persistent_root, game.id)
        if current_tag != tag or slot.exists():
            continue
        slot.parent.mkdir(parents=True, exist_ok=True)
        copy_path.chmod(0o644)
        shutil.move(str(copy_path), str(slot))
        ledger[rel_key] = tag
        return rel_key
    return None


def repair_backups(persistent_root: Path, game):
    # Keeps only backups of the game's current originals, so a backup from an older game version is never restored.
    # Backups and stray copies an older audio root left behind fill the empty slot of the override they match, or are removed.
    listed = _listed_override_tags(persistent_root, game)
    if not listed:
        return 0
    root = _backup_root(game.id)
    ledger = _load_ledger(game.id)
    loaded_ledger = dict(ledger)
    strays = []
    for bfile in list(root.rglob(f"*{BACKUP_SUFFIX}")) if root.exists() else []:
        rel = bfile.relative_to(root)
        rel_key = rel.with_name(rel.name[:-len(BACKUP_SUFFIX)]).as_posix()
        if rel_key not in listed:
            ledger.pop(rel_key, None)
            strays.append(bfile)
            continue
        try:
            # Captures taken while the manifest was unreadable carry no tag, so their content is hashed once.
            if ledger.get(rel_key) is None:
                ledger[rel_key] = _xxh64_tag(bfile)
            if ledger[rel_key] != listed[rel_key]:
                bfile.chmod(0o644)
                bfile.unlink()
                ledger.pop(rel_key)
                logger.info(f"[Patch Backup] Backup of {rel_key} is not the game's current original; dropped it")
        except OSError as e:
            logger.error(f"[Patch Backup] Failed to check the backup of {rel_key}: {e}")
    for pck in persistent_root.rglob("*.pck"):
        if game.is_protected_pck(pck.name) and pck.relative_to(persistent_root).as_posix() not in listed:
            strays.append(pck)
    adopted = 0
    for stray in strays:
        try:
            owner_rel = _adopt_pristine_copy(stray, listed, persistent_root, game, ledger)
            if owner_rel:
                adopted += 1
                logger.info(f"[Patch Backup] Kept the stray copy {stray} as the original of {owner_rel}")
                continue
            stray.chmod(0o644)
            stray.unlink()
            logger.info(f"[Patch Backup] Removed the stray copy {stray}")
        except OSError as e:
            logger.error(f"[Patch Backup] Failed to sort out the stray copy {stray}: {e}")
    if ledger != loaded_ledger:
        _save_ledger(game.id, ledger)
    return adopted


def migrate_persistent_backups(persistent_root: Path, game):
    # Bulk move of any legacy co-located Persistent backups into the state dir (per-access migration is the safety net).
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
