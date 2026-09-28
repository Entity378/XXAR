import importlib.util
import re

import pytest

import src.core.app_config as app_config
from src.core.game_registry import (
    DEFAULT_GAME_ID,
    get_game,
    get_game_language_folders,
    get_game_subfolder_sort_priority,
    get_supported_game_ids,
)

GAME_IDS = list(get_supported_game_ids())
GAME_INDEPENDENT_CONSTANTS = {
    "APP_NAME",
    "APP_VERSION",
    "CONFIG_DIR_NAME",
    "FLATPAK_ENV_VAR",
    "FLATPAK_BUILD_ENV_VAR",
    "DEBUG",
    "GAME_THEME_PALETTES",
    "DEFAULT_GAME_ID",
}


def expected_constants(game_id):
    game = get_game(game_id)
    accent, accent_light, accent_dark = app_config.GAME_THEME_PALETTES[game.id]
    return {
        "GAME_NAME": game.display_name,
        "GAME_SHORT": game.short_label,
        "GAME_DATA_FOLDER": game.data_dir_name,
        "GAME_DATA_FOLDER_SEARCH": game.data_dir_name,
        "GAMEBANANA_GAME_ID": game.gamebanana_game_id,
        "GAME_INSTALL_SUBDIRS": [
            f"Program Files/HoYoPlay/games/{game.install_dir_name}",
            f"Program Files (x86)/HoYoPlay/games/{game.install_dir_name}",
        ],
        "GAME_INSTALL_HOME_SUBDIR": f"Games/{game.install_dir_name}",
        "AUDIO_SUBPATH": game.game_audio_subpath,
        "SOUNDBANK_PCK_GLOB": game.soundbank_pck_glob,
        "STREAMED_PCK_GLOB": game.streamed_pck_glob,
        "STREAMED_PCK_PREFIX": game.streamed_pck_prefix,
        "SOUNDBANK_PCK_PREFIX": game.soundbank_pck_prefix,
        "SOUNDBANK_PCK_FILTER_PREFIX": game.soundbank_pck_filter_prefix,
        "LANGUAGE_FOLDERS": get_game_language_folders(game.id),
        "AUDIO_ROOT_FRIENDLY_NAME": game.audio_root_friendly_name,
        "SUBFOLDER_SORT_PRIORITY": get_game_subfolder_sort_priority(game.id),
        "LOOP_POINT_PATCHING_SUPPORTED": game.loop_point_patching_supported,
        "LOOP_POINT_MODES": game.loop_point_modes,
        "ACCENT_COLOR": accent,
        "ACCENT_COLOR_LIGHT": accent_light,
        "ACCENT_COLOR_DARK": accent_dark,
        "APP_FULL_NAME": game.app_full_name,
        "MOD_FILE_EXT": game.mod_file_ext,
        "MOD_FILE_EXT_UPPER": game.mod_file_ext_upper,
        "ASSETS_DIR": game.assets_dir,
        "LOGO_PNG": game.logo_png,
        "LOGO_256": game.logo_256,
        "DATA_SUBDIR": game.build_target,
    }


def current_constants(names):
    return {name: getattr(app_config, name) for name in names}


def load_fresh_app_config():
    spec = importlib.util.spec_from_file_location("fresh_app_config", app_config.__file__)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_import_time_constants_describe_the_default_game():
    fresh_module = load_fresh_app_config()
    expected = expected_constants(DEFAULT_GAME_ID)
    assert {name: getattr(fresh_module, name) for name in expected} == expected
    assert fresh_module._active_game.id == DEFAULT_GAME_ID


def test_every_module_constant_is_either_game_independent_or_rebound_on_switch():
    module_constants = {name for name in vars(app_config) if name.isupper()}
    assert module_constants - GAME_INDEPENDENT_CONSTANTS == set(expected_constants(DEFAULT_GAME_ID))


@pytest.mark.parametrize("game_id", GAME_IDS)
def test_switch_active_game_rebinds_every_game_constant(game_id):
    app_config.switch_active_game(game_id)
    expected = expected_constants(game_id)
    assert app_config._active_game is get_game(game_id)
    assert current_constants(expected) == expected


@pytest.mark.parametrize("game_id", [game_id for game_id in GAME_IDS if game_id != DEFAULT_GAME_ID])
def test_switching_away_and_back_restores_the_default_constants(game_id):
    default_constants = current_constants(expected_constants(DEFAULT_GAME_ID))
    app_config.switch_active_game(game_id)
    assert current_constants(default_constants) != default_constants
    app_config.switch_active_game(DEFAULT_GAME_ID)
    assert current_constants(default_constants) == default_constants


def test_switch_active_game_with_unknown_id_falls_back_to_default():
    app_config.switch_active_game("hsr")
    app_config.switch_active_game("not-a-game")
    assert app_config._active_game.id == DEFAULT_GAME_ID
    assert app_config.GAME_NAME == get_game(DEFAULT_GAME_ID).display_name


def test_from_import_copies_go_stale_after_a_game_switch():
    # This is the documented gotcha: only module attribute access follows switch_active_game.
    from src.core.app_config import GAME_NAME, MOD_FILE_EXT

    app_config.switch_active_game("genshin")
    assert app_config.GAME_NAME == "Genshin Impact"
    assert app_config.MOD_FILE_EXT == ".giar"
    assert GAME_NAME == "Zenless Zone Zero"
    assert MOD_FILE_EXT == ".zzar"


def test_theme_palettes_are_distinct_hex_triplets():
    assert set(app_config.GAME_THEME_PALETTES) == set(GAME_IDS)
    accents = [palette[0] for palette in app_config.GAME_THEME_PALETTES.values()]
    assert len(set(accents)) == len(accents)
    for palette in app_config.GAME_THEME_PALETTES.values():
        assert len(palette) == 3
        assert all(re.fullmatch(r"#[0-9a-f]{6}", color) for color in palette)


def test_app_version_is_a_release_tag_version():
    assert re.fullmatch(r"\d+\.\d+\.\d+(-[0-9A-Za-z.]+)?", app_config.APP_VERSION)
    assert app_config.APP_NAME == "XXAR"
    assert app_config.CONFIG_DIR_NAME == "XXAR"
