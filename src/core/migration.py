"""One-shot folder migrations between XXAR versions.

Runs at startup before any config_manager paths are accessed. Moves user
data from its pre-0.8 location to the new layout:

  games/      LOCALAPPDATA -> APPDATA      (user content: mods, databases)
  tools/      APPDATA      -> LOCALAPPDATA (large binaries, machine-local)
  temp/       APPDATA      -> LOCALAPPDATA (transient; just deleted, lazy recreate)

Each move is no-op if the source does not exist or the destination is
already populated — both protect against repeated runs and fresh installs.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


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


def _has_files(path: Path) -> bool:
    for p in path.rglob("*"):
        if p.is_file():
            return True
    return False


def _move_dir(src: Path, dst: Path) -> None:
    # Skip if nothing to move, or if dest already has real files (either a
    # prior migration succeeded or a fresh install beat us to it). Empty
    # subdirectory scaffolding left by ConfigManager auto-mkdir doesn't count.
    if not src.exists():
        return
    if dst.exists() and _has_files(dst):
        print(f"[XXAR migration] Skipping {src} -> {dst}: destination already has files")
        return
    try:
        # Remove empty scaffolding in the dest so shutil.move can claim the name.
        if dst.exists():
            shutil.rmtree(str(dst))
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        print(f"[XXAR migration] Moved {src} -> {dst}")
    except OSError as e:
        print(f"[XXAR migration] Failed to move {src} -> {dst}: {e}")


def _delete_dir(path: Path) -> None:
    if not path.exists():
        return
    try:
        shutil.rmtree(str(path), ignore_errors=True)
        print(f"[XXAR migration] Removed stale {path}")
    except OSError as e:
        print(f"[XXAR migration] Could not remove {path}: {e}")


def run_migrations() -> None:
    appdata = _appdata_xxar()
    localappdata = _localappdata_xxar()
    if appdata is None or localappdata is None:
        return

    # games/ : Local -> Roaming
    _move_dir(localappdata / "games", appdata / "games")

    # tools/ : Roaming -> Local
    _move_dir(appdata / "tools", localappdata / "tools")

    # temp/ : just delete the stale Roaming copy (lazy-recreated on demand).
    _delete_dir(appdata / "temp")

    # Pre-0.8 Qt nested its own paths under %LOCALAPPDATA%\XXAR\XXAR\ because
    # organizationName+applicationName were both "XXAR". Dropping the org name
    # makes Qt write to %LOCALAPPDATA%\XXAR\ directly; the old nested dir only
    # holds regenerable QML bytecode cache.
    _delete_dir(localappdata / "XXAR")
