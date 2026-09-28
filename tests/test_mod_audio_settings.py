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
    GameKeys,
    bank_bytes,
    bank_wems,
    install_enabled,
    loose_wem,
    make_mod_env,
    make_pcm_wem,
    mod_entry,
    music_segment_object,
    music_track_object,
    read_music_track,
    read_segment_duration,
    run_apply,
    sound_object,
    write_pkg_version_manifest,
)
from src.gui.backend.audio_games import get_browser_handler_class
from src.wwise.bnk_handler import BNKFile

SEGMENT_ID = 500
INTRO_TRACK_ID = 501
LOOP_TRACK_ID = 502
SFX_SOUND_ID = 600
INTRO_WEM_ID = 140001
LOOP_WEM_ID = 140002
INTRO_MS = 12000.0
LOOP_MS = 100000.0


def music_env(tmp_path, game_id, segment_duration=INTRO_MS + LOOP_MS, loop_track_props=None):
    keys = GameKeys(game_id)
    music_bnk = build_bnk(MUSIC_BNK_ID, hirc_objects=[
        music_track_object(INTRO_TRACK_ID, INTRO_WEM_ID, 0.0, INTRO_MS, parent_id=SEGMENT_ID),
        music_track_object(LOOP_TRACK_ID, LOOP_WEM_ID, INTRO_MS, LOOP_MS, parent_id=SEGMENT_ID, props=loop_track_props),
        music_segment_object(SEGMENT_ID, [INTRO_TRACK_ID, LOOP_TRACK_ID], segment_duration),
    ])
    sfx_bnk = build_bnk(SFX_BNK_ID, {EMBEDDED_WEM_ID: make_wem(1), SHARED_WEM_ID: make_wem(2, 48)}, hirc_objects=[sound_object(SFX_SOUND_ID, EMBEDDED_WEM_ID)])
    second_sfx_bnk = build_bnk(SECOND_SFX_BNK_ID, {SECOND_SFX_BNK_WEM_ID: make_wem(3)})
    streaming_files = {
        keys.soundbank: build_pck(banks=[(SFX_BNK_ID, 0, sfx_bnk), (SECOND_SFX_BNK_ID, 0, second_sfx_bnk), (MUSIC_BNK_ID, 0, music_bnk)]),
        keys.music: build_pck(sounds=[(INTRO_WEM_ID, 0, make_wem(20)), (LOOP_WEM_ID, 0, make_wem(21))]),
    }
    return make_mod_env(tmp_path, game_id, streaming_files=streaming_files)


def install_loop_mod(env, wem_bytes, **audio_settings):
    return install_enabled(env, "Music Mod", {env.keys.music: [mod_entry(env.work_dir / "music", LOOP_WEM_ID, wem_bytes, **audio_settings)]})


def modded_music_bank(env):
    return bank_bytes(env.persistent_root / env.keys.soundbank, MUSIC_BNK_ID)


def hirc_chunk(bnk_bytes):
    return bnk_bytes[bnk_bytes.index(b"HIRC"):]


@pytest.mark.parametrize("game_id", GAME_IDS)
def test_auto_loop_point_retimes_an_intro_plus_loop_segment(tmp_path, game_id):
    env = music_env(tmp_path, game_id)
    install_loop_mod(env, make_pcm_wem(90000), loop_point_mode="auto")

    run_apply(env)
    music_bank = modded_music_bank(env)

    assert read_music_track(music_bank, LOOP_TRACK_ID)[1] == [(LOOP_WEM_ID, INTRO_MS, 90000.0)]
    assert read_music_track(music_bank, INTRO_TRACK_ID)[1] == [(INTRO_WEM_ID, 0.0, INTRO_MS)]
    assert read_segment_duration(music_bank, SEGMENT_ID) == INTRO_MS + 90000.0
    assert loose_wem(env.persistent_root / env.keys.music, LOOP_WEM_ID) == make_pcm_wem(90000)


@pytest.mark.parametrize("game_id", GAME_IDS)
def test_manual_loop_point_on_a_loop_with_tail_keeps_the_segment_timing(tmp_path, game_id):
    loop_with_tail_duration = 110000.0
    env = music_env(tmp_path, game_id, segment_duration=loop_with_tail_duration)
    install_loop_mod(env, make_wem(22), loop_point_mode="manual", loop_point_manual_ms=90000)

    run_apply(env)
    music_bank = modded_music_bank(env)

    assert read_music_track(music_bank, LOOP_TRACK_ID)[1] == [(LOOP_WEM_ID, INTRO_MS, 90000.0)]
    assert read_segment_duration(music_bank, SEGMENT_ID) == loop_with_tail_duration


@pytest.mark.parametrize("game_id", GAME_IDS)
def test_a_mod_without_audio_settings_leaves_the_music_bank_untouched(tmp_path, game_id):
    env = music_env(tmp_path, game_id)
    install_loop_mod(env, make_pcm_wem(90000))

    run_apply(env)

    assert not (env.persistent_root / env.keys.soundbank).exists()
    assert loose_wem(env.persistent_root / env.keys.music, LOOP_WEM_ID) == make_pcm_wem(90000)


@pytest.mark.parametrize("game_id", GAME_IDS)
def test_volume_is_inserted_on_a_music_track_without_one(tmp_path, game_id):
    env = music_env(tmp_path, game_id)
    install_loop_mod(env, make_wem(23), volume_enabled=True, volume_db=-6.0)

    run_apply(env)
    music_bank = modded_music_bank(env)

    assert read_music_track(music_bank, LOOP_TRACK_ID)[2] == {0x00: -6.0}
    assert read_music_track(music_bank, INTRO_TRACK_ID)[2] == {}
    assert BNKFile(bnk_bytes=music_bank).data["HIRC"].entries == 3
    assert bank_bytes(env.persistent_root / env.keys.soundbank, SECOND_SFX_BNK_ID) == bank_bytes(env.streaming_root / env.keys.soundbank, SECOND_SFX_BNK_ID)


def test_volume_overwrites_an_existing_music_track_volume_in_place(tmp_path):
    env = music_env(tmp_path, "zzz", loop_track_props={0x00: -1.0})
    install_loop_mod(env, make_wem(24), volume_enabled=True, volume_db=-7.5)

    run_apply(env)

    assert read_music_track(modded_music_bank(env), LOOP_TRACK_ID)[2] == {0x00: -7.5}
    assert (env.persistent_root / env.keys.soundbank).stat().st_size == (env.streaming_root / env.keys.soundbank).stat().st_size


def test_volume_disabled_keeps_the_music_track_as_is(tmp_path):
    env = music_env(tmp_path, "zzz")
    install_loop_mod(env, make_wem(25), volume_enabled=False, volume_db=-6.0)

    run_apply(env)

    assert not (env.persistent_root / env.keys.soundbank).exists()


@pytest.mark.parametrize("game_id", GAME_IDS)
def test_volume_never_touches_a_non_music_sound(tmp_path, game_id):
    env = music_env(tmp_path, game_id)
    install_enabled(env, "Sfx Volume", {env.keys.soundbank: [mod_entry(env.work_dir / "sfx", EMBEDDED_WEM_ID, make_wem(26), bnk_id=SFX_BNK_ID, volume_enabled=True, volume_db=-6.0)]})

    run_apply(env)
    modded_sfx_bank = bank_bytes(env.persistent_root / env.keys.soundbank, SFX_BNK_ID)

    assert hirc_chunk(modded_sfx_bank) == hirc_chunk(bank_bytes(env.streaming_root / env.keys.soundbank, SFX_BNK_ID))
    assert modded_music_bank(env) == bank_bytes(env.streaming_root / env.keys.soundbank, MUSIC_BNK_ID)
    assert bank_wems(env.persistent_root / env.keys.soundbank, SFX_BNK_ID)[EMBEDDED_WEM_ID] == make_wem(26)


@pytest.mark.parametrize("game_id", GAME_IDS)
def test_hirc_post_steps_stack_on_the_rebuilt_soundbank_overlay(tmp_path, game_id):
    env = music_env(tmp_path, game_id)
    install_enabled(env, "Combined", {
        env.keys.soundbank: [mod_entry(env.work_dir / "sfx", EMBEDDED_WEM_ID, make_wem(27), bnk_id=SFX_BNK_ID)],
        env.keys.music: [mod_entry(env.work_dir / "music", LOOP_WEM_ID, make_wem(28), loop_point_mode="manual", loop_point_manual_ms=80000, volume_enabled=True, volume_db=-3.0)],
    })

    run_apply(env)
    music_track = read_music_track(modded_music_bank(env), LOOP_TRACK_ID)

    assert bank_wems(env.persistent_root / env.keys.soundbank, SFX_BNK_ID)[EMBEDDED_WEM_ID] == make_wem(27)
    assert music_track[1:] == ([(LOOP_WEM_ID, INTRO_MS, 80000.0)], {0x00: -3.0})


@pytest.mark.parametrize("game_id", GAME_IDS)
def test_reapplying_a_music_mod_does_not_stack_the_retiming(tmp_path, game_id):
    env = music_env(tmp_path, game_id)
    install_loop_mod(env, make_pcm_wem(90000), loop_point_mode="auto", volume_enabled=True, volume_db=-6.0)

    run_apply(env)
    first_music_bank = modded_music_bank(env)
    run_apply(env)

    assert modded_music_bank(env) == first_music_bank


@pytest.mark.parametrize(("game_id", "has_manifest"), [
    ("zzz", True),
    ("genshin", True),
    pytest.param("hsr", False, marks=pytest.mark.xfail(strict=True, reason="bug: pcks rewritten by the loop/volume post step are not recorded in mod_tracker, so without a manifest the overlay survives disabling")),
])
def test_disabling_a_loop_mod_removes_every_overlay_it_wrote(tmp_path, game_id, has_manifest):
    env = music_env(tmp_path, game_id)
    if has_manifest:
        write_pkg_version_manifest(env)
    install_loop_mod(env, make_wem(29), loop_point_mode="manual", loop_point_manual_ms=90000)
    run_apply(env)

    env.manager.set_all_mods_enabled(False)
    run_apply(env)

    assert list(env.persistent_root.rglob("*.pck")) == []


def test_collectors_read_loop_and_volume_defaults_as_off():
    handler = get_browser_handler_class("zzz")(bridge=None)
    replacements = {"Full/Streamed_SFX_1.pck": {
        "1": {"file_type": "wem", "wem_path": "missing.wem"},
        "1003|2": {"file_type": "bnk", "loop_point_mode": "manual", "loop_point_manual_ms": 500},
        "3": {"file_type": "wem", "loop_point_mode": "manual", "loop_point_manual_ms": 0, "wem_path": "missing.wem"},
        "4": {"file_type": "wem", "volume_enabled": True, "volume_db": 99},
        "5": {"file_type": "wem", "loop_point_mode": "bogus", "wem_path": "missing.wem"},
        "6": {"file_type": "hirc", "loop_point_mode": "manual", "loop_point_manual_ms": 500, "volume_enabled": True},
    }}

    assert handler._collect_loop_patch_targets(replacements) == {2: 500.0}
    assert handler._collect_volume_patch_targets(replacements) == {4: 24.0}


def test_genshin_collects_audio_settings_only_from_music_pcks():
    handler = get_browser_handler_class("genshin")(bridge=None)
    replacements = {
        "Music0.pck": {"1": {"file_type": "wem", "loop_point_mode": "manual", "loop_point_manual_ms": 500, "volume_enabled": True, "volume_db": -2.0}},
        "Banks0.pck": {"1003|2": {"file_type": "bnk", "loop_point_mode": "manual", "loop_point_manual_ms": 500, "volume_enabled": True, "volume_db": -2.0}},
    }

    assert handler._collect_loop_patch_targets(replacements) == {1: 500.0}
    assert handler._collect_volume_patch_targets(replacements) == {1: -2.0}
