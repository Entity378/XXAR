from pathlib import Path
from types import SimpleNamespace

import pytest

from src.gui.backend.audio_games import (
    GIARBrowserHandler,
    SRARBrowserHandler,
    ZZARBrowserHandler,
    build_browser_handlers,
    get_browser_handler_class,
)
from src.gui.backend.audio_games.base_handler import TITLESCREEN_FOLDER_KEY, BaseBrowserHandler


@pytest.mark.parametrize(
    ("game_id", "handler_class"),
    [
        ("zzz", ZZARBrowserHandler),
        ("genshin", GIARBrowserHandler),
        ("hsr", SRARBrowserHandler),
        ("gi", GIARBrowserHandler),
        ("SRAR", SRARBrowserHandler),
        ("zzar", ZZARBrowserHandler),
        ("wuthering", ZZARBrowserHandler),
        ("", ZZARBrowserHandler),
        (None, ZZARBrowserHandler),
    ],
)
def test_handler_class_resolves_aliases_and_falls_back_to_the_default_game(game_id, handler_class):
    assert get_browser_handler_class(game_id) is handler_class


def test_build_browser_handlers_makes_one_handler_per_game_bound_to_the_bridge():
    bridge = object()

    handlers = build_browser_handlers(bridge)

    assert {game_id: type(handler) for game_id, handler in handlers.items()} == {
        "zzz": ZZARBrowserHandler,
        "genshin": GIARBrowserHandler,
        "hsr": SRARBrowserHandler,
    }
    assert all(handler.bridge is bridge and handler.game.id == game_id for game_id, handler in handlers.items())


@pytest.mark.parametrize(
    ("game_id", "pck_name", "folder", "hide_useless", "expected"),
    [
        ("zzz", "Patch.pck", "Full", False, False),
        ("zzz", "Hotfix.pck", "En", False, False),
        ("zzz", "Streamed_En.pck", "En", True, False),
        ("zzz", "Streamed_En.pck", "En", False, True),
        ("zzz", "SoundBank_En.pck", "En", True, True),
        ("zzz", "Streamed_SFX_1.pck", "Full", True, True),
        ("zzz", "Minimum.pck", TITLESCREEN_FOLDER_KEY, True, True),
        ("genshin", "Streamed0.pck", "English(US)", True, True),
        ("genshin", "Hotfix.pck", "Full", False, False),
        ("hsr", "Streamed0.pck", "English", True, False),
        ("hsr", "Banks0.pck", "English", True, True),
        ("hsr", "Streamed0.pck", "SFX", True, True),
    ],
)
def test_include_pck_file_per_game(game_id, pck_name, folder, hide_useless, expected):
    handler = get_browser_handler_class(game_id)(bridge=None)

    assert handler.include_pck_file(Path(pck_name), folder, True, hide_useless) is expected


@pytest.mark.parametrize(
    ("game_id", "pck_name", "file_type", "expected"),
    [
        ("zzz", "Streamed_SFX_1.pck", "wem", True),
        ("zzz", "SoundBank_SFX_1.pck", "bnk", True),
        ("zzz", "Streamed_SFX_1.pck", "hirc", False),
        ("hsr", "Streamed0.pck", "wem", True),
        ("genshin", "Streamed0.pck", "wem", False),
        ("genshin", "Music0.pck", "wem", True),
        ("genshin", "minimum.pck", "bnk", True),
    ],
)
def test_loop_points_apply_per_game(game_id, pck_name, file_type, expected):
    handler_class = get_browser_handler_class(game_id)

    assert handler_class.is_loop_entry_applicable(pck_name, {"file_type": file_type}) is expected


@pytest.mark.parametrize(("mode", "expected"), [("MANUAL", "manual"), (" disabled ", "disabled"), ("bogus", "auto"), (None, "auto")])
def test_normalize_loop_mode(mode, expected):
    assert BaseBrowserHandler.normalize_loop_mode(mode) == expected


@pytest.mark.parametrize(("volume", "expected"), [(30, 24.0), (-200, -96.0), ("1.26", 1.3), ("abc", 0.0)])
def test_normalize_volume_db_clamps_and_rounds(volume, expected):
    assert BaseBrowserHandler.normalize_volume_db(volume) == expected


@pytest.mark.parametrize(("manual_ms", "expected"), [(-5, 0), ("1200", 1200), ("x", 0)])
def test_normalize_loop_manual_ms(manual_ms, expected):
    assert BaseBrowserHandler.normalize_loop_manual_ms(manual_ms) == expected


@pytest.mark.parametrize(("tracker_key", "expected"), [("100|21", 21), ("21", 21), ("abc", None), ("", None)])
def test_tracker_file_id_is_the_wem_id_after_the_bank(tracker_key, expected):
    assert BaseBrowserHandler._extract_tracker_file_id(tracker_key) == expected


@pytest.mark.parametrize(
    ("game_id", "folders", "expected_order"),
    [
        ("genshin", ["English(US)", "MusicGame", TITLESCREEN_FOLDER_KEY, "Full", "BeyondUGC"], ["Full", "BeyondUGC", "MusicGame", "English(US)", TITLESCREEN_FOLDER_KEY]),
        ("hsr", ["Japanese", "English", "SFX", "Full"], ["Full", "SFX", "English", "Japanese"]),
        ("zzz", ["Jp", "En", "Full"], ["Full", "En", "Jp"]),
    ],
)
def test_language_tabs_are_ordered_per_game(game_id, folders, expected_order):
    bridge = SimpleNamespace(language_folders={folder: {} for folder in folders})
    handler = get_browser_handler_class(game_id)(bridge)

    assert handler._ordered_folder_keys() == expected_order


@pytest.mark.parametrize(("game_id", "pck_name", "editable"), [("zzz", "Streamed_SFX_1.pck", True), ("genshin", "Streamed0.pck", False), ("genshin", "Music0.pck", True)])
def test_enrich_change_entry_exposes_loop_and_volume_editing(game_id, pck_name, editable):
    handler = get_browser_handler_class(game_id)(bridge=None)
    entry = {"loopPointEditable": False}

    handler.enrich_change_entry(pck_name, "21", {"file_type": "wem", "wem_path": "", "volume_db": 99}, entry)

    assert entry["loopPointEditable"] is editable
    if editable:
        assert (entry["loopPointMode"], entry["volumeEditable"], entry["volumeDb"]) == ("auto", True, 24.0)


def test_mod_manager_post_step_without_loop_or_volume_settings_touches_nothing(tmp_path):
    replacements = {"Streamed_SFX_1.pck": {"21": {"file_type": "wem", "wem_path": str(tmp_path / "x.wem")}}}

    result = ZZARBrowserHandler.apply_post_mod_manager_steps(replacements, tmp_path / "missing", tmp_path / "missing")

    assert result == {"patched_files": 0, "patched_ids": 0}
    assert list(tmp_path.iterdir()) == []
