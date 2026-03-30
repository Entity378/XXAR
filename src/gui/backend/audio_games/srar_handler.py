import configparser
import shutil
from pathlib import Path

from src.config_manager import get_game_data_dir
from src.game_registry import get_game

from .base_handler import BaseBrowserHandler

# Subfolder inside the app data dir that stores the original VO backup.
_BACKUP_DIR_NAME = "original_vo"

# File that records the game version at the time the backup was taken.
_VERSION_FILE_NAME = "vo_version.txt"


def _vo_folder_names(game):
    # Derive VO folder names from the game definition.
    non_lang = set(game.non_language_tabs or ())
    return {name for name, _ in game.language_folders if name not in non_lang}


def _read_game_version(data_folder: Path) -> str | None:
    # Read ``game_version`` from the game's *config.ini*.

    config_ini = data_folder.parent / "config.ini"
    if not config_ini.is_file():
        return None
    try:
        cp = configparser.ConfigParser()
        cp.read(str(config_ini), encoding="utf-8")
        return cp.get("general", "game_version", fallback=None)
    except Exception:
        return None


def _backup_needed(app_game_dir: Path, current_version: str) -> bool:
    """Return *True* when the VO backup is missing or outdated."""
    version_file = app_game_dir / _VERSION_FILE_NAME
    if not version_file.is_file():
        return True
    try:
        saved = version_file.read_text(encoding="utf-8").strip()
    except Exception:
        return True
    return saved != current_version


def _copy_vo_folders(persistent_root: Path, backup_dir: Path, vo_names: set) -> int:
    # Copy every VO language folder from *persistent_root* into *backup_dir*.
    copied = 0
    for folder in sorted(persistent_root.iterdir()):
        if not folder.is_dir():
            continue
        if folder.name not in vo_names:
            continue
        if not any(folder.glob("*.pck")):
            continue
        dest = backup_dir / folder.name
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(folder, dest)
        copied += 1
        print(f"[HSR VO Backup] Copied {folder.name} → {dest}")
    return copied


class SRARBrowserHandler(BaseBrowserHandler):
    game_id = "hsr"

    def scan_language_folders(self, data_folder):
        """Override to run the VO backup check before the normal scan."""
        self._ensure_vo_backup(data_folder)
        super().scan_language_folders(data_folder)

    # VO backup
    def _ensure_vo_backup(self, data_folder: Path):
        """Back up original VO PCK files from Persistent when the game
        updates (new ``game_version`` in *config.ini*).
        """
        current_version = _read_game_version(data_folder)
        if not current_version:
            print("[HSR VO Backup] Could not read game_version from config.ini")
            return

        app_game_dir = get_game_data_dir(self.game_id)
        if not _backup_needed(app_game_dir, current_version):
            print(
                f"[HSR VO Backup] Backup up-to-date (version {current_version})"
            )
            return

        persistent_root = data_folder.joinpath(*self.game.persistent_audio_subpath)
        if not persistent_root.is_dir():
            print(f"[HSR VO Backup] Persistent folder not found: {persistent_root}")
            return

        backup_dir = app_game_dir / _BACKUP_DIR_NAME
        backup_dir.mkdir(parents=True, exist_ok=True)

        vo_names = _vo_folder_names(self.game)
        self._emit_status("Backing up HSR voice-over files...")
        copied = _copy_vo_folders(persistent_root, backup_dir, vo_names)

        if copied > 0:
            version_file = app_game_dir / _VERSION_FILE_NAME
            version_file.write_text(current_version, encoding="utf-8")
            print(
                f"[HSR VO Backup] Backed up {copied} VO folder(s) "
                f"(version {current_version})"
            )
        else:
            print("[HSR VO Backup] No VO folders found to back up")


    # Persistent cleanup policy
    @staticmethod
    def should_skip_persistent_cleanup_folder(lang_folder, pck_count):
        folder_name = Path(lang_folder).name
        game = get_game("hsr")
        vo_names = _vo_folder_names(game)

        # Non-VO folders are never touched.
        if folder_name not in vo_names:
            return True

        # If we have a backup of this folder → safe to overwrite Persistent.
        backup = get_game_data_dir("hsr") / _BACKUP_DIR_NAME / folder_name
        if backup.is_dir() and any(backup.glob("*.pck")):
            return False

        # No backup yet -> protect the originals.
        return True
