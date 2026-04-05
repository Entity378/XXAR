from src.core.game_registry import (
    get_game_for_build_target,
    get_game_id_for_build_target,
    get_game_language_folders,
    get_game_subfolder_sort_priority,
)


BUILD_TARGET = "ZZAR"

if BUILD_TARGET not in {"ZZAR", "SRAR", "GIAR"}:
    raise ValueError(
        f"Unknown BUILD_TARGET: {BUILD_TARGET!r}. Must be 'ZZAR', 'SRAR' or 'GIAR'."
    )

APP_NAME = BUILD_TARGET
CONFIG_DIR_NAME = BUILD_TARGET

FLATPAK_ENV_VAR = f"{BUILD_TARGET}_FLATPAK"
FLATPAK_BUILD_ENV_VAR = f"{BUILD_TARGET}_FLATPAK_BUILD"

_TARGET_GAME_ID = get_game_id_for_build_target(BUILD_TARGET)
_GAME = get_game_for_build_target(BUILD_TARGET)

GAME_NAME = _GAME.display_name
GAME_SHORT = _GAME.short_label
GAME_DATA_FOLDER = _GAME.data_dir_name
GAME_DATA_FOLDER_SEARCH = GAME_DATA_FOLDER
GAMEBANANA_GAME_ID = _GAME.gamebanana_game_id

GAME_INSTALL_SUBDIRS = [
    f"Program Files/HoYoPlay/games/{_GAME.install_dir_name}",
    f"Program Files (x86)/HoYoPlay/games/{_GAME.install_dir_name}",
]
GAME_INSTALL_HOME_SUBDIR = f"Games/{_GAME.install_dir_name}"

AUDIO_SUBPATH = _GAME.game_audio_subpath
SOUNDBANK_PCK_GLOB = _GAME.soundbank_pck_glob
STREAMED_PCK_GLOB = _GAME.streamed_pck_glob
STREAMED_PCK_PREFIX = _GAME.streamed_pck_prefix
SOUNDBANK_PCK_PREFIX = _GAME.soundbank_pck_prefix
SOUNDBANK_PCK_FILTER_PREFIX = _GAME.soundbank_pck_filter_prefix
LANGUAGE_FOLDERS = get_game_language_folders(_TARGET_GAME_ID)
AUDIO_ROOT_FRIENDLY_NAME = _GAME.audio_root_friendly_name
SUBFOLDER_SORT_PRIORITY = get_game_subfolder_sort_priority(_TARGET_GAME_ID)
LOOP_POINT_PATCHING_SUPPORTED = _GAME.loop_point_patching_supported
LOOP_POINT_MODES = _GAME.loop_point_modes

GAME_THEME_PALETTES = {
    "zzz": ("#d8fa00", "#e8ff33", "#a8c800"),
    "genshin": ("#34c27a", "#6fe3a5", "#238a58"),
    "hsr": ("#3f9ec3", "#62b8d8", "#2d7a99"),
}
ACCENT_COLOR, ACCENT_COLOR_LIGHT, ACCENT_COLOR_DARK = GAME_THEME_PALETTES.get(
    _TARGET_GAME_ID,
    GAME_THEME_PALETTES["zzz"],
)

if BUILD_TARGET == "ZZAR":
    APP_FULL_NAME = "Zenless Zone Zero Audio Replacer"
    APP_VERSION = "1.2.2"
    MOD_FILE_EXT = ".zzar"
    MOD_FILE_EXT_UPPER = "ZZAR"
    ASSETS_DIR = "ZZAR"
    LOGO_PNG = "ZZAR-Logo2.png"
    LOGO_ICO = "ZZAR-Logo2.ico"
    LOGO_256 = "ZZAR-Logo2-256.png"
elif BUILD_TARGET == "SRAR":
    APP_FULL_NAME = "Honkai Star Rail Audio Replacer"
    APP_VERSION = "1.0.0"
    MOD_FILE_EXT = ".srar"
    MOD_FILE_EXT_UPPER = "SRAR"
    ASSETS_DIR = "SRAR"
    LOGO_PNG = "SRAR-Logo2.png"
    LOGO_ICO = "SRAR-Logo2.ico"
    LOGO_256 = "SRAR-Logo2-256.png"
else:
    APP_FULL_NAME = "Genshin Impact Audio Replacer"
    APP_VERSION = "1.0.0"
    MOD_FILE_EXT = ".giar"
    MOD_FILE_EXT_UPPER = "GIAR"
    # Reuse existing assets until GIAR-specific assets are added.
    ASSETS_DIR = "ZZAR"
    LOGO_PNG = "ZZAR-Logo2.png"
    LOGO_ICO = "ZZAR-Logo2.ico"
    LOGO_256 = "ZZAR-Logo2-256.png"

# Derived - always matches APP_NAME
DATA_SUBDIR = APP_NAME
