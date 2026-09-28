import pytest

import src.core.app_config as app_config
from src.core.game_registry import get_supported_game_ids
from src.gui.backend.ui_theme_bridge import UIThemeBridge
from helpers import record_signal

GAME_IDS = list(get_supported_game_ids())


def theme_values(bridge):
    return tuple(bridge.property(name) for name in ("gameId", "accentColor", "accentColorLight", "accentColorDark"))


@pytest.mark.parametrize("game_id", GAME_IDS)
def test_bridge_exposes_the_game_palette_to_qml(qapp, game_id):
    bridge = UIThemeBridge(game_id)
    assert theme_values(bridge) == (game_id, *app_config.GAME_THEME_PALETTES[game_id])


@pytest.mark.parametrize("unknown_game_id", ["", "wuwa", None])
def test_unknown_game_uses_the_default_palette(qapp, unknown_game_id):
    assert theme_values(UIThemeBridge(unknown_game_id)) == ("zzz", *app_config.GAME_THEME_PALETTES["zzz"])


def test_theme_change_emits_once_per_real_change(qapp):
    bridge = UIThemeBridge("zzz")
    theme_changes = record_signal(bridge.themeChanged)
    assert bridge.set_theme_for_game("genshin") is True
    assert bridge.set_theme_for_game("GENSHIN") is False
    bridge.setThemeForGame("hsr")
    assert len(theme_changes) == 2
    assert bridge.accentColor == app_config.GAME_THEME_PALETTES["hsr"][0]


@pytest.mark.parametrize("game_id", GAME_IDS)
def test_theme_follows_the_active_game(qapp, game_id):
    bridge = UIThemeBridge(app_config._active_game.id)
    app_config.switch_active_game(game_id)
    bridge.setThemeForGame(app_config._active_game.id)
    assert (bridge.accentColor, bridge.accentColorLight, bridge.accentColorDark) == (
        app_config.ACCENT_COLOR,
        app_config.ACCENT_COLOR_LIGHT,
        app_config.ACCENT_COLOR_DARK,
    )


def test_bridge_is_independent_of_the_import_time_accent(qapp):
    app_config.switch_active_game("hsr")
    assert UIThemeBridge("genshin").accentColor == app_config.GAME_THEME_PALETTES["genshin"][0]
    assert UIThemeBridge().accentColor == app_config.GAME_THEME_PALETTES["zzz"][0]
