from fnmatch import fnmatch
from pathlib import Path

import pytest

import src.core.app_config as app_config
from src.core.game_registry import (
    DEFAULT_GAME_ID,
    build_audio_paths,
    detect_game_id_from_path,
    extract_game_data_dir_from_audio_path,
    get_audio_settings_keys,
    get_data_dir_to_game_id_map,
    get_game,
    get_game_language_folders,
    get_game_subfolder_sort_priority,
    get_gamebanana_game_id,
    get_supported_game_ids,
    get_supported_games,
    is_valid_game_data_dir,
    normalize_game_data_dir,
    normalize_game_id,
    normalize_game_mode,
)
from helpers import make_game_install

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ALL_GAMES = get_supported_games()
GAME_IDS = [game.id for game in ALL_GAMES]


@pytest.mark.parametrize(
    "field_name",
    ["id", "build_target", "display_name", "short_label", "data_dir_name", "install_dir_name", "mod_file_ext", "assets_dir", "gamebanana_game_id"],
)
def test_game_fields_are_unique_across_games(field_name):
    values = [getattr(game, field_name) for game in ALL_GAMES]
    assert len(set(values)) == len(values)


def test_default_game_is_supported():
    assert DEFAULT_GAME_ID == "zzz"
    assert DEFAULT_GAME_ID in get_supported_game_ids()
    assert get_supported_game_ids() == ("zzz", "genshin", "hsr")


@pytest.mark.parametrize("game", ALL_GAMES, ids=GAME_IDS)
def test_game_branding_is_consistent(game):
    assert game.mod_file_ext == "." + game.mod_file_ext_upper.lower()
    assert game.build_target == game.mod_file_ext_upper
    assert game.logo_png.startswith(game.assets_dir)
    assert game.logo_256.startswith(game.assets_dir)
    assert game.app_full_name.startswith(game.display_name)
    assets_dir = PROJECT_ROOT / "src" / "gui" / "assets" / game.assets_dir
    assert (assets_dir / game.logo_png).is_file()
    assert (assets_dir / game.logo_256).is_file()


@pytest.mark.parametrize("game", ALL_GAMES, ids=GAME_IDS)
def test_game_pck_globs_match_their_prefixes(game):
    assert fnmatch(f"{game.soundbank_pck_prefix}1.pck", game.soundbank_pck_glob)
    assert fnmatch(f"{game.streamed_pck_prefix}1.pck", game.streamed_pck_glob)
    assert game.soundbank_pck_prefix.startswith(game.soundbank_pck_filter_prefix)
    assert game.streamed_pck_prefix.startswith(game.streamed_pck_filter_prefix)
    assert not fnmatch(f"{game.soundbank_pck_prefix}1.pck", game.streamed_pck_glob)


@pytest.mark.parametrize("game", ALL_GAMES, ids=GAME_IDS)
def test_game_has_theme_palette_and_browser_handler(game):
    from src.gui.backend.audio_games import _CANONICAL_BROWSER_HANDLER_CLASSES

    assert game.id in app_config.GAME_THEME_PALETTES
    assert game.id in _CANONICAL_BROWSER_HANDLER_CLASSES


@pytest.mark.parametrize("game", ALL_GAMES, ids=GAME_IDS)
def test_game_defaults_protect_override_pcks_and_offer_every_loop_mode(game):
    assert game.protected_pcks == frozenset({"Patch.pck", "Hotfix.pck"})
    assert set(game.loop_point_modes) == {"auto", "manual", "disabled"}
    assert "Full" in game.non_language_tabs
    language_folder_names = [folder for folder, _ in game.language_folders]
    assert len(set(language_folder_names)) == len(language_folder_names)


@pytest.mark.parametrize(
    "game_mode, expected_game_id",
    [
        ("zzz", "zzz"),
        ("zzar", "zzz"),
        ("ZZAR", "zzz"),
        ("  Zzz  ", "zzz"),
        ("genshin", "genshin"),
        ("gi", "genshin"),
        ("GI", "genshin"),
        ("giar", "genshin"),
        ("hsr", "hsr"),
        ("srar", "hsr"),
        ("SRAR", "hsr"),
    ],
)
def test_normalize_game_mode_resolves_aliases(game_mode, expected_game_id):
    assert normalize_game_mode(game_mode) == expected_game_id


@pytest.mark.parametrize("unknown_mode", ["", None, "starrail", "wuwa", "zzz2"])
def test_normalize_game_mode_falls_back_to_default(unknown_mode):
    assert normalize_game_mode(unknown_mode) == DEFAULT_GAME_ID
    assert normalize_game_mode(unknown_mode, default="hsr") == "hsr"


@pytest.mark.parametrize("game_id", GAME_IDS)
def test_normalize_game_id_accepts_canonical_ids_in_any_case(game_id):
    assert normalize_game_id(game_id.upper()) == game_id
    assert normalize_game_id(f" {game_id} ") == game_id


@pytest.mark.parametrize("alias", ["zzar", "gi", "giar", "srar"])
def test_normalize_game_id_does_not_resolve_mode_aliases(alias):
    assert normalize_game_id(alias) == DEFAULT_GAME_ID
    assert normalize_game_id(alias, default="genshin") == "genshin"


def test_get_game_falls_back_to_default_game():
    assert get_game("unknown").id == DEFAULT_GAME_ID
    assert get_game(None).id == DEFAULT_GAME_ID
    assert get_game("unknown", default="hsr").id == "hsr"


@pytest.mark.parametrize("game_id, expected_gamebanana_id", [("zzz", 19567), ("genshin", 8552), ("hsr", 18366)])
def test_gamebanana_ids(game_id, expected_gamebanana_id):
    assert get_gamebanana_game_id(game_id) == expected_gamebanana_id


def test_language_folders_and_sort_priority_are_plain_dicts():
    assert get_game_language_folders("zzz")["Jp"] == "Japanese"
    assert get_game_language_folders("genshin")["English(US)"] == "English"
    assert get_game_subfolder_sort_priority("genshin") == {"BeyondUGC": 1, "MusicGame": 2}
    assert get_game_subfolder_sort_priority("zzz") == {}


@pytest.mark.parametrize("game_id", GAME_IDS)
def test_audio_settings_keys_are_prefixed_by_game_id(game_id):
    assert get_audio_settings_keys(game_id) == (f"{game_id}_game_audio_dir", f"{game_id}_persistent_audio_dir")


def test_audio_settings_keys_for_unknown_game_use_the_default_game():
    assert get_audio_settings_keys("nope") == ("zzz_game_audio_dir", "zzz_persistent_audio_dir")


@pytest.mark.parametrize(
    "game_id, streaming_subpath, persistent_subpath",
    [
        ("zzz", "StreamingAssets/Audio/Windows", "Persistent/Audio/Windows"),
        ("genshin", "StreamingAssets/AudioAssets", "Persistent/AudioAssets"),
        ("hsr", "StreamingAssets/Audio/AudioPackage/Windows", "Persistent/Audio/AudioPackage/Windows"),
    ],
)
def test_build_audio_paths(tmp_path, game_id, streaming_subpath, persistent_subpath):
    data_dir = tmp_path / get_game(game_id).data_dir_name
    streaming_root, persistent_root = build_audio_paths(game_id, data_dir)
    assert streaming_root == data_dir / streaming_subpath
    assert persistent_root == data_dir / persistent_subpath


def test_data_dir_map_covers_every_game():
    assert get_data_dir_to_game_id_map() == {game.data_dir_name: game.id for game in ALL_GAMES}


@pytest.mark.parametrize("game_id", GAME_IDS)
def test_detect_game_id_from_data_dir_and_nested_audio_paths(tmp_path, game_id):
    install = make_game_install(tmp_path, game_id)
    assert detect_game_id_from_path(install.data_dir) == game_id
    assert detect_game_id_from_path(str(install.streaming_root)) == game_id
    assert detect_game_id_from_path(install.persistent_root / "En" / "Patch.pck") == game_id


@pytest.mark.parametrize("path_value", ["", None])
def test_detect_game_id_from_empty_path_returns_default(path_value):
    assert detect_game_id_from_path(path_value) == DEFAULT_GAME_ID
    assert detect_game_id_from_path(path_value, default=None) is None


def test_detect_game_id_from_unrelated_path_returns_default(tmp_path):
    assert detect_game_id_from_path(tmp_path / "Music" / "song.wav") == DEFAULT_GAME_ID
    assert detect_game_id_from_path(tmp_path / "Music", default=None) is None


@pytest.mark.parametrize("game_id", GAME_IDS)
def test_normalize_game_data_dir_descends_from_the_install_root(tmp_path, game_id):
    install = make_game_install(tmp_path, game_id)
    assert normalize_game_data_dir(install.game_root) == install.data_dir
    assert normalize_game_data_dir(install.data_dir) == install.data_dir


def test_normalize_game_data_dir_keeps_unrelated_paths(tmp_path):
    assert normalize_game_data_dir(tmp_path / "Somewhere") == tmp_path / "Somewhere"


@pytest.mark.parametrize("game_id", GAME_IDS)
def test_is_valid_game_data_dir(tmp_path, game_id):
    install = make_game_install(tmp_path, game_id)
    assert is_valid_game_data_dir(install.data_dir)
    assert not is_valid_game_data_dir(install.game_root)
    assert not is_valid_game_data_dir(install.data_dir / "StreamingAssets")


def test_is_valid_game_data_dir_requires_streaming_assets_and_existence(tmp_path):
    data_dir_without_streaming = tmp_path / "ZenlessZoneZero_Data"
    data_dir_without_streaming.mkdir()
    assert not is_valid_game_data_dir(data_dir_without_streaming)
    assert not is_valid_game_data_dir(tmp_path / "missing" / "GenshinImpact_Data")
    renamed_dir = tmp_path / "Renamed_Data"
    (renamed_dir / "StreamingAssets").mkdir(parents=True)
    assert not is_valid_game_data_dir(renamed_dir)


@pytest.mark.parametrize("game_id", GAME_IDS)
def test_extract_game_data_dir_from_audio_path(tmp_path, game_id):
    install = make_game_install(tmp_path, game_id)
    assert extract_game_data_dir_from_audio_path(install.streaming_root) == str(install.data_dir)
    assert extract_game_data_dir_from_audio_path(str(install.persistent_root)) == str(install.data_dir)
    assert extract_game_data_dir_from_audio_path(install.data_dir) == str(install.data_dir)


def test_extract_game_data_dir_from_unrelated_or_empty_path(tmp_path):
    assert extract_game_data_dir_from_audio_path(tmp_path / "audio") == str(tmp_path / "audio")
    assert extract_game_data_dir_from_audio_path("") == ""
    assert extract_game_data_dir_from_audio_path(None) == ""


@pytest.mark.parametrize("game", ALL_GAMES, ids=GAME_IDS)
def test_is_protected_pck_matches_bare_qualified_and_full_keys(tmp_path, game):
    full_patch_path = tmp_path / game.data_dir_name / "Persistent" / "Patch.pck"
    assert game.is_protected_pck("Patch.pck")
    assert game.is_protected_pck("Hotfix.pck")
    assert game.is_protected_pck("En/Patch.pck")
    assert game.is_protected_pck(str(full_patch_path))
    assert game.is_protected_pck(full_patch_path)


@pytest.mark.parametrize("pck_key", ["SoundBank_SFX_1.pck", "En/Streamed_SFX_1.pck", "Patch.pck.xxar_backup", "MyPatch.pck", "Patch"])
def test_is_protected_pck_rejects_other_pcks(pck_key):
    assert not get_game("zzz").is_protected_pck(pck_key)
