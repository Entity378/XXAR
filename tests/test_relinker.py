import json

import pytest

from helpers import build_pck, make_game_install, make_wem
from overlay_builders import bank, bnk_replacement, sound, wem_replacement, write_persist_manifest
from src.mods.mod_relinker import GameAudioIndex, relink_metadata, relink_replacements, relink_tracker
from src.mods.persistent_manager import PersistentModManager
from src.wwise.override_pck_patcher import patch_override_pcks

ENGLISH = {1: "english"}


def make_updated_game(tmp_path, persistent_files=None):
    # The update moved WEM 1002 out of bank 100 into Streamed_SFX_7 and WEM 2001 from Streamed_SFX_1 into bank 100.
    return make_game_install(
        tmp_path, "zzz",
        streaming_files={
            "Full/SoundBank_SFX_1.pck": build_pck(banks=[bank(100, {1001: make_wem(1), 2001: make_wem(2)})]),
            "Full/Streamed_SFX_1.pck": build_pck(sounds=[sound(3001)]),
            "Full/Streamed_SFX_7.pck": build_pck(sounds=[sound(1002)]),
        },
        persistent_files=persistent_files,
    )


@pytest.mark.parametrize(("pck_key", "expected_rel"), [
    ("Full/Streamed_SFX_7.pck", "Full/Streamed_SFX_7.pck"),
    ("Streamed_SFX_7.pck", "Full/Streamed_SFX_7.pck"),
    ("Streamed_SFX_1.pck", "Full/Streamed_SFX_1.pck"),
])
def test_find_live_pck_resolves_keys_like_locate_pck_paths(tmp_path, pck_key, expected_rel):
    install = make_updated_game(tmp_path)
    (install.streaming_root / "Full" / "Deep").mkdir()
    (install.streaming_root / "Full" / "Deep" / "Streamed_SFX_1.pck").write_bytes(build_pck(sounds=[sound(9)]))
    index = GameAudioIndex(install.streaming_root, install.game)

    assert index.find_live_pck(pck_key) == install.streaming_root / expected_rel


def test_find_live_pck_returns_nothing_for_missing_or_stale_keys(tmp_path):
    install = make_updated_game(tmp_path)
    index = GameAudioIndex(install.streaming_root, install.game)

    assert index.find_live_pck("Missing.pck") is None
    assert index.find_live_pck(str(tmp_path / "old_install" / "Streamed_SFX_7.pck")) is None


@pytest.mark.parametrize(("pck_key", "file_type", "bnk_id", "wem_id", "expected"), [
    ("Full/SoundBank_SFX_1.pck", "bnk", 100, 1001, True),
    ("Full/SoundBank_SFX_1.pck", "bnk", 100, 1002, False),
    ("Full/SoundBank_SFX_1.pck", "bnk", 999, 1001, False),
    ("Full/Streamed_SFX_7.pck", "wem", None, 1002, True),
    ("Streamed_SFX_7.pck", "wem", None, 1002, True),
    ("Full/Streamed_SFX_1.pck", "wem", None, 2001, False),
    ("Missing.pck", "wem", None, 1002, False),
])
def test_entry_is_valid_checks_the_live_game_audio(tmp_path, pck_key, file_type, bnk_id, wem_id, expected):
    install = make_updated_game(tmp_path)
    index = GameAudioIndex(install.streaming_root, install.game)

    assert index.entry_is_valid(pck_key, file_type, bnk_id, wem_id) is expected


@pytest.mark.parametrize(("wem_id", "expected_home"), [
    (1002, {"pck_name": "Full/Streamed_SFX_7.pck", "file_type": "wem", "bnk_id": None}),
    (2001, {"pck_name": "Full/SoundBank_SFX_1.pck", "file_type": "bnk", "bnk_id": 100}),
    (4242, None),
])
def test_locate_finds_the_current_home_of_a_wem(tmp_path, wem_id, expected_home):
    install = make_updated_game(tmp_path)

    assert GameAudioIndex(install.streaming_root, install.game).locate(wem_id) == expected_home


def test_locate_prefers_a_soundbank_container_over_a_streamed_one(tmp_path):
    install = make_game_install(tmp_path, "zzz", streaming_files={
        "Full/Streamed_SFX_1.pck": build_pck(sounds=[sound(1002)]),
        "Full/SoundBank_SFX_2.pck": build_pck(sounds=[sound(1002)]),
    })

    home = GameAudioIndex(install.streaming_root, install.game).locate(1002)

    assert home == {"pck_name": "Full/SoundBank_SFX_2.pck", "file_type": "wem", "bnk_id": None}


def test_patch_embedded_copy_wins_and_is_read_from_the_pristine_backup(tmp_path):
    override_pck = build_pck(banks=[bank(500, {1002: make_wem(51)})])
    install = make_updated_game(tmp_path, persistent_files={"Full/Patch.pck": override_pck})
    write_persist_manifest(install, {"Full/Patch.pck": override_pck})
    patch_override_pcks(install.persistent_root, {"a.pck": {"500|1002": bnk_replacement(500, 1002)}}, install.game)
    index = GameAudioIndex(install.streaming_root, install.game)

    assert index.patch_home(1002) == ("Patch.pck", 500)
    assert index.locate(1002) == {"pck_name": "Patch.pck", "file_type": "bnk", "bnk_id": 500}
    assert index.entry_is_valid("Full/Patch.pck", "bnk", 500, 1002)
    assert not index.entry_is_valid("Full/Streamed_SFX_7.pck", "wem", None, 1002)


def test_persistent_dir_is_derived_from_the_streaming_assets_path(tmp_path):
    install = make_updated_game(tmp_path)

    assert GameAudioIndex(install.streaming_root, install.game).persistent_audio_dir == install.persistent_root
    assert GameAudioIndex(install.streaming_root, install.game, tmp_path / "custom").persistent_audio_dir == tmp_path / "custom"
    detached_index = GameAudioIndex(tmp_path / "loose_audio", install.game)
    assert detached_index.persistent_audio_dir is None
    assert detached_index.patch_home(1002) is None


def test_relink_replacements_follows_wems_the_update_moved(tmp_path):
    install = make_updated_game(tmp_path)
    audio_settings = {"volume_db": -4.0, "loop_point_mode": "manual", "loop_point_manual_ms": 500}
    replacements = {
        "Full/SoundBank_SFX_1.pck": {
            "100|1001": bnk_replacement(100, 1001, "valid.wem"),
            "100|1002": bnk_replacement(100, 1002, "moved_out.wem", **audio_settings),
        },
        "Full/Streamed_SFX_1.pck": {"2001": wem_replacement(2001, "moved_in.wem")},
    }

    result = relink_replacements(replacements, install.streaming_root, install.game)

    assert result == {"relinked": 2, "unresolved": []}
    assert replacements == {
        "Full/SoundBank_SFX_1.pck": {
            "100|1001": bnk_replacement(100, 1001, "valid.wem"),
            "100|2001": {**wem_replacement(2001, "moved_in.wem"), "file_type": "bnk", "bnk_id": 100},
        },
        "Full/Streamed_SFX_7.pck": {"1002": {**bnk_replacement(100, 1002, "moved_out.wem", **audio_settings), "file_type": "wem", "bnk_id": None}},
    }
    assert relink_replacements(replacements, install.streaming_root, install.game) == {"relinked": 0, "unresolved": []}


@pytest.mark.parametrize("old_pck", ["Full/Streamed_SFX_1.pck", "Streamed_SFX_1.pck"])
def test_a_sound_shared_with_a_voice_bank_relinks_to_its_sfx_soundbank(tmp_path, old_pck):
    install = make_game_install(tmp_path, "zzz", streaming_files={
        "Full/En/SoundBank_En_0.pck": build_pck(banks=[bank(300, {4001: make_wem(4)}, lang_id=1)], languages=ENGLISH),
        "Full/SoundBank_SFX_8.pck": build_pck(banks=[bank(100, {4001: make_wem(4)})]),
    })
    replacements = {old_pck: {"4001": wem_replacement(4001)}}

    relink_replacements(replacements, install.streaming_root, install.game)

    assert list(replacements) == ["Full/SoundBank_SFX_8.pck"]


def test_a_voice_shared_by_two_languages_relinks_within_its_own_language(tmp_path):
    install = make_game_install(tmp_path, "zzz", streaming_files={
        "Full/En/SoundBank_En_0.pck": build_pck(banks=[bank(300, {5001: make_wem(5)}, lang_id=1)], languages=ENGLISH),
        "Full/Jp/SoundBank_Jp_0.pck": build_pck(banks=[bank(300, {5001: make_wem(5)}, lang_id=1)], languages=ENGLISH),
        "Full/Jp/Streamed_Jp_1.pck": build_pck(sounds=[sound(6001, lang_id=1)], languages=ENGLISH),
    })
    replacements = {"Full/Jp/Streamed_Jp_1.pck": {"5001": wem_replacement(5001)}}

    relink_replacements(replacements, install.streaming_root, install.game)

    assert list(replacements) == ["Full/Jp/SoundBank_Jp_0.pck"]


def test_entry_shadowed_by_a_patch_bank_is_relinked_to_the_override(tmp_path):
    install = make_updated_game(tmp_path, persistent_files={"Full/Patch.pck": build_pck(banks=[bank(500, {1001: make_wem(51)})])})
    replacements = {"Full/SoundBank_SFX_1.pck": {"100|1001": bnk_replacement(100, 1001)}}

    result = relink_replacements(replacements, install.streaming_root, install.game)

    assert result == {"relinked": 1, "unresolved": []}
    assert replacements == {"Patch.pck": {"500|1001": {**bnk_replacement(100, 1001), "bnk_id": 500}}}


def test_relink_replacements_leaves_adds_overrides_and_unresolved_entries_alone(tmp_path):
    install = make_updated_game(tmp_path)
    replacements = {
        "Full/Streamed_SFX_1.pck": {"4242": wem_replacement(4242), "9001": {**wem_replacement(9001), "is_add": True}},
        "Full/Patch.pck": {"100|1002": bnk_replacement(100, 1002)},
    }
    before = json.loads(json.dumps(replacements))

    result = relink_replacements(replacements, install.streaming_root, install.game)

    assert result == {"relinked": 0, "unresolved": [("Full/Streamed_SFX_1.pck", 4242)]}
    assert replacements == before


def test_entries_that_cannot_be_verified_are_left_untouched(tmp_path):
    install = make_updated_game(tmp_path)
    (install.streaming_root / "Full" / "Streamed_SFX_9.pck").write_bytes(b"not a pck")
    replacements = {"Full/Streamed_SFX_9.pck": {"1002": wem_replacement(1002)}}

    result = relink_replacements(replacements, install.streaming_root, install.game)

    assert result == {"relinked": 0, "unresolved": []}
    assert replacements == {"Full/Streamed_SFX_9.pck": {"1002": wem_replacement(1002)}}


def test_relink_metadata_repairs_a_flat_v1_mod(tmp_path):
    install = make_updated_game(tmp_path)
    metadata = {"format_version": "1.0", "replacements": {"Full/SoundBank_SFX_1.pck": {
        "1001": {"wem_file": "wem_files/1001.wem", "bnk_id": 100, "file_type": "bnk"},
        "1002": {"wem_file": "wem_files/1002.wem", "bnk_id": 100, "file_type": "bnk", "volume_db": -4.0},
    }}}

    result = relink_metadata(metadata, install.streaming_root, install.game)

    assert result == {"relinked": 1, "unresolved": []}
    assert metadata["replacements"] == {
        "Full/SoundBank_SFX_1.pck": {"1001": {"wem_file": "wem_files/1001.wem", "bnk_id": 100, "file_type": "bnk"}},
        "Full/Streamed_SFX_7.pck": {"1002": {"wem_file": "wem_files/1002.wem", "bnk_id": None, "file_type": "wem", "volume_db": -4.0}},
    }


@pytest.mark.parametrize("format_version", ["2.0", "3.0"])
def test_relink_metadata_repairs_a_nested_mod(tmp_path, format_version):
    install = make_updated_game(tmp_path)
    metadata = {"format_version": format_version, "replacements": {
        "Full/SoundBank_SFX_1.pck": {"100.bnk": {
            "1001": {"wem_file": "wem_files/100/1001.wem", "file_type": "bnk"},
            "1002": {"wem_file": "wem_files/100/1002.wem", "file_type": "bnk", "loop_point_mode": "disabled"},
        }},
        "Full/Streamed_SFX_1.pck": {"direct": {"2001": {"wem_file": "wem_files/2001.wem", "file_type": "wem"}}},
    }}

    result = relink_metadata(metadata, install.streaming_root, install.game)

    assert result == {"relinked": 2, "unresolved": []}
    assert metadata["replacements"] == {
        "Full/SoundBank_SFX_1.pck": {"100.bnk": {
            "1001": {"wem_file": "wem_files/100/1001.wem", "file_type": "bnk"},
            "2001": {"wem_file": "wem_files/2001.wem", "file_type": "bnk"},
        }},
        "Full/Streamed_SFX_7.pck": {"direct": {"1002": {"wem_file": "wem_files/100/1002.wem", "file_type": "wem", "loop_point_mode": "disabled"}}},
    }


def test_relink_metadata_reuses_a_shared_index(tmp_path):
    install = make_updated_game(tmp_path)
    shared_index = GameAudioIndex(install.streaming_root, install.game)
    metadata = {"format_version": "2.0", "replacements": {"Full/Streamed_SFX_1.pck": {"direct": {"2001": {"file_type": "wem"}}}}}

    result = relink_metadata(metadata, None, install.game, index=shared_index)

    assert result == {"relinked": 1, "unresolved": []}
    assert metadata["replacements"] == {"Full/SoundBank_SFX_1.pck": {"100.bnk": {"2001": {"file_type": "bnk"}}}}


def test_relink_tracker_saves_the_repaired_tracker(tmp_path):
    install = make_updated_game(tmp_path)
    manager = PersistentModManager(tracker_path=tmp_path / "mod_tracker.json")
    manager.add_replacement("Full/SoundBank_SFX_1.pck", 1002, "moved_out.wem", file_type="bnk", bnk_id=100, volume_db=-4.0)

    result = relink_tracker(manager, install.streaming_root, install.game)

    saved_tracker = json.loads(manager.mod_tracker_path.read_text(encoding="utf-8"))
    assert result == {"relinked": 1, "unresolved": []}
    assert list(saved_tracker) == ["Full/Streamed_SFX_7.pck"]
    assert (saved_tracker["Full/Streamed_SFX_7.pck"]["1002"]["wem_path"], saved_tracker["Full/Streamed_SFX_7.pck"]["1002"]["volume_db"]) == ("moved_out.wem", -4.0)


def test_relink_tracker_does_not_rewrite_a_healthy_tracker(tmp_path):
    install = make_updated_game(tmp_path)
    manager = PersistentModManager(tracker_path=tmp_path / "mod_tracker.json")
    manager.add_replacement("Full/SoundBank_SFX_1.pck", 1001, "valid.wem", file_type="bnk", bnk_id=100)
    manager.mod_tracker_path.unlink()

    assert relink_tracker(manager, install.streaming_root, install.game) == {"relinked": 0, "unresolved": []}
    assert not manager.mod_tracker_path.exists()


def test_voice_wem_moved_into_a_voice_bank_is_relinked(tmp_path):
    install = make_game_install(tmp_path, "zzz", streaming_files={
        "Full/En/SoundBank_En_1.pck": build_pck(banks=[bank(300, {3001: make_wem(1)}, lang_id=1)], languages=ENGLISH),
        "Full/En/Streamed_En_1.pck": build_pck(sounds=[sound(3002, lang_id=1)], languages=ENGLISH),
    })
    replacements = {"Full/En/Streamed_En_1.pck": {"3001": wem_replacement(3001)}}

    result = relink_replacements(replacements, install.streaming_root, install.game)

    assert result == {"relinked": 1, "unresolved": []}
    assert [(info["file_type"], info["bnk_id"]) for entries in replacements.values() for info in entries.values()] == [("bnk", 300)]
