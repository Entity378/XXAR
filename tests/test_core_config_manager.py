from pathlib import Path

import pytest

from src.core import config_manager
from src.core.config_manager import (
    ConfigManager,
    get_cache_dir,
    get_config_dir,
    get_constellation_index_file,
    get_custom_mod_library_root,
    get_custom_mod_library_settings_key,
    get_data_dir,
    get_default_mod_library_dir,
    get_fingerprint_database_file,
    get_game_constellation_index_file,
    get_game_data_dir,
    get_game_fingerprint_database_file,
    get_game_hirc_draft_file,
    get_game_hirc_draft_wem_dir,
    get_game_mod_config_file,
    get_game_mod_library_dir,
    get_game_mod_tracker_file,
    get_game_sound_database_file,
    get_game_state_dir,
    get_games_dir,
    get_mod_library_dir,
    get_settings_file,
    get_sound_database_file,
    get_state_dir,
    get_tools_dir,
    get_updates_dir,
    resolve_mod_library_dir,
    resolve_mod_paths_for_game,
    set_mod_library_dir,
)
from src.core.game_registry import get_supported_game_ids
from helpers import write_settings

GAME_IDS = list(get_supported_game_ids())


def test_config_and_data_dirs_follow_the_isolated_appdata(isolated_user_dirs):
    assert get_config_dir() == isolated_user_dirs.config_dir
    assert get_data_dir() == isolated_user_dirs.data_dir
    assert get_config_dir().is_dir()
    assert get_data_dir().is_dir()


def test_settings_and_games_live_in_roaming(isolated_user_dirs):
    assert get_settings_file() == isolated_user_dirs.config_dir / "settings.json"
    assert get_games_dir() == isolated_user_dirs.config_dir / "games"
    assert get_games_dir().is_dir()


@pytest.mark.parametrize(
    "path_helper, dir_name",
    [(get_tools_dir, "tools"), (get_state_dir, "state"), (get_cache_dir, "cache"), (get_updates_dir, "updates")],
)
def test_machine_local_dirs_live_in_local(isolated_user_dirs, path_helper, dir_name):
    assert path_helper() == isolated_user_dirs.data_dir / dir_name
    assert path_helper().is_dir()
    assert isolated_user_dirs.config_dir not in path_helper().parents


@pytest.mark.parametrize("game_id", GAME_IDS)
def test_per_game_dirs(isolated_user_dirs, game_id):
    assert get_game_data_dir(game_id) == isolated_user_dirs.config_dir / "games" / game_id
    assert get_game_state_dir(game_id) == isolated_user_dirs.data_dir / "state" / game_id
    assert get_game_data_dir(game_id).is_dir()
    assert get_game_state_dir(game_id).is_dir()


def test_per_game_dirs_for_unknown_game_use_the_default_game(isolated_user_dirs):
    assert get_game_data_dir("nope") == isolated_user_dirs.config_dir / "games" / "zzz"
    assert get_game_state_dir("") == isolated_user_dirs.data_dir / "state" / "zzz"
    assert not (isolated_user_dirs.config_dir / "games" / "nope").exists()


def test_config_manager_caches_resolved_dirs(isolated_user_dirs, monkeypatch, tmp_path):
    manager = ConfigManager()
    first_config_dir = manager.config_dir
    monkeypatch.setenv("APPDATA", str(tmp_path / "Elsewhere"))
    assert manager.config_dir == first_config_dir
    assert ConfigManager().config_dir == tmp_path / "Elsewhere" / "XXAR"


def test_linux_config_and_data_dirs_follow_xdg(monkeypatch, tmp_path):
    monkeypatch.setattr(config_manager, "IS_WINDOWS", False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg_config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg_data"))
    manager = ConfigManager()
    assert manager.config_dir == tmp_path / "xdg_config" / "XXAR"
    assert manager.data_dir == tmp_path / "xdg_data" / "XXAR"
    assert manager.tools_dir == tmp_path / "xdg_data" / "XXAR" / "tools"
    assert manager.settings_file == tmp_path / "xdg_config" / "XXAR" / "settings.json"


def test_linux_mod_library_lives_in_xdg_config_home(monkeypatch, tmp_path):
    monkeypatch.setattr(config_manager, "IS_WINDOWS", False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg_config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg_data"))
    monkeypatch.setattr(config_manager, "_config_manager", ConfigManager())
    assert get_game_mod_library_dir("genshin") == tmp_path / "xdg_config" / "XXAR" / "games" / "genshin" / "mod_library"


@pytest.mark.parametrize("game_id", GAME_IDS)
def test_default_mod_library_files(isolated_user_dirs, game_id):
    library_dir = isolated_user_dirs.config_dir / "games" / game_id / "mod_library"
    assert get_game_mod_library_dir(game_id) == library_dir
    assert get_game_mod_config_file(game_id) == library_dir / "mod_config.json"
    assert get_game_mod_tracker_file(game_id) == library_dir / "mod_tracker.json"
    assert resolve_mod_library_dir(game_id) == library_dir


def test_custom_root_nests_the_library_by_game(tmp_path):
    custom_root = tmp_path / "MyMods"
    assert get_game_mod_library_dir("hsr", custom_root) == custom_root / "hsr"
    assert get_game_mod_config_file("hsr", custom_root) == custom_root / "hsr" / "mod_config.json"
    assert get_game_mod_tracker_file("hsr", str(custom_root)) == custom_root / "hsr" / "mod_tracker.json"


def test_resolve_mod_paths_for_game(isolated_user_dirs, tmp_path):
    default_paths = resolve_mod_paths_for_game("genshin")
    library_dir = isolated_user_dirs.config_dir / "games" / "genshin" / "mod_library"
    assert default_paths == {
        "game_id": "genshin",
        "mod_library_dir": library_dir,
        "mods_dir": library_dir / "mods",
        "mod_config_file": library_dir / "mod_config.json",
        "mod_tracker_file": library_dir / "mod_tracker.json",
    }
    custom_paths = resolve_mod_paths_for_game("GENSHIN", custom_root=tmp_path / "custom")
    assert custom_paths["game_id"] == "genshin"
    assert custom_paths["mods_dir"] == tmp_path / "custom" / "genshin" / "mods"


@pytest.mark.parametrize("game_id", GAME_IDS)
def test_custom_mod_library_settings_key(game_id):
    assert get_custom_mod_library_settings_key(game_id) == f"{game_id}_custom_mod_library_dir"


def test_per_game_custom_mod_library_root(tmp_path):
    settings = {"genshin_custom_mod_library_dir": str(tmp_path / "gi_mods")}
    assert get_custom_mod_library_root("genshin", settings=settings) == str(tmp_path / "gi_mods")
    assert get_custom_mod_library_root("hsr", settings=settings) == ""
    assert resolve_mod_library_dir("genshin", settings=settings) == tmp_path / "gi_mods"


def test_legacy_custom_mod_library_key_applies_only_to_the_default_game(isolated_user_dirs, tmp_path):
    settings = {"custom_mod_library_dir": str(tmp_path / "legacy_mods")}
    assert get_custom_mod_library_root("zzz", settings=settings) == str(tmp_path / "legacy_mods")
    assert get_custom_mod_library_root("genshin", settings=settings) == ""
    assert resolve_mod_library_dir("hsr", settings=settings) == isolated_user_dirs.config_dir / "games" / "hsr" / "mod_library"


def test_per_game_custom_key_wins_over_the_legacy_key(tmp_path):
    settings = {"custom_mod_library_dir": str(tmp_path / "legacy"), "zzz_custom_mod_library_dir": str(tmp_path / "per_game")}
    assert get_custom_mod_library_root("zzz", settings=settings) == str(tmp_path / "per_game")


def test_custom_mod_library_root_is_read_from_settings_file(tmp_path):
    write_settings({"hsr_custom_mod_library_dir": str(tmp_path / "hsr_mods")})
    assert get_custom_mod_library_root("hsr") == str(tmp_path / "hsr_mods")
    assert resolve_mod_library_dir("hsr") == tmp_path / "hsr_mods"


@pytest.mark.parametrize("settings_text", ["{not json", "", "\x00\x01", '{"zzz_custom_mod_library_dir": '])
def test_malformed_settings_file_never_raises(isolated_user_dirs, settings_text):
    get_settings_file().write_text(settings_text, encoding="utf-8")
    assert get_custom_mod_library_root("zzz") == ""
    assert resolve_mod_library_dir("zzz") == isolated_user_dirs.config_dir / "games" / "zzz" / "mod_library"


def test_missing_settings_file_uses_default_library(isolated_user_dirs):
    assert not get_settings_file().exists()
    assert get_custom_mod_library_root("genshin") == ""
    assert resolve_mod_library_dir("genshin") == isolated_user_dirs.config_dir / "games" / "genshin" / "mod_library"


def test_set_mod_library_dir_overrides_and_resets(isolated_user_dirs, tmp_path):
    default_library = isolated_user_dirs.config_dir / "games" / "zzz" / "mod_library"
    assert get_default_mod_library_dir() == default_library
    assert get_mod_library_dir() == default_library
    set_mod_library_dir(str(tmp_path / "custom"))
    assert get_mod_library_dir() == tmp_path / "custom"
    set_mod_library_dir("")
    assert get_mod_library_dir() == default_library


@pytest.mark.parametrize(
    "per_game_helper, file_name",
    [
        (get_game_sound_database_file, "sound_database.json"),
        (get_game_fingerprint_database_file, "fingerprint_database.json"),
        (get_game_constellation_index_file, "constellation_index.sqlite"),
    ],
)
@pytest.mark.parametrize("game_id", GAME_IDS)
def test_per_game_database_files(isolated_user_dirs, per_game_helper, file_name, game_id):
    assert per_game_helper(game_id) == isolated_user_dirs.config_dir / "games" / game_id / file_name


@pytest.mark.parametrize(
    "per_game_helper, legacy_helper",
    [
        (get_game_sound_database_file, get_sound_database_file),
        (get_game_fingerprint_database_file, get_fingerprint_database_file),
        (get_game_constellation_index_file, get_constellation_index_file),
    ],
)
def test_legacy_unsuffixed_database_files_are_the_default_game_ones(per_game_helper, legacy_helper):
    assert legacy_helper() == per_game_helper("zzz")
    assert legacy_helper() == per_game_helper("unknown")
    assert legacy_helper() != per_game_helper("genshin")


def test_hirc_draft_paths_are_per_game(isolated_user_dirs):
    assert get_game_hirc_draft_file("hsr") == isolated_user_dirs.config_dir / "games" / "hsr" / "hirc_mod_draft.json"
    assert get_game_hirc_draft_wem_dir("genshin") == isolated_user_dirs.config_dir / "games" / "genshin" / "hirc_draft_wems"


def test_no_path_helper_escapes_the_isolated_user_dirs(isolated_user_dirs):
    user_root = isolated_user_dirs.config_dir.parent.parent
    helpers_output = [
        get_config_dir(),
        get_data_dir(),
        get_settings_file(),
        get_tools_dir(),
        get_state_dir(),
        get_cache_dir(),
        get_updates_dir(),
        *(get_game_mod_library_dir(game_id) for game_id in GAME_IDS),
        *(get_game_state_dir(game_id) for game_id in GAME_IDS),
    ]
    assert all(user_root in Path(path).parents for path in helpers_output)
