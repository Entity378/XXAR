from src.core.game_registry import (
    get_game,
    get_game_language_folders,
    get_game_subfolder_sort_priority,
    DEFAULT_GAME_ID,
)


APP_NAME = "XXAR"
APP_VERSION = "0.6.0-alpha"
CONFIG_DIR_NAME = "XXAR"

FLATPAK_ENV_VAR = "XXAR_FLATPAK"
FLATPAK_BUILD_ENV_VAR = "XXAR_FLATPAK_BUILD"

# ── Active game (mutable at runtime) ────────────────────────────
# Initialised from DEFAULT_GAME_ID; updated by switch_active_game().

_active_game = get_game(DEFAULT_GAME_ID)

GAME_NAME = _active_game.display_name
GAME_SHORT = _active_game.short_label
GAME_DATA_FOLDER = _active_game.data_dir_name
GAME_DATA_FOLDER_SEARCH = GAME_DATA_FOLDER
GAMEBANANA_GAME_ID = _active_game.gamebanana_game_id

GAME_INSTALL_SUBDIRS = [
    f"Program Files/HoYoPlay/games/{_active_game.install_dir_name}",
    f"Program Files (x86)/HoYoPlay/games/{_active_game.install_dir_name}",
]
GAME_INSTALL_HOME_SUBDIR = f"Games/{_active_game.install_dir_name}"

AUDIO_SUBPATH = _active_game.game_audio_subpath
SOUNDBANK_PCK_GLOB = _active_game.soundbank_pck_glob
STREAMED_PCK_GLOB = _active_game.streamed_pck_glob
STREAMED_PCK_PREFIX = _active_game.streamed_pck_prefix
SOUNDBANK_PCK_PREFIX = _active_game.soundbank_pck_prefix
SOUNDBANK_PCK_FILTER_PREFIX = _active_game.soundbank_pck_filter_prefix
LANGUAGE_FOLDERS = get_game_language_folders(_active_game.id)
AUDIO_ROOT_FRIENDLY_NAME = _active_game.audio_root_friendly_name
SUBFOLDER_SORT_PRIORITY = get_game_subfolder_sort_priority(_active_game.id)
LOOP_POINT_PATCHING_SUPPORTED = _active_game.loop_point_patching_supported
LOOP_POINT_MODES = _active_game.loop_point_modes

GAME_THEME_PALETTES = {
    "zzz": ("#d8fa00", "#e8ff33", "#a8c800"),
    "genshin": ("#34c27a", "#6fe3a5", "#238a58"),
    "hsr": ("#3f9ec3", "#62b8d8", "#2d7a99"),
}
ACCENT_COLOR, ACCENT_COLOR_LIGHT, ACCENT_COLOR_DARK = GAME_THEME_PALETTES.get(
    _active_game.id,
    GAME_THEME_PALETTES["zzz"],
)

# ── Game-specific branding (updates with active game) ───────────
APP_FULL_NAME = _active_game.app_full_name
MOD_FILE_EXT = _active_game.mod_file_ext
MOD_FILE_EXT_UPPER = _active_game.mod_file_ext_upper
ASSETS_DIR = _active_game.assets_dir
LOGO_PNG = _active_game.logo_png
LOGO_ICO = _active_game.logo_ico
LOGO_256 = _active_game.logo_256

DATA_SUBDIR = _active_game.build_target


def switch_active_game(game_id: str):
    import src.core.app_config as _self

    game = get_game(game_id)
    _self._active_game = game

    _self.GAME_NAME = game.display_name
    _self.GAME_SHORT = game.short_label
    _self.GAME_DATA_FOLDER = game.data_dir_name
    _self.GAME_DATA_FOLDER_SEARCH = game.data_dir_name
    _self.GAMEBANANA_GAME_ID = game.gamebanana_game_id
    _self.GAME_INSTALL_SUBDIRS = [
        f"Program Files/HoYoPlay/games/{game.install_dir_name}",
        f"Program Files (x86)/HoYoPlay/games/{game.install_dir_name}",
    ]
    _self.GAME_INSTALL_HOME_SUBDIR = f"Games/{game.install_dir_name}"
    _self.AUDIO_SUBPATH = game.game_audio_subpath
    _self.SOUNDBANK_PCK_GLOB = game.soundbank_pck_glob
    _self.STREAMED_PCK_GLOB = game.streamed_pck_glob
    _self.STREAMED_PCK_PREFIX = game.streamed_pck_prefix
    _self.SOUNDBANK_PCK_PREFIX = game.soundbank_pck_prefix
    _self.SOUNDBANK_PCK_FILTER_PREFIX = game.soundbank_pck_filter_prefix
    _self.LANGUAGE_FOLDERS = get_game_language_folders(game.id)
    _self.AUDIO_ROOT_FRIENDLY_NAME = game.audio_root_friendly_name
    _self.SUBFOLDER_SORT_PRIORITY = get_game_subfolder_sort_priority(game.id)
    _self.LOOP_POINT_PATCHING_SUPPORTED = game.loop_point_patching_supported
    _self.LOOP_POINT_MODES = game.loop_point_modes

    _self.ACCENT_COLOR, _self.ACCENT_COLOR_LIGHT, _self.ACCENT_COLOR_DARK = (
        _self.GAME_THEME_PALETTES.get(game.id, _self.GAME_THEME_PALETTES["zzz"])
    )

    _self.APP_FULL_NAME = game.app_full_name
    _self.MOD_FILE_EXT = game.mod_file_ext
    _self.MOD_FILE_EXT_UPPER = game.mod_file_ext_upper
    _self.ASSETS_DIR = game.assets_dir
    _self.LOGO_PNG = game.logo_png
    _self.LOGO_ICO = game.logo_ico
    _self.LOGO_256 = game.logo_256
    _self.DATA_SUBDIR = game.build_target
