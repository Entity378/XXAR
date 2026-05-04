# Standalone folder-swap helper for XXAR portable/ZIP installs.

# The main XXAR.exe, once onefolder-packaged, cannot overwrite its own Resources/Bin while running.
# It downloads a new build into a staging folder and spawns this helper.
# The helper waits for the main to exit, swaps Bin atomically (rename-then-move), and relaunches the app.

# MSI installs go through msiexec instead and do not use this helper.


import argparse
import logging
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

# Only a no-op outside Windows — Linux ships as Flatpak and has no folder swap.
if sys.platform != "win32":
    print("XXAR Updater is Windows-only", file=sys.stderr)
    sys.exit(0)


LOCK_RETRY_SECONDS = 1.0
# Empirically, Windows Defender's real-time scan of the freshly-extracted staging Bin dir can hold a directory handle for ~30-60 s.
# A worst-case budget of 3 min is safer than failing updates on slow machines.
LOCK_RETRY_MAX = 180
APP_EXE_NAME = "XXAR.exe"


def _setup_logging(dist_dir: Path) -> Path:
    localappdata = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    log_dir = localappdata / "XXAR" / "launcher" / "cache" / "updates"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "updater.log"
    logging.basicConfig(
        filename=str(log_file),
        filemode="a",
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    logging.info("=" * 60)
    logging.info("XXAR Updater starting (dist_dir=%s)", dist_dir)
    return log_file


def _rename_with_retry(src: Path, dst: Path) -> None:
    # Rename fails while the target or source is locked by the still-exiting XXAR process.
    # Retry until Windows releases the handles.
    for attempt in range(1, LOCK_RETRY_MAX + 1):
        try:
            src.rename(dst)
            logging.info("Renamed %s -> %s (attempt %d)", src.name, dst.name, attempt)
            return
        except (PermissionError, OSError) as e:
            if attempt == LOCK_RETRY_MAX:
                logging.error("Rename failed after %d attempts: %s", attempt, e)
                raise
            logging.info("Locked, retry %d/%d", attempt, LOCK_RETRY_MAX)
            time.sleep(LOCK_RETRY_SECONDS)


def _remove_tree_best_effort(path: Path) -> None:
    if not path.exists():
        return
    try:
        shutil.rmtree(str(path))
        logging.info("Removed %s", path)
    except Exception as e:
        logging.warning("Could not remove %s: %s (leaving it behind)", path, e)


def _swap_folder(dist_dir: Path, staging_dir: Path) -> Path:
    # Swap <dist>/Resources/Bin with the pre-extracted staging folder.
    # Return the path to the new app exe for relaunch.
    bin_dir = dist_dir / "Resources" / "Bin"
    bin_old = dist_dir / "Resources" / "Bin.old"

    if not staging_dir.exists():
        raise FileNotFoundError(f"Staging dir not found: {staging_dir}")

    # Clean any leftover Bin.old from a previous interrupted update.
    _remove_tree_best_effort(bin_old)

    if bin_dir.exists():
        _rename_with_retry(bin_dir, bin_old)

    bin_dir.parent.mkdir(parents=True, exist_ok=True)
    _rename_with_retry(staging_dir, bin_dir)

    # Best-effort cleanup; Bin.old may have files Windows still holds briefly.
    _remove_tree_best_effort(bin_old)

    new_exe = bin_dir / APP_EXE_NAME
    if not new_exe.exists():
        raise FileNotFoundError(f"New exe not found after swap: {new_exe}")
    return new_exe


def _relaunch(app_exe: Path) -> None:
    # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP so the new app does not die with us when the updater exits.
    DETACHED_PROCESS = 0x00000008
    CREATE_NEW_PROCESS_GROUP = 0x00000200
    subprocess.Popen(
        [str(app_exe)],
        cwd=str(app_exe.parent),
        creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
        close_fds=True,
    )
    logging.info("Relaunched %s", app_exe)


def main() -> int:
    parser = argparse.ArgumentParser(description="XXAR portable folder-swap updater")
    parser.add_argument("--dist-dir", required=True, type=Path,
                        help="Install root (contains Resources/Bin)")
    parser.add_argument("--staging-dir", required=True, type=Path,
                        help="Pre-extracted new build (will be moved into Resources/Bin)")
    parser.add_argument("--no-relaunch", action="store_true",
                        help="Do not relaunch XXAR after update")
    args = parser.parse_args()

    dist_dir = args.dist_dir.resolve()
    staging_dir = args.staging_dir.resolve()

    log_file = _setup_logging(dist_dir)
    logging.info("staging_dir=%s", staging_dir)

    try:
        new_exe = _swap_folder(dist_dir, staging_dir)
    except Exception as e:
        logging.exception("Update failed: %s", e)
        print(f"Update failed: {e}\nSee log: {log_file}", file=sys.stderr)
        return 1

    if not args.no_relaunch:
        try:
            _relaunch(new_exe)
        except Exception as e:
            logging.exception("Relaunch failed: %s", e)
            # Update itself succeeded, just no auto-restart
            return 2

    logging.info("Update complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
