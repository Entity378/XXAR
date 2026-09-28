import json

import pytest

from helpers import build_bnk, build_pck, make_wem
from mod_builders import (
    EMBEDDED_WEM_ID,
    GAME_IDS,
    LAYOUTS,
    SECOND_SFX_BNK_ID,
    SECOND_SFX_BNK_WEM_ID,
    SFX_BNK_ID,
    SHARED_WEM_ID,
    STREAMED_WEM_ID,
    VOICE_BNK_ID,
    VOICE_LANG_ID,
    VOICE_LANGUAGES,
    VOICE_WEM_ID,
    GameKeys,
    bank_bytes,
    bank_wems,
    install_enabled,
    loose_wem,
    make_mod_env,
    mod_entry,
    pck_entries,
    run_apply,
    snapshot_files,
)
from src.core.config_manager import get_game_mod_tracker_file
from src.mods.package_manager import ModApplicationError

ALIAS_FIRST_WEM_ID = 300001
ALIAS_SECOND_WEM_ID = 300002
DUPLICATED_WEM_ID = 160001


def persistent_pcks(env):
    return sorted(path.relative_to(env.persistent_root).as_posix() for path in env.persistent_root.rglob("*.pck"))


def install_three_target_mod(env, name="Three Targets"):
    return install_enabled(env, name, {
        env.keys.soundbank: [mod_entry(env.work_dir / name, EMBEDDED_WEM_ID, make_wem(100), bnk_id=SFX_BNK_ID)],
        env.keys.streamed: [mod_entry(env.work_dir / name, STREAMED_WEM_ID, make_wem(101))],
        env.keys.voice_soundbank: [mod_entry(env.work_dir / name, VOICE_WEM_ID, make_wem(102), bnk_id=VOICE_BNK_ID, lang_id=VOICE_LANG_ID)],
    })


@pytest.mark.parametrize("game_id", GAME_IDS)
def test_apply_writes_each_replacement_into_its_mirrored_overlay(tmp_path, game_id):
    env = make_mod_env(tmp_path, game_id)
    streaming_before = snapshot_files(env.streaming_root)
    install_three_target_mod(env)

    apply_summary = run_apply(env)

    assert apply_summary == {"applied_pcks": 3, "skipped_missing_original": []}
    assert persistent_pcks(env) == sorted([env.keys.soundbank, env.keys.streamed, env.keys.voice_soundbank])
    assert bank_wems(env.persistent_root / env.keys.soundbank, SFX_BNK_ID)[EMBEDDED_WEM_ID] == make_wem(100)
    assert loose_wem(env.persistent_root / env.keys.streamed, STREAMED_WEM_ID) == make_wem(101)
    assert bank_wems(env.persistent_root / env.keys.voice_soundbank, VOICE_BNK_ID)[VOICE_WEM_ID] == make_wem(102)
    assert snapshot_files(env.streaming_root) == streaming_before


@pytest.mark.parametrize("game_id", GAME_IDS)
def test_apply_leaves_every_untouched_entry_byte_identical(tmp_path, game_id):
    env = make_mod_env(tmp_path, game_id)
    install_three_target_mod(env)

    run_apply(env)
    original_soundbank = pck_entries(env.streaming_root / env.keys.soundbank)
    modded_soundbank = pck_entries(env.persistent_root / env.keys.soundbank)
    original_streamed = pck_entries(env.streaming_root / env.keys.streamed)
    modded_streamed = pck_entries(env.persistent_root / env.keys.streamed)

    assert modded_soundbank.keys() == original_soundbank.keys()
    assert modded_soundbank[("banks", SECOND_SFX_BNK_ID, 0)] == original_soundbank[("banks", SECOND_SFX_BNK_ID, 0)]
    assert bank_wems(env.persistent_root / env.keys.soundbank, SFX_BNK_ID)[SHARED_WEM_ID] == bank_wems(env.streaming_root / env.keys.soundbank, SFX_BNK_ID)[SHARED_WEM_ID]
    assert modded_streamed.keys() == original_streamed.keys()
    assert {key: data for key, data in modded_streamed.items() if key[1] != STREAMED_WEM_ID} == {key: data for key, data in original_streamed.items() if key[1] != STREAMED_WEM_ID}


@pytest.mark.parametrize("game_id", GAME_IDS)
def test_a_soundbank_replacement_also_patches_the_streamed_duplicate(tmp_path, game_id):
    env = make_mod_env(tmp_path, game_id)
    install_enabled(env, "Shared", {env.keys.soundbank: [mod_entry(env.work_dir / "src", SHARED_WEM_ID, make_wem(103), bnk_id=SFX_BNK_ID)]})

    run_apply(env)

    assert bank_wems(env.persistent_root / env.keys.soundbank, SFX_BNK_ID)[SHARED_WEM_ID] == make_wem(103)
    assert loose_wem(env.persistent_root / env.keys.streamed, SHARED_WEM_ID) == make_wem(103)
    assert loose_wem(env.persistent_root / env.keys.streamed, STREAMED_WEM_ID) == loose_wem(env.streaming_root / env.keys.streamed, STREAMED_WEM_ID)


@pytest.mark.parametrize("game_id", GAME_IDS)
def test_a_streamed_replacement_leaves_the_soundbank_untouched(tmp_path, game_id):
    env = make_mod_env(tmp_path, game_id)
    install_enabled(env, "Streamed Only", {env.keys.streamed: [mod_entry(env.work_dir / "src", SHARED_WEM_ID, make_wem(104))]})

    run_apply(env)

    assert persistent_pcks(env) == [env.keys.streamed]
    assert loose_wem(env.persistent_root / env.keys.streamed, SHARED_WEM_ID) == make_wem(104)


@pytest.mark.parametrize("game_id", GAME_IDS)
def test_apply_snapshots_the_resolved_mods_into_mod_tracker_json(tmp_path, game_id):
    env = make_mod_env(tmp_path, game_id)
    installed_mod_uuid = install_enabled(env, "Tracked", {
        env.keys.soundbank: [mod_entry(env.work_dir / "src", EMBEDDED_WEM_ID, make_wem(105), bnk_id=SFX_BNK_ID)],
        env.keys.streamed: [mod_entry(env.work_dir / "src", STREAMED_WEM_ID, make_wem(106), loop_point_mode="manual", loop_point_manual_ms=1234, volume_enabled=True, volume_db=-4.5)],
    })

    run_apply(env)
    tracker_on_disk = json.loads(get_game_mod_tracker_file(game_id).read_text())
    mod_dir = env.manager.mods_dir / installed_mod_uuid
    embedded_entry = next(iter(tracker_on_disk[env.keys.soundbank].values()))
    streamed_entry = next(iter(tracker_on_disk[env.keys.streamed].values()))

    assert set(tracker_on_disk) == {env.keys.soundbank, env.keys.streamed}
    assert {key: embedded_entry[key] for key in ("wem_path", "file_type", "lang_id", "bnk_id", "source")} == {
        "wem_path": str(mod_dir / "wem_files" / "1001" / "110001.wem"), "file_type": "bnk", "lang_id": 0, "bnk_id": SFX_BNK_ID, "source": "mod_manager",
    }
    assert not any(key in embedded_entry for key in ("loop_point_mode", "loop_point_manual_ms", "volume_enabled", "volume_db"))
    assert {key: streamed_entry[key] for key in ("loop_point_mode", "loop_point_manual_ms", "volume_enabled", "volume_db", "bnk_id")} == {
        "loop_point_mode": "manual", "loop_point_manual_ms": 1234, "volume_enabled": True, "volume_db": -4.5, "bnk_id": None,
    }


@pytest.mark.xfail(strict=True, reason="bug: the mod_tracker snapshot keys entries by bare wem id, so two bnks sharing a wem id collapse")
def test_tracker_snapshot_keeps_two_bnks_that_embed_the_same_wem(tmp_path):
    keys = GameKeys("zzz")
    soundbank = build_pck(banks=[
        (SFX_BNK_ID, 0, build_bnk(SFX_BNK_ID, {DUPLICATED_WEM_ID: make_wem(60)})),
        (SECOND_SFX_BNK_ID, 0, build_bnk(SECOND_SFX_BNK_ID, {DUPLICATED_WEM_ID: make_wem(60)})),
    ])
    env = make_mod_env(tmp_path, "zzz", streaming_files={keys.soundbank: soundbank})
    install_enabled(env, "Duplicated", {env.keys.soundbank: [
        mod_entry(env.work_dir / "src", DUPLICATED_WEM_ID, make_wem(61), bnk_id=SFX_BNK_ID),
        mod_entry(env.work_dir / "src", DUPLICATED_WEM_ID, make_wem(62), bnk_id=SECOND_SFX_BNK_ID),
    ]})

    run_apply(env)

    assert bank_wems(env.persistent_root / keys.soundbank, SFX_BNK_ID)[DUPLICATED_WEM_ID] == make_wem(61)
    assert bank_wems(env.persistent_root / keys.soundbank, SECOND_SFX_BNK_ID)[DUPLICATED_WEM_ID] == make_wem(62)
    assert sorted(info["bnk_id"] for info in env.tracker.get_all_replacements()[keys.soundbank].values()) == [SFX_BNK_ID, SECOND_SFX_BNK_ID]


@pytest.mark.parametrize("game_id", GAME_IDS)
def test_disabling_every_mod_and_applying_restores_the_original_audio(tmp_path, game_id):
    env = make_mod_env(tmp_path, game_id)
    streaming_before = snapshot_files(env.streaming_root)
    install_three_target_mod(env)
    run_apply(env)

    env.manager.set_all_mods_enabled(False)
    run_apply(env)

    assert persistent_pcks(env) == []
    assert snapshot_files(env.streaming_root) == streaming_before
    assert env.tracker.get_all_replacements() == {}


@pytest.mark.parametrize("game_id", GAME_IDS)
def test_applying_twice_is_idempotent(tmp_path, game_id):
    env = make_mod_env(tmp_path, game_id)
    streaming_before = snapshot_files(env.streaming_root)
    install_three_target_mod(env)

    run_apply(env)
    first_overlays = snapshot_files(env.persistent_root)
    run_apply(env)

    assert snapshot_files(env.persistent_root) == first_overlays
    assert snapshot_files(env.streaming_root) == streaming_before


@pytest.mark.parametrize("game_id", GAME_IDS)
def test_removing_one_mod_drops_only_its_overlay(tmp_path, game_id):
    env = make_mod_env(tmp_path, game_id)
    removed_mod_uuid = install_enabled(env, "Removed", {env.keys.soundbank: [mod_entry(env.work_dir / "a", EMBEDDED_WEM_ID, make_wem(107), bnk_id=SFX_BNK_ID)]})
    install_enabled(env, "Kept", {env.keys.streamed: [mod_entry(env.work_dir / "b", STREAMED_WEM_ID, make_wem(108))]})
    run_apply(env)

    env.manager.remove_mod(removed_mod_uuid)
    run_apply(env)

    assert persistent_pcks(env) == [env.keys.streamed]
    assert loose_wem(env.persistent_root / env.keys.streamed, STREAMED_WEM_ID) == make_wem(108)


@pytest.mark.parametrize("game_id", GAME_IDS)
def test_the_later_mod_in_load_order_wins_the_game_file(tmp_path, game_id):
    env = make_mod_env(tmp_path, game_id)
    earlier_mod_uuid = install_enabled(env, "Earlier", {env.keys.soundbank: [mod_entry(env.work_dir / "a", EMBEDDED_WEM_ID, make_wem(110), bnk_id=SFX_BNK_ID)]})
    later_mod_uuid = install_enabled(env, "Later", {env.keys.soundbank: [mod_entry(env.work_dir / "b", EMBEDDED_WEM_ID, make_wem(111), bnk_id=SFX_BNK_ID)]})

    run_apply(env)
    wem_with_default_order = bank_wems(env.persistent_root / env.keys.soundbank, SFX_BNK_ID)[EMBEDDED_WEM_ID]
    env.manager.update_load_order([later_mod_uuid, earlier_mod_uuid])
    run_apply(env)
    wem_after_reorder = bank_wems(env.persistent_root / env.keys.soundbank, SFX_BNK_ID)[EMBEDDED_WEM_ID]

    assert wem_with_default_order == make_wem(111)
    assert wem_after_reorder == make_wem(110)


def test_a_conflict_preference_beats_the_load_order(tmp_path):
    env = make_mod_env(tmp_path, "zzz")
    install_enabled(env, "Earlier", {env.keys.soundbank: [mod_entry(env.work_dir / "a", EMBEDDED_WEM_ID, make_wem(110), bnk_id=SFX_BNK_ID)]})
    install_enabled(env, "Later", {env.keys.soundbank: [mod_entry(env.work_dir / "b", EMBEDDED_WEM_ID, make_wem(111), bnk_id=SFX_BNK_ID)]})

    run_apply(env, conflict_preferences={f"{env.keys.soundbank}:{SFX_BNK_ID}|{EMBEDDED_WEM_ID}": "Earlier"})

    assert bank_wems(env.persistent_root / env.keys.soundbank, SFX_BNK_ID)[EMBEDDED_WEM_ID] == make_wem(110)


def alias_cases():
    for game_id in GAME_IDS:
        yield pytest.param(game_id, "sfx", id=f"{game_id}-sfx")
        yield pytest.param(game_id, "voice", id=f"{game_id}-voice")


@pytest.mark.parametrize(("game_id", "pck_kind"), list(alias_cases()))
def test_bare_and_folder_qualified_keys_for_one_pck_both_land(tmp_path, game_id, pck_kind):
    layout = LAYOUTS[game_id]
    keys = GameKeys(game_id)
    qualified_key, bare_key, lang_id = {
        "sfx": (keys.streamed, layout.streamed, 0),
        "voice": (keys.voice_streamed, layout.voice_streamed, VOICE_LANG_ID),
    }[pck_kind]
    target_pck = build_pck(sounds=[(ALIAS_FIRST_WEM_ID, lang_id, make_wem(30)), (ALIAS_SECOND_WEM_ID, lang_id, make_wem(31))], languages=VOICE_LANGUAGES)
    env = make_mod_env(tmp_path, game_id, streaming_files={qualified_key: target_pck})
    install_enabled(env, "Bare Key", {bare_key: [mod_entry(env.work_dir / "a", ALIAS_FIRST_WEM_ID, make_wem(40), lang_id=lang_id)]})
    install_enabled(env, "Qualified Key", {qualified_key: [mod_entry(env.work_dir / "b", ALIAS_SECOND_WEM_ID, make_wem(41), lang_id=lang_id)]})

    run_apply(env)

    assert loose_wem(env.persistent_root / qualified_key, ALIAS_FIRST_WEM_ID) == make_wem(40)
    assert loose_wem(env.persistent_root / qualified_key, ALIAS_SECOND_WEM_ID) == make_wem(41)


def test_apply_skips_a_pck_whose_original_is_missing(tmp_path):
    env = make_mod_env(tmp_path, "zzz")
    install_enabled(env, "Stale Target", {
        "Full/Streamed_SFX_99.pck": [mod_entry(env.work_dir / "src", 999001, make_wem(112))],
        env.keys.streamed: [mod_entry(env.work_dir / "src", STREAMED_WEM_ID, make_wem(113))],
    })

    apply_summary = run_apply(env)

    assert apply_summary == {"applied_pcks": 1, "skipped_missing_original": ["Full/Streamed_SFX_99.pck"]}
    assert persistent_pcks(env) == [env.keys.streamed]


def test_apply_skips_a_replacement_whose_wem_file_vanished(tmp_path):
    env = make_mod_env(tmp_path, "zzz")
    installed_mod_uuid = install_enabled(env, "Missing Audio", {env.keys.soundbank: [
        mod_entry(env.work_dir / "src", EMBEDDED_WEM_ID, make_wem(114), bnk_id=SFX_BNK_ID),
        mod_entry(env.work_dir / "src", SHARED_WEM_ID, make_wem(115), bnk_id=SFX_BNK_ID),
    ]})
    (env.manager.mods_dir / installed_mod_uuid / "wem_files" / "1001" / f"{SHARED_WEM_ID}.wem").unlink()

    run_apply(env)
    modded_wems = bank_wems(env.persistent_root / env.keys.soundbank, SFX_BNK_ID)

    assert modded_wems[EMBEDDED_WEM_ID] == make_wem(114)
    assert modded_wems[SHARED_WEM_ID] == bank_wems(env.streaming_root / env.keys.soundbank, SFX_BNK_ID)[SHARED_WEM_ID]


def test_apply_raises_when_the_game_audio_dir_is_missing(tmp_path):
    env = make_mod_env(tmp_path, "zzz")

    with pytest.raises(ModApplicationError, match="Game audio directory not found"):
        env.manager.apply_mods(env.streaming_root / "missing", env.persistent_root)


def test_apply_reports_progress_through_the_callback(tmp_path):
    env = make_mod_env(tmp_path, "zzz")
    install_three_target_mod(env)
    progress_messages = []

    env.manager.apply_mods(env.streaming_root, env.persistent_root, progress_callback=lambda message, current, total: progress_messages.append((message, current, total)))

    assert progress_messages[0] == ("Resolving mod conflicts...", 0, 1)
    assert progress_messages[-1] == ("Applied 3 PCK(s) successfully", 3, 3)


def test_a_new_bank_version_is_rebuilt_from_streaming_assets(tmp_path):
    env = make_mod_env(tmp_path, "zzz")
    install_enabled(env, "Embedded", {env.keys.soundbank: [mod_entry(env.work_dir / "src", EMBEDDED_WEM_ID, make_wem(116), bnk_id=SFX_BNK_ID)]})
    run_apply(env)
    updated_second_sfx_bnk = build_bnk(SECOND_SFX_BNK_ID, {SECOND_SFX_BNK_WEM_ID: make_wem(333)})
    (env.streaming_root / env.keys.soundbank).write_bytes(build_pck(banks=[
        (SFX_BNK_ID, 0, bank_bytes(env.streaming_root / env.keys.soundbank, SFX_BNK_ID)),
        (SECOND_SFX_BNK_ID, 0, updated_second_sfx_bnk),
    ]))

    run_apply(env)

    assert bank_bytes(env.persistent_root / env.keys.soundbank, SECOND_SFX_BNK_ID) == updated_second_sfx_bnk
    assert bank_wems(env.persistent_root / env.keys.soundbank, SFX_BNK_ID)[EMBEDDED_WEM_ID] == make_wem(116)

