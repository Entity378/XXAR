import pytest

from helpers import build_bnk, build_pck, make_wem
from mod_builders import (
    EMBEDDED_WEM_ID,
    GAME_IDS,
    MUSIC_BNK_ID,
    SECOND_SFX_BNK_ID,
    SECOND_SFX_BNK_WEM_ID,
    SFX_BNK_ID,
    SHARED_WEM_ID,
    STREAMED_WEM_ID,
    GameKeys,
    bank_bytes,
    bank_wems,
    install_enabled,
    loose_wem,
    make_mod_env,
    mod_entry,
    music_segment_object,
    music_track_object,
    read_music_track,
    run_apply,
    snapshot_files,
    write_pkg_version_manifest,
)
from src.mods.hirc_mod_apply import apply_hirc_track_patches
from src.wwise.bnk_handler import BNKFile

SEGMENT_ID = 700
TRACK_ID = 701
OLD_SOURCE_ID = 170001
NEW_SOURCE_ID = 170002
UNKNOWN_BNK_ID = 424242
REALLOCATED_ID_BASE = 0xF0000000


def music_bank(loop_track_props=None):
    return build_bnk(MUSIC_BNK_ID, hirc_objects=[
        music_track_object(TRACK_ID, OLD_SOURCE_ID, 0.0, 30000.0, parent_id=SEGMENT_ID, props=loop_track_props),
        music_segment_object(SEGMENT_ID, [TRACK_ID], 30000.0),
    ])


def soundbank_with_music(loop_track_props=None, embedded_bytes=None):
    sfx_bnk = build_bnk(SFX_BNK_ID, {EMBEDDED_WEM_ID: embedded_bytes or make_wem(1), SHARED_WEM_ID: make_wem(2, 48)})
    second_sfx_bnk = build_bnk(SECOND_SFX_BNK_ID, {SECOND_SFX_BNK_WEM_ID: make_wem(3)})
    return build_pck(banks=[(SFX_BNK_ID, 0, sfx_bnk), (SECOND_SFX_BNK_ID, 0, second_sfx_bnk), (MUSIC_BNK_ID, 0, music_bank(loop_track_props))])


def hirc_env(tmp_path, game_id="zzz", loop_track_props=None, persistent_files=None):
    keys = GameKeys(game_id)
    return make_mod_env(tmp_path, game_id, streaming_files={keys.soundbank: soundbank_with_music(loop_track_props)}, persistent_files=persistent_files)


def track_patch(pck_name, **patch_fields):
    return {
        "pck_name": pck_name,
        "bnk_id": MUSIC_BNK_ID,
        "track_obj_id": TRACK_ID,
        "source_remaps": [
            {"slot": "src", "index": 0, "old_source_id": OLD_SOURCE_ID, "new_source_id": NEW_SOURCE_ID},
            {"slot": "pl", "index": 0, "old_source_id": OLD_SOURCE_ID, "new_source_id": NEW_SOURCE_ID},
        ],
        **patch_fields,
    }


def apply_patches(env, patches, fresh_clone=False, soundbank_glob="game"):
    if soundbank_glob == "game":
        soundbank_glob = env.game.soundbank_pck_glob
    return apply_hirc_track_patches(patches, env.streaming_root, env.persistent_root, fresh_clone=fresh_clone, soundbank_glob=soundbank_glob)


def overlay_track(env, pck_key=None):
    return read_music_track(bank_bytes(env.persistent_root / (pck_key or env.keys.soundbank), MUSIC_BNK_ID), TRACK_ID)


@pytest.mark.parametrize("game_id", GAME_IDS)
def test_fresh_clone_copies_the_soundbank_and_remaps_the_track(tmp_path, game_id):
    env = hirc_env(tmp_path, game_id)
    streaming_before = snapshot_files(env.streaming_root)

    apply_summary = apply_patches(env, [track_patch(env.keys.soundbank, loop_ms=25000.0)], fresh_clone=True)
    overlay = env.persistent_root / env.keys.soundbank

    assert apply_summary == {"patched_files": 1, "patched_bnks": 1}
    assert overlay_track(env)[:2] == ([NEW_SOURCE_ID], [(NEW_SOURCE_ID, 0.0, 25000.0)])
    assert overlay.stat().st_size == (env.streaming_root / env.keys.soundbank).stat().st_size
    assert bank_bytes(overlay, SECOND_SFX_BNK_ID) == bank_bytes(env.streaming_root / env.keys.soundbank, SECOND_SFX_BNK_ID)
    assert snapshot_files(env.streaming_root) == streaming_before


@pytest.mark.parametrize("game_id", GAME_IDS)
def test_a_volume_insert_grows_the_bank_and_repacks_the_overlay(tmp_path, game_id):
    env = hirc_env(tmp_path, game_id)

    apply_summary = apply_patches(env, [track_patch(env.keys.soundbank, volume_db=-5.0)], fresh_clone=True)
    overlay = env.persistent_root / env.keys.soundbank

    assert apply_summary == {"patched_files": 1, "patched_bnks": 1}
    assert overlay_track(env)[2] == {0x00: -5.0}
    assert len(bank_bytes(overlay, MUSIC_BNK_ID)) == len(bank_bytes(env.streaming_root / env.keys.soundbank, MUSIC_BNK_ID)) + 5
    assert BNKFile(bnk_bytes=bank_bytes(overlay, MUSIC_BNK_ID)).data["HIRC"].entries == 2
    assert bank_wems(overlay, SFX_BNK_ID) == bank_wems(env.streaming_root / env.keys.soundbank, SFX_BNK_ID)
    assert list(overlay.parent.glob("*.pck")) == [overlay]


def test_a_volume_overwrite_keeps_the_overlay_size(tmp_path):
    env = hirc_env(tmp_path, loop_track_props={0x00: -1.0})

    apply_patches(env, [track_patch(env.keys.soundbank, volume_db=-9.0)], fresh_clone=True)

    assert overlay_track(env)[2] == {0x00: -9.0}
    assert (env.persistent_root / env.keys.soundbank).stat().st_size == (env.streaming_root / env.keys.soundbank).stat().st_size


def test_without_fresh_clone_an_existing_overlay_keeps_its_other_changes(tmp_path):
    keys = GameKeys("zzz")
    earlier_overlay = soundbank_with_music(embedded_bytes=make_wem(99))
    env = hirc_env(tmp_path, persistent_files={keys.soundbank: earlier_overlay})

    apply_patches(env, [track_patch(keys.soundbank)], fresh_clone=False)

    assert bank_wems(env.persistent_root / keys.soundbank, SFX_BNK_ID)[EMBEDDED_WEM_ID] == make_wem(99)
    assert overlay_track(env)[0] == [NEW_SOURCE_ID]


def test_fresh_clone_discards_a_stale_overlay(tmp_path):
    keys = GameKeys("zzz")
    stale_overlay = soundbank_with_music(embedded_bytes=make_wem(99))
    env = hirc_env(tmp_path, persistent_files={keys.soundbank: stale_overlay})

    apply_patches(env, [track_patch(keys.soundbank)], fresh_clone=True)

    assert bank_wems(env.persistent_root / keys.soundbank, SFX_BNK_ID)[EMBEDDED_WEM_ID] == make_wem(1)
    assert overlay_track(env)[0] == [NEW_SOURCE_ID]


def test_reapplying_the_same_patch_changes_nothing(tmp_path):
    env = hirc_env(tmp_path)
    patches = [track_patch(env.keys.soundbank, loop_ms=25000.0)]
    apply_patches(env, patches, fresh_clone=False)
    overlay_after_first_apply = (env.persistent_root / env.keys.soundbank).read_bytes()

    second_summary = apply_patches(env, patches, fresh_clone=False)

    assert second_summary == {"patched_files": 0, "patched_bnks": 0}
    assert (env.persistent_root / env.keys.soundbank).read_bytes() == overlay_after_first_apply


def test_a_stale_pck_name_still_finds_the_bank_by_id(tmp_path):
    env = hirc_env(tmp_path)

    apply_summary = apply_patches(env, [track_patch("Full/SoundBank_SFX_99.pck")], fresh_clone=True)

    assert apply_summary == {"patched_files": 1, "patched_bnks": 1}
    assert overlay_track(env)[0] == [NEW_SOURCE_ID]


def test_an_unknown_bank_is_skipped(tmp_path):
    env = hirc_env(tmp_path)
    unknown_bank_patch = dict(track_patch(env.keys.soundbank), bnk_id=UNKNOWN_BNK_ID)

    apply_summary = apply_patches(env, [unknown_bank_patch], fresh_clone=True)

    assert apply_summary == {"patched_files": 0, "patched_bnks": 0}
    assert list(env.persistent_root.rglob("*.pck")) == []


def test_a_patch_for_an_unknown_track_leaves_the_overlay_pristine(tmp_path):
    env = hirc_env(tmp_path)
    unknown_track_patch = dict(track_patch(env.keys.soundbank), track_obj_id=999)

    apply_summary = apply_patches(env, [unknown_track_patch], fresh_clone=True)

    assert apply_summary == {"patched_files": 0, "patched_bnks": 0}
    assert (env.persistent_root / env.keys.soundbank).read_bytes() == (env.streaming_root / env.keys.soundbank).read_bytes()


def test_the_soundbank_glob_limits_where_banks_are_searched(tmp_path):
    keys = GameKeys("zzz")
    streamed_holding_music = build_pck(banks=[(MUSIC_BNK_ID, 0, music_bank())], sounds=[(STREAMED_WEM_ID, 0, make_wem(4))])
    env = make_mod_env(tmp_path, "zzz", streaming_files={keys.streamed: streamed_holding_music})

    summary_with_game_glob = apply_patches(env, [track_patch(keys.streamed)], fresh_clone=True)
    summary_with_any_pck = apply_patches(env, [track_patch(keys.streamed)], fresh_clone=True, soundbank_glob=None)

    assert summary_with_game_glob == {"patched_files": 0, "patched_bnks": 0}
    assert summary_with_any_pck == {"patched_files": 1, "patched_bnks": 1}
    assert overlay_track(env, keys.streamed)[0] == [NEW_SOURCE_ID]


def test_missing_roots_skip_every_patch(tmp_path):
    env = hirc_env(tmp_path)

    apply_summary = apply_hirc_track_patches([track_patch(env.keys.soundbank)], env.streaming_root / "missing", env.persistent_root)

    assert apply_summary == {"patched_files": 0, "patched_bnks": 0}


def test_the_status_callback_reports_patched_files(tmp_path):
    env = hirc_env(tmp_path)
    status_messages = []

    apply_hirc_track_patches([track_patch(env.keys.soundbank)], env.streaming_root, env.persistent_root, fresh_clone=True, status_cb=status_messages.append)

    assert status_messages == ["HIRC track patches applied in 1 bank file(s)."]


@pytest.mark.parametrize("game_id", GAME_IDS)
def test_apply_mods_applies_a_hirc_only_mod(tmp_path, game_id):
    env = hirc_env(tmp_path, game_id)
    install_enabled(env, "Hirc Only", {}, hirc_patches=[track_patch(env.keys.soundbank, loop_ms=20000.0, volume_db=-4.0)])

    run_apply(env)

    assert overlay_track(env) == ([NEW_SOURCE_ID], [(NEW_SOURCE_ID, 0.0, 20000.0)], {0x00: -4.0})


def test_disabling_a_hirc_only_mod_removes_its_overlay(tmp_path):
    env = hirc_env(tmp_path)
    write_pkg_version_manifest(env)
    install_enabled(env, "Hirc Only", {}, hirc_patches=[track_patch(env.keys.soundbank)])
    run_apply(env)

    env.manager.set_all_mods_enabled(False)
    run_apply(env)

    assert list(env.persistent_root.rglob("*.pck")) == []


def test_later_mods_win_per_track_and_remaps_merge_by_slot(tmp_path):
    env = hirc_env(tmp_path)
    source_only_patch = {"pck_name": env.keys.soundbank, "bnk_id": MUSIC_BNK_ID, "track_obj_id": TRACK_ID, "loop_ms": 10000.0,
                         "source_remaps": [{"slot": "src", "index": 0, "old_source_id": OLD_SOURCE_ID, "new_source_id": NEW_SOURCE_ID}]}
    playlist_only_patch = {"pck_name": env.keys.soundbank, "bnk_id": MUSIC_BNK_ID, "track_obj_id": TRACK_ID, "loop_ms": 15000.0,
                           "source_remaps": [{"slot": "pl", "index": 0, "old_source_id": OLD_SOURCE_ID, "new_source_id": NEW_SOURCE_ID}]}
    install_enabled(env, "Earlier Hirc", {}, hirc_patches=[source_only_patch])
    install_enabled(env, "Later Hirc", {}, hirc_patches=[playlist_only_patch])

    run_apply(env)

    assert overlay_track(env)[:2] == ([NEW_SOURCE_ID], [(NEW_SOURCE_ID, 0.0, 15000.0)])


def test_an_added_wem_colliding_with_an_original_id_is_moved_to_a_free_id(tmp_path):
    env = hirc_env(tmp_path)
    colliding_add = mod_entry(env.work_dir / "add", STREAMED_WEM_ID, make_wem(120), is_add=True)
    remap_to_added_wem = dict(track_patch(env.keys.soundbank), source_remaps=[
        {"slot": "src", "index": 0, "old_source_id": OLD_SOURCE_ID, "new_source_id": STREAMED_WEM_ID},
        {"slot": "pl", "index": 0, "old_source_id": OLD_SOURCE_ID, "new_source_id": STREAMED_WEM_ID},
    ])
    install_enabled(env, "Add Mod", {env.keys.streamed: [colliding_add]}, hirc_patches=[remap_to_added_wem])

    run_apply(env)
    modded_streamed = env.persistent_root / env.keys.streamed

    assert loose_wem(modded_streamed, STREAMED_WEM_ID) == loose_wem(env.streaming_root / env.keys.streamed, STREAMED_WEM_ID)
    assert loose_wem(modded_streamed, REALLOCATED_ID_BASE) == make_wem(120)
    assert overlay_track(env)[:2] == ([REALLOCATED_ID_BASE], [(REALLOCATED_ID_BASE, 0.0, 30000.0)])
