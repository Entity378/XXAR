from pathlib import Path

from src.core.config_manager import get_game_data_dir
from src.core.game_registry import get_game

from src.audio import vo_download
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
    def restore_persistent_originals(
        persistent_path, progress_callback=None, vo_backup_mode="local"
    ):
        game = get_game("hsr")
        vo_names = _vo_folder_names(game)
        persistent_path = Path(persistent_path)

        if not persistent_path.is_dir():
            return

        # Find installed language folders (those with existing PCK files).
        needed_languages = set()
        for folder in persistent_path.iterdir():
            if folder.is_dir() and folder.name in vo_names:
                if any(folder.glob("*.pck")):
                    needed_languages.add(folder.name)

        if not needed_languages:
            return

        app_game_dir = get_game_data_dir("hsr")

        if vo_backup_mode == "local":
            _restore_via_local_hashes(
                app_game_dir, persistent_path, needed_languages, progress_callback
            )
        else:
            _restore_via_api(
                app_game_dir, persistent_path, needed_languages,
                game, progress_callback,
            )


def _restore_via_local_hashes(app_game_dir, persistent_path, languages, progress_cb):
    from src.audio import vo_local_backup

    restored = 0
    for lang in sorted(languages):
        ok = vo_local_backup.restore_language_from_hashes(
            app_game_dir=app_game_dir,
            persistent_path=persistent_path,
            folder_name=lang,
            progress_cb=progress_cb,
        )
        if ok:
            restored += 1
        elif progress_cb:
            progress_cb(f"Warning: could not restore {lang} originals (local backup)")

    if restored:
        print(f"[HSR VO Restore] Restored {restored} language(s) via local backup")


def _restore_via_api(app_game_dir, persistent_path, languages, game, progress_cb):
    data_folder = persistent_path
    for _ in range(len(game.persistent_audio_subpath)):
        data_folder = data_folder.parent

    version = _read_game_version(data_folder)
    if not version:
        print("[HSR VO Restore] Could not read game version")
        return

    cached_version = vo_download.cleanup_stale_cache(app_game_dir, version)

    restored = 0
    for lang in sorted(languages):
        ok = vo_download.restore_language_from_api(
            app_game_dir=app_game_dir,
            persistent_path=persistent_path,
            folder_name=lang,
            version=version,
            cached_version=cached_version,
            progress_cb=progress_cb,
        )
        if ok:
            restored += 1
        elif progress_cb:
            progress_cb(f"Warning: could not restore {lang} originals")

    if restored:
        print(f"[HSR VO Restore] Restored {restored} language(s) via API")
