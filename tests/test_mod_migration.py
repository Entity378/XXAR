import json
from pathlib import Path

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
    install_enabled,
    loose_wem,
    make_mod_env,
    mod_entry,
    package_mod,
    run_apply,
)
from src.mods.package_manager import ModPackageManager

MOVED_WEM_ID = 150001
MOVED_VOICE_WEM_ID = 270001
NEW_VOICE_BNK_ID = 2002


def moved_wem_env(tmp_path, game_id):
    keys = GameKeys(game_id)
    streamed_with_moved_wem = build_pck(sounds=[(STREAMED_WEM_ID, 0, make_wem(4)), (MOVED_WEM_ID, 0, make_wem(9))])
    return make_mod_env(tmp_path, game_id, streaming_files={keys.streamed: streamed_with_moved_wem})


def installed_metadata(env, installed_mod_uuid):
    return json.loads((env.manager.mods_dir / installed_mod_uuid / "metadata.json").read_text())


def replacements_by_pck_name(metadata):
    return {Path(pck_key).name: bnk_buckets for pck_key, bnk_buckets in metadata["replacements"].items()}


@pytest.mark.parametrize("game_id", GAME_IDS)
def test_install_relinks_a_wem_that_moved_to_a_streamed_pck(tmp_path, game_id):
    env = moved_wem_env(tmp_path, game_id)
    package_path = package_mod(env, "Stale Target", {env.keys.soundbank: [mod_entry(env.work_dir / "src", MOVED_WEM_ID, make_wem(100), bnk_id=SFX_BNK_ID)]})
    package_before = package_path.read_bytes()

    installed_mod_uuid = env.manager.install_mod(package_path, game_audio_dir=env.streaming_root)["uuid"]
    migrated_metadata = installed_metadata(env, installed_mod_uuid)

    assert replacements_by_pck_name(migrated_metadata) == {
        LAYOUTS[game_id].streamed: {"direct": {str(MOVED_WEM_ID): {"wem_file": f"wem_files/1001/{MOVED_WEM_ID}.wem", "sound_name": "", "lang_id": 0, "file_type": "wem"}}},
    }
    assert ModPackageManager(game_id=game_id).mod_config["installed_mods"][installed_mod_uuid]["metadata"]["replacements"] == migrated_metadata["replacements"]
    assert package_path.read_bytes() == package_before


@pytest.mark.parametrize("game_id", GAME_IDS)
def test_a_relinked_mod_applies_to_the_new_location(tmp_path, game_id):
    env = moved_wem_env(tmp_path, game_id)
    installed_mod_uuid = env.manager.install_mod(
        package_mod(env, "Stale Target", {env.keys.soundbank: [mod_entry(env.work_dir / "src", MOVED_WEM_ID, make_wem(100), bnk_id=SFX_BNK_ID)]}),
        game_audio_dir=env.streaming_root,
    )["uuid"]
    env.manager.set_mod_enabled(installed_mod_uuid, True)

    run_apply(env)

    assert loose_wem(env.persistent_root / env.keys.streamed, MOVED_WEM_ID) == make_wem(100)
    assert not (env.persistent_root / env.keys.soundbank).exists()


def test_install_without_a_game_dir_keeps_the_metadata_as_packaged(tmp_path):
    env = moved_wem_env(tmp_path, "zzz")
    package_path = package_mod(env, "Stale Target", {env.keys.soundbank: [mod_entry(env.work_dir / "src", MOVED_WEM_ID, make_wem(100), bnk_id=SFX_BNK_ID)]})

    installed_mod_uuid = env.manager.install_mod(package_path)["uuid"]

    assert list(installed_metadata(env, installed_mod_uuid)["replacements"]) == [env.keys.soundbank]


@pytest.mark.parametrize("game_id", GAME_IDS)
def test_apply_relinks_mods_broken_by_a_game_update(tmp_path, game_id):
    env = make_mod_env(tmp_path, game_id)
    installed_mod_uuid = install_enabled(env, "Pre Update", {env.keys.soundbank: [mod_entry(env.work_dir / "src", EMBEDDED_WEM_ID, make_wem(101), bnk_id=SFX_BNK_ID)]})
    (env.streaming_root / env.keys.soundbank).write_bytes(build_pck(banks=[
        (SFX_BNK_ID, 0, build_bnk(SFX_BNK_ID, {SHARED_WEM_ID: make_wem(2, 48)})),
        (SECOND_SFX_BNK_ID, 0, build_bnk(SECOND_SFX_BNK_ID, {SECOND_SFX_BNK_WEM_ID: make_wem(3)})),
    ]))
    (env.streaming_root / env.keys.streamed).write_bytes(build_pck(sounds=[(STREAMED_WEM_ID, 0, make_wem(4)), (EMBEDDED_WEM_ID, 0, make_wem(1))]))

    run_apply(env)
    reloaded_metadata = ModPackageManager(game_id=game_id).mod_config["installed_mods"][installed_mod_uuid]["metadata"]

    assert loose_wem(env.persistent_root / env.keys.streamed, EMBEDDED_WEM_ID) == make_wem(101)
    assert list(replacements_by_pck_name(reloaded_metadata)) == [LAYOUTS[game_id].streamed]
    assert installed_metadata(env, installed_mod_uuid)["replacements"] == reloaded_metadata["replacements"]


def test_migrating_a_healthy_library_writes_nothing(tmp_path):
    env = make_mod_env(tmp_path, "zzz")
    installed_mod_uuid = env.manager.install_mod(
        package_mod(env, "Healthy", {env.keys.soundbank: [mod_entry(env.work_dir / "src", EMBEDDED_WEM_ID, make_wem(102), bnk_id=SFX_BNK_ID)]}),
        game_audio_dir=env.streaming_root,
    )["uuid"]
    metadata_file = env.manager.mods_dir / installed_mod_uuid / "metadata.json"
    watched_files = (metadata_file, env.manager.config_path)
    before = [(path.read_bytes(), path.stat().st_mtime_ns) for path in watched_files]

    env.manager.migrate_installed_mods(env.streaming_root)

    assert [(path.read_bytes(), path.stat().st_mtime_ns) for path in watched_files] == before


def test_an_unlocatable_wem_is_left_unchanged(tmp_path):
    env = make_mod_env(tmp_path, "zzz")
    installed_mod_uuid = env.manager.install_mod(
        package_mod(env, "Lost", {env.keys.soundbank: [mod_entry(env.work_dir / "src", 999999, make_wem(103), bnk_id=SFX_BNK_ID)]}),
        game_audio_dir=env.streaming_root,
    )["uuid"]

    assert installed_metadata(env, installed_mod_uuid)["replacements"] == {env.keys.soundbank: {"1001.bnk": {"999999": {"wem_file": "wem_files/1001/999999.wem", "sound_name": "", "lang_id": 0, "file_type": "bnk"}}}}


def test_relink_keeps_audio_settings_and_add_entries(tmp_path):
    env = moved_wem_env(tmp_path, "zzz")
    installed_mod_uuid = env.manager.install_mod(
        package_mod(env, "Settings", {env.keys.soundbank: [
            mod_entry(env.work_dir / "src", MOVED_WEM_ID, make_wem(104), bnk_id=SFX_BNK_ID, loop_point_mode="manual", loop_point_manual_ms=4000, volume_enabled=True, volume_db=-2.0),
            mod_entry(env.work_dir / "src", 4000000001, make_wem(105), bnk_id=SFX_BNK_ID, is_add=True),
        ]}),
        game_audio_dir=env.streaming_root,
    )["uuid"]

    migrated = replacements_by_pck_name(installed_metadata(env, installed_mod_uuid))

    assert migrated[LAYOUTS["zzz"].streamed]["direct"][str(MOVED_WEM_ID)] == {
        "wem_file": f"wem_files/1001/{MOVED_WEM_ID}.wem", "sound_name": "", "lang_id": 0, "file_type": "wem",
        "loop_point_mode": "manual", "loop_point_manual_ms": 4000, "volume_enabled": True, "volume_db": -2.0,
    }
    assert migrated[LAYOUTS["zzz"].soundbank]["1001.bnk"]["4000000001"]["is_add"] is True


def voice_relink_cases():
    for game_id in GAME_IDS:
        marks = []
        if game_id == "zzz":
            marks = [pytest.mark.xfail(strict=True, reason="bug: mod_relinker scans only SoundBank_SFX_* for embedded wems, so ZZZ voice mods never relink")]
        yield pytest.param(game_id, marks=marks)


@pytest.mark.parametrize("game_id", list(voice_relink_cases()))
def test_install_relinks_a_voice_wem_that_moved_to_another_voice_bank(tmp_path, game_id):
    keys = GameKeys(game_id)
    updated_voice_soundbank = build_pck(banks=[
        (VOICE_BNK_ID, VOICE_LANG_ID, build_bnk(VOICE_BNK_ID, {VOICE_WEM_ID: make_wem(6)}, language_id=VOICE_LANG_ID)),
        (NEW_VOICE_BNK_ID, VOICE_LANG_ID, build_bnk(NEW_VOICE_BNK_ID, {MOVED_VOICE_WEM_ID: make_wem(10)}, language_id=VOICE_LANG_ID)),
    ], languages=VOICE_LANGUAGES)
    env = make_mod_env(tmp_path, game_id, streaming_files={keys.voice_soundbank: updated_voice_soundbank})
    package_path = package_mod(env, "Voice", {keys.voice_soundbank: [mod_entry(env.work_dir / "src", MOVED_VOICE_WEM_ID, make_wem(106), bnk_id=VOICE_BNK_ID, lang_id=VOICE_LANG_ID)]})

    installed_mod_uuid = env.manager.install_mod(package_path, game_audio_dir=env.streaming_root)["uuid"]

    assert replacements_by_pck_name(installed_metadata(env, installed_mod_uuid)) == {
        LAYOUTS[game_id].voice_soundbank: {f"{NEW_VOICE_BNK_ID}.bnk": {str(MOVED_VOICE_WEM_ID): {"wem_file": f"wem_files/{VOICE_BNK_ID}/{MOVED_VOICE_WEM_ID}.wem", "sound_name": "", "lang_id": VOICE_LANG_ID, "file_type": "bnk"}}},
    }
