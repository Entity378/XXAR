from pathlib import Path

from src.config_manager import get_game_data_dir
from src.game_registry import get_game

from . import vo_download
from .base_handler import BaseBrowserHandler


def _vo_folder_names(game):
    non_lang = set(game.non_language_tabs or ())
    return {name for name, _ in game.language_folders if name not in non_lang}


def _read_game_version(data_folder: Path) -> str | None:
    import configparser

    config_ini = data_folder.parent / "config.ini"
    if not config_ini.is_file():
        return None
    try:
        cp = configparser.ConfigParser()
        cp.read(str(config_ini), encoding="utf-8")
        return cp.get("general", "game_version", fallback=None)
    except Exception:
        return None


class SRARBrowserHandler(BaseBrowserHandler):
    game_id = "hsr"

    @staticmethod
    def should_skip_persistent_cleanup_folder(_lang_folder, _pck_count):
        return True

    @staticmethod
    def restore_persistent_originals(persistent_path, progress_callback=None):
        # Restore original VO PCK files
        game = get_game("hsr")
        vo_names = _vo_folder_names(game)
        persistent_path = Path(persistent_path)

        if not persistent_path.is_dir():
            return

        # Find installed language folders (those with existing PCK files)
        needed_languages = set()
        for folder in persistent_path.iterdir():
            if folder.is_dir() and folder.name in vo_names:
                if any(folder.glob("*.pck")):
                    needed_languages.add(folder.name)

        if not needed_languages:
            return

        # Read current game version from config.ini
        # Walk up from persistent_path to find the data folder
        data_folder = persistent_path
        for _ in range(len(game.persistent_audio_subpath)):
            data_folder = data_folder.parent

        version = _read_game_version(data_folder)
        if not version:
            print("[HSR VO Restore] Could not read game version")
            return

        app_game_dir = get_game_data_dir("hsr")

        # Clean up cache from older versions before restoring.
        vo_download.cleanup_stale_cache(app_game_dir, version)

        restored = 0
        for lang in sorted(needed_languages):
            ok = vo_download.restore_language_from_api(
                app_game_dir=app_game_dir,
                persistent_path=persistent_path,
                folder_name=lang,
                version=version,
                progress_cb=progress_callback,
            )
            if ok:
                restored += 1
            else:
                if progress_callback:
                    progress_callback(
                        f"Warning: could not restore {lang} originals"
                    )

        if restored:
            print(f"[HSR VO Restore] Restored {restored} language(s)")
