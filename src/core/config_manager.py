import os
import sys
from pathlib import Path

from src.core.app_config import CONFIG_DIR_NAME
from src.core.game_registry import (
    DEFAULT_GAME_ID,
    normalize_game_id as normalize_game_id_from_registry,
)


class ConfigManager:
    def __init__(self):
        self.platform = sys.platform
        self._config_dir = None
        self._data_dir = None
        self._launcher_dir = None
        self._games_dir = None
        self._tools_dir = None
        self._custom_mod_library_dir = None

    @property
    def config_dir(self):
        if self._config_dir:
            return self._config_dir

        if self.platform == "win32":
            appdata = Path(
                os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")
            )
            self._config_dir = appdata / CONFIG_DIR_NAME
        else:
            xdg_config = os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")
            self._config_dir = Path(xdg_config) / CONFIG_DIR_NAME

        self._config_dir.mkdir(parents=True, exist_ok=True)
        return self._config_dir

    @property
    def data_dir(self):
        if self._data_dir:
            return self._data_dir

        if self.platform == "win32":
            localappdata = Path(
                os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")
            )
            self._data_dir = localappdata / CONFIG_DIR_NAME
        else:
            xdg_data = os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")
            self._data_dir = Path(xdg_data) / CONFIG_DIR_NAME

        self._data_dir.mkdir(parents=True, exist_ok=True)
        return self._data_dir

    @property
    def launcher_dir(self):
        if self._launcher_dir:
            return self._launcher_dir

        self._launcher_dir = self.data_dir / "launcher"
        self._launcher_dir.mkdir(parents=True, exist_ok=True)
        return self._launcher_dir

    @property
    def games_dir(self):
        if self._games_dir:
            return self._games_dir

        self._games_dir = self.data_dir / "games"
        self._games_dir.mkdir(parents=True, exist_ok=True)
        return self._games_dir

    def game_data_dir(self, game_id=DEFAULT_GAME_ID):
        game = normalize_game_id_from_registry(game_id, default=DEFAULT_GAME_ID)
        game_dir = self.games_dir / game
        game_dir.mkdir(parents=True, exist_ok=True)
        return game_dir

    @property
    def settings_file(self):
        return self.config_dir / "settings.json"

    @property
    def mod_config_file(self):
        return self.config_dir / "mod_config.json"

    @property
    def mod_tracker_file(self):
        return self.config_dir / "mod_tracker.json"

    @property
    def default_mod_library_dir(self):
        return self.game_data_dir(DEFAULT_GAME_ID) / "mod_library"

    @property
    def mod_library_dir(self):
        if self._custom_mod_library_dir:
            return self._custom_mod_library_dir
        return self.default_mod_library_dir

    def set_mod_library_dir(self, path):
        if path:
            self._custom_mod_library_dir = Path(path)
        else:
            self._custom_mod_library_dir = None

    @property
    def cache_dir(self):
        return self.launcher_dir / "cache"

    @property
    def tools_dir(self):
        if self._tools_dir:
            return self._tools_dir

        # Windows: Roaming AppData (alongside settings.json) so binaries persist
        # across reinstalls and aren't scattered next to the exe. Linux keeps
        # XDG_DATA_HOME for continuity with the existing Flatpak layout.
        if self.platform == "win32":
            self._tools_dir = self.config_dir / "tools"
        else:
            self._tools_dir = self.data_dir / "tools"

        self._tools_dir.mkdir(parents=True, exist_ok=True)
        return self._tools_dir

    @property
    def sound_database_file(self):
        return self.game_data_dir(DEFAULT_GAME_ID) / "sound_database.json"

    @property
    def fingerprint_database_file(self):
        return self.game_data_dir(DEFAULT_GAME_ID) / "fingerprint_database.json"

_config_manager = ConfigManager()


def get_config_manager():
    return _config_manager


def get_config_dir():
    return _config_manager.config_dir


def get_data_dir():
    return _config_manager.data_dir


def get_launcher_dir():
    return _config_manager.launcher_dir


def get_games_dir():
    return _config_manager.games_dir


def get_game_data_dir(game_id=DEFAULT_GAME_ID):
    return _config_manager.game_data_dir(game_id)


def get_settings_file():
    return _config_manager.settings_file


def get_mod_config_file():
    return _config_manager.mod_config_file


def get_mod_tracker_file():
    return _config_manager.mod_tracker_file


def get_mod_library_dir():
    return _config_manager.mod_library_dir


def get_default_mod_library_dir():
    return _config_manager.default_mod_library_dir


def set_mod_library_dir(path):
    _config_manager.set_mod_library_dir(path)


def get_cache_dir():
    return _config_manager.cache_dir


def get_tools_dir():
    return _config_manager.tools_dir


def get_sound_database_file():
    return _config_manager.sound_database_file


def get_fingerprint_database_file():
    return _config_manager.fingerprint_database_file


def normalize_game_id(game_id):
    return normalize_game_id_from_registry(game_id, default=DEFAULT_GAME_ID)


def get_game_mod_library_dir(game_id=DEFAULT_GAME_ID, custom_root=None):
    game = normalize_game_id(game_id)
    if custom_root:
        return Path(custom_root) / game
    return get_game_data_dir(game) / "mod_library"


def get_custom_mod_library_settings_key(game_id=DEFAULT_GAME_ID):
    game = normalize_game_id(game_id)
    return f"{game}_custom_mod_library_dir"


def get_game_mod_config_file(game_id=DEFAULT_GAME_ID):
    game = normalize_game_id(game_id)
    if game == DEFAULT_GAME_ID:
        return get_mod_config_file()
    return get_config_dir() / f"mod_config_{game}.json"


def get_game_mod_tracker_file(game_id=DEFAULT_GAME_ID):
    game = normalize_game_id(game_id)
    if game == DEFAULT_GAME_ID:
        return get_mod_tracker_file()
    return get_config_dir() / f"mod_tracker_{game}.json"


def resolve_mod_paths_for_game(game_id=DEFAULT_GAME_ID, custom_root=None):
    game = normalize_game_id(game_id)
    mod_library_dir = get_game_mod_library_dir(game, custom_root)
    return {
        "game_id": game,
        "mod_library_dir": mod_library_dir,
        "mods_dir": mod_library_dir / "mods",
        "mod_config_file": get_game_mod_config_file(game),
        "mod_tracker_file": get_game_mod_tracker_file(game),
    }


def get_game_sound_database_file(game_id=DEFAULT_GAME_ID):
    game = normalize_game_id(game_id)
    if game == DEFAULT_GAME_ID:
        return get_sound_database_file()
    return get_game_data_dir(game) / "sound_database.json"


def get_game_fingerprint_database_file(game_id=DEFAULT_GAME_ID):
    game = normalize_game_id(game_id)
    if game == DEFAULT_GAME_ID:
        return get_fingerprint_database_file()
    return get_game_data_dir(game) / "fingerprint_database.json"
