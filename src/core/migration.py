# One-shot folder migrations between XXAR versions.


from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path

RETRY_COUNT = 3
RETRY_SLEEP_SECONDS = 0.5
LOCK_STALE_SECONDS = 30 * 60


def _appdata_xxar() -> Path | None:
    if sys.platform != "win32":
        return None
    base = os.environ.get("APPDATA")
    if not base:
        return None
    return Path(base) / "XXAR"


def _localappdata_xxar() -> Path | None:
    if sys.platform != "win32":
        return None
    base = os.environ.get("LOCALAPPDATA")
    if not base:
        return None
    return Path(base) / "XXAR"


_log_path: Path | None = None


def _resolve_log_path() -> Path | None:
    base = _localappdata_xxar()
    if base is None:
        return None
    log_dir = base / "logs"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None
    return log_dir / "migration.log"


def _log(msg: str) -> None:
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] [XXAR migration] {msg}\n"
    try:
        sys.stderr.write(line)
    except Exception:
        pass
    if _log_path is None:
        return
    try:
        with open(_log_path, "a", encoding="utf-8") as f:
            f.write(line)
    except OSError:
        pass


def _has_files(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        for p in path.rglob("*"):
            if p.is_file():
                return True
    except OSError:
        pass
    return False


def _try_acquire_lock(base: Path) -> tuple[Path, int] | None:
    try:
        base.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None
    lock_path = base / ".migration.lock"
    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        try:
            os.write(fd, str(os.getpid()).encode("utf-8"))
        except OSError:
            pass
        return (lock_path, fd)
    except FileExistsError:
        try:
            age = time.time() - lock_path.stat().st_mtime
        except OSError:
            return None
        if age > LOCK_STALE_SECONDS:
            _log(f"Reclaiming stale lock {lock_path} (age {age:.0f}s)")
            try:
                lock_path.unlink()
            except OSError:
                return None
            return _try_acquire_lock(base)
        _log("Another migration appears to be in progress, skipping this run")
        return None
    except OSError as e:
        _log(f"Could not acquire migration lock: {e}")
        return None


def _release_lock(lock: tuple[Path, int]) -> None:
    path, fd = lock
    try:
        os.close(fd)
    except OSError:
        pass
    try:
        path.unlink()
    except OSError:
        pass


def _copy_one(src_file: Path, dst_file: Path) -> bool:
    last_err: Exception | None = None
    for attempt in range(RETRY_COUNT):
        try:
            dst_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(src_file), str(dst_file))
            return True
        except OSError as e:
            last_err = e
            if attempt < RETRY_COUNT - 1:
                time.sleep(RETRY_SLEEP_SECONDS * (attempt + 1))
    _log(f"  failed to copy {src_file.name}: {last_err}")
    return False


def _per_file_copy(src: Path, dst: Path) -> int:
    """Copy every file under src to dst, skipping files already at dst with
    the same size. Returns count of failed files (0 on full success)."""
    try:
        src_files = [p for p in src.rglob("*") if p.is_file()]
    except OSError as e:
        _log(f"  enumeration of {src} failed: {e}")
        return -1

    copied = 0
    skipped = 0
    failed = 0

    for src_file in src_files:
        try:
            rel = src_file.relative_to(src)
        except ValueError:
            failed += 1
            continue
        dst_file = dst / rel

        if dst_file.exists():
            try:
                if dst_file.stat().st_size == src_file.stat().st_size:
                    skipped += 1
                    continue
            except OSError:
                pass

        if _copy_one(src_file, dst_file):
            copied += 1
        else:
            failed += 1

    _log(f"  per-file: copied={copied} skipped={skipped} failed={failed}")
    return failed


def _migrate_dir(src: Path, dst: Path) -> None:
    if not src.exists():
        return

    _log(f"Migrating {src} -> {dst}")

    if dst.exists() and _has_files(dst):
        _log(f"  destination has files, resuming with per-file copy")
        if _per_file_copy(src, dst) == 0:
            try:
                shutil.rmtree(str(src))
                _log(f"  removed source {src} after successful resume")
            except OSError as e:
                _log(f"  copy ok but rmtree {src} failed: {e}")
        return

    try:
        if dst.exists():
            shutil.rmtree(str(dst))
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        _log(f"  atomic move ok")
        return
    except OSError as e:
        _log(f"  atomic move failed: {e} (falling back to per-file copy)")

    failed = _per_file_copy(src, dst)
    if failed == 0:
        try:
            shutil.rmtree(str(src))
            _log(f"  removed source {src} after fallback copy")
        except OSError as e:
            _log(f"  copy ok but rmtree {src} failed: {e}")
    else:
        _log(f"  leaving {src} for retry next run ({failed} files failed)")


def _delete_dir(path: Path) -> None:
    if not path.exists():
        return
    try:
        shutil.rmtree(str(path), ignore_errors=True)
        _log(f"Removed stale {path}")
    except OSError as e:
        _log(f"Could not remove {path}: {e}")


def _read_selected_game(roaming: Path) -> str:
    settings_path = roaming / "settings.json"
    try:
        with open(settings_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        sel = data.get("selected_game")
        if isinstance(sel, str) and sel:
            return sel
    except (OSError, ValueError) as e:
        _log(f"  could not read settings.json ({e}); defaulting selected_game=zzz")
    return "zzz"


def _migrate_legacy_mod_config(legacy: Path, target: Path, game: str) -> None:
    if not legacy.exists():
        return
    if target.exists():
        _log(f"  mod_config.json: target {target} already exists, leaving legacy in place")
        return
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(legacy), str(target))
        _log(f"  moved legacy mod_config.json -> games/{game}/")
    except OSError as e:
        _log(f"  failed to move mod_config.json: {e}")


def _migrate_legacy_mod_tracker(legacy: Path, target: Path, game: str, roaming: Path) -> None:
    """Move top-level mod_tracker.json to games/<game>/, rewriting absolute
    wem_path values from Local/XXAR/games/... to Roaming/XXAR/games/... to
    follow the games/ directory move."""
    if not legacy.exists():
        return
    if target.exists():
        _log(f"  mod_tracker.json: target {target} already exists, leaving legacy in place")
        return

    try:
        with open(legacy, "r", encoding="utf-8") as f:
            tracker = json.load(f)
    except (OSError, ValueError) as e:
        _log(f"  failed to read legacy mod_tracker.json: {e}")
        return

    local_xxar = _localappdata_xxar()
    rewritten = 0
    if local_xxar is not None and isinstance(tracker, dict):
        local_games_prefix = str(local_xxar / "games")
        roaming_games_prefix = str(roaming / "games")
        for files in tracker.values():
            if not isinstance(files, dict):
                continue
            for info in files.values():
                if not isinstance(info, dict):
                    continue
                wem_path = info.get("wem_path")
                if not isinstance(wem_path, str):
                    continue
                # Compare case-insensitively because Windows path casing varies
                if wem_path.lower().startswith(local_games_prefix.lower()):
                    info["wem_path"] = roaming_games_prefix + wem_path[len(local_games_prefix):]
                    rewritten += 1

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "w", encoding="utf-8") as f:
            json.dump(tracker, f, indent=2)
    except OSError as e:
        _log(f"  failed to write target mod_tracker.json: {e}")
        return

    try:
        legacy.unlink()
    except OSError as e:
        _log(f"  wrote target mod_tracker.json but could not remove legacy {legacy}: {e}")
        return

    _log(f"  moved legacy mod_tracker.json -> games/{game}/ (rewrote {rewritten} wem_path values)")


def _migrate_legacy_mod_state(roaming: Path) -> None:
    legacy_config = roaming / "mod_config.json"
    legacy_tracker = roaming / "mod_tracker.json"
    if not legacy_config.exists() and not legacy_tracker.exists():
        return

    selected_game = _read_selected_game(roaming)
    target_dir = roaming / "games" / selected_game
    _log(f"Relocating legacy mod state to games/{selected_game}/")

    _migrate_legacy_mod_config(legacy_config, target_dir / "mod_config.json", selected_game)
    _migrate_legacy_mod_tracker(legacy_tracker, target_dir / "mod_tracker.json", selected_game, roaming)


def run_migrations() -> None:
    global _log_path

    appdata = _appdata_xxar()
    localappdata = _localappdata_xxar()
    if appdata is None or localappdata is None:
        return

    _log_path = _resolve_log_path()

    needs_migration = (
        (localappdata / "games").exists()
        or (appdata / "tools").exists()
        or (appdata / "temp").exists()
        or (localappdata / "XXAR").exists()
        or (appdata / "mod_config.json").exists()
        or (appdata / "mod_tracker.json").exists()
    )
    if not needs_migration:
        return

    lock = _try_acquire_lock(localappdata)
    if lock is None:
        return

    try:
        # games/ : Local -> Roaming
        _migrate_dir(localappdata / "games", appdata / "games")

        # Top-level mod_config.json + mod_tracker.json (pre-0.8 single-game
        # layout) -> games/<active_game>/. Run AFTER games/ move so the
        # rewritten wem_path values point at where games/ now lives.
        _migrate_legacy_mod_state(appdata)

        # tools/ : Roaming -> Local
        _migrate_dir(appdata / "tools", localappdata / "tools")

        # temp/ : just delete the stale Roaming copy (lazy-recreated on demand).
        _delete_dir(appdata / "temp")

        # Pre-0.8 Qt nested its own paths under %LOCALAPPDATA%\XXAR\XXAR\ because
        # organizationName+applicationName were both "XXAR". Dropping the org name
        # makes Qt write to %LOCALAPPDATA%\XXAR\ directly; the old nested dir only
        # holds regenerable QML bytecode cache.
        _delete_dir(localappdata / "XXAR")
    finally:
        _release_lock(lock)
