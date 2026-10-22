"""Steam's downloaded voice packs must work through the normal apply pipeline."""

import copy
import json
from types import SimpleNamespace

import pytest

from helpers import build_bnk, build_pck, configure_game_in_settings, make_game_install, make_wem
from mod_builders import (
    VOICE_BNK_ID,
    VOICE_LANG_ID,
    VOICE_LANGUAGES,
    VOICE_WEM_ID,
    GameKeys,
    bank_wems,
    install_enabled,
    mod_entry,
    run_apply,
    standard_audio_files,
)
from overlay_builders import write_pkg_version, xxh64_tag
from src.mods.package_manager import ModApplicationError, ModPackageManager
from src.mods.persistent_manager import PersistentModManager
from src.mods.steam_audio import prepare_steam_audio


def audio_entry(rel, content):
    return {
        "remoteName": f"Audio/Windows/{rel}",
        "md5": xxh64_tag(content),
        "fileSize": len(content),
        "isPatch": False,
        "tags": [3, 4],
    }


def write_catalog(path, catalog):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(catalog, indent=2), encoding="utf-8")


@pytest.fixture
def steam_voice_env(tmp_path):
    keys = GameKeys("zzz")
    audio = standard_audio_files("zzz")
    sfx = {rel: content for rel, content in audio.items() if "/En/" not in rel}
    original_voice = audio[keys.voice_soundbank]
    install = make_game_install(
        tmp_path / "game", "zzz", streaming_files=sfx,
        persistent_files={keys.voice_soundbank: original_voice},
    )
    configure_game_in_settings(install)
    write_pkg_version(install, sfx)
    base_path = install.data_dir / "StreamingAssets" / "audio_version"
    persist_path = install.data_dir / "Persistent" / "audio_version_persist"
    sfx_entries = [audio_entry(rel, content) for rel, content in sfx.items()]
    # These opaque catalogue fields belong to the game and must survive intact.
    base_catalog = {
        "remoteParentDir": "Audio/Windows",
        "files": sfx_entries,
        "basePackages": ["Full"],
        "baseOnlyPackages": ["unchanged-package"],
        "baseOnlyTitles": {"sentinel": "unchanged"},
    }
    persist_catalog = {
        "remoteParentDir": "Audio/Windows",
        "files": [audio_entry(keys.voice_soundbank, original_voice)],
        "basePackages": [],
        "baseOnlyPackages": [],
        "baseOnlyTitles": [],
    }
    write_catalog(base_path, base_catalog)
    write_catalog(persist_path, persist_catalog)
    tracker = PersistentModManager(game_id="zzz")
    manager = ModPackageManager(persistent_mod_manager=tracker, game_id="zzz")
    return SimpleNamespace(
        **vars(install), keys=keys, manager=manager, tracker=tracker,
        work_dir=tmp_path / "work", original_voice=original_voice,
        original_sfx=sfx, base_path=base_path, persist_path=persist_path,
        base_catalog=copy.deepcopy(base_catalog), persist_catalog=persist_catalog,
    )


def install_voice_mod(env):
    replacement = make_wem(900, payload_size=112)
    uid = install_enabled(env, "Steam Voice", {
        env.keys.voice_soundbank: [mod_entry(
            env.work_dir / "src", VOICE_WEM_ID, replacement,
            bnk_id=VOICE_BNK_ID, lang_id=VOICE_LANG_ID,
        )],
    })
    return uid, replacement


def acknowledge_prepared_catalog(env):
    """Simulate the game's one-time catalogue registration, never XXAR writes."""
    prepare_steam_audio("zzz", env.streaming_root, env.persistent_root)
    marker = env.data_dir / "Persistent" / "base_version_hash"
    marker.write_text("res_silence_data_" + xxh64_tag(env.base_path.read_bytes()), encoding="utf-8")


def registered_voice_entry(env):
    catalog = json.loads(env.base_path.read_text(encoding="utf-8"))
    remote_name = f"Audio/Windows/{env.keys.voice_soundbank}"
    entries = [entry for entry in catalog["files"] if entry["remoteName"] == remote_name]
    assert len(entries) == 1
    return entries[0]


def assert_baseline_preserved(env, original_voice):
    assert (env.streaming_root / env.keys.voice_soundbank).read_bytes() == original_voice
    assert registered_voice_entry(env) == audio_entry(env.keys.voice_soundbank, original_voice)
    catalog = json.loads(env.base_path.read_text(encoding="utf-8"))
    assert {key: value for key, value in catalog.items() if key != "files"} == {
        key: value for key, value in env.base_catalog.items() if key != "files"
    }
    assert [entry for entry in catalog["files"] if "/En/" not in entry["remoteName"]] == env.base_catalog["files"]
    for rel, content in env.original_sfx.items():
        assert (env.streaming_root / rel).read_bytes() == content


def test_normal_apply_reuses_prepared_steam_voice_and_pristine_base(steam_voice_env):
    env = steam_voice_env
    _, replacement = install_voice_mod(env)
    persistent_catalog_before = env.persist_path.read_bytes()
    acknowledge_prepared_catalog(env)

    summary = run_apply(env)

    assert summary == {"applied_pcks": 1, "skipped_missing_original": []}
    assert bank_wems(env.persistent_root / env.keys.voice_soundbank, VOICE_BNK_ID)[VOICE_WEM_ID] == replacement
    assert_baseline_preserved(env, env.original_voice)
    assert env.persist_path.read_bytes() == persistent_catalog_before
    overlay_before = (env.persistent_root / env.keys.voice_soundbank).read_bytes()
    base_catalog_before = env.base_path.read_bytes()

    # Reapply must rebuild from the verified original, never adopt its previous output.
    assert run_apply(env) == summary

    assert (env.persistent_root / env.keys.voice_soundbank).read_bytes() == overlay_before
    assert_baseline_preserved(env, env.original_voice)
    assert env.base_path.read_bytes() == base_catalog_before
    assert env.persist_path.read_bytes() == persistent_catalog_before


@pytest.mark.parametrize("old_marker", [None, "res_silence_data_0"])
def test_fresh_headless_apply_prepares_catalog_then_waits_for_game_registration(steam_voice_env, old_marker):
    env = steam_voice_env
    _, replacement = install_voice_mod(env)
    persistent_catalog_before = env.persist_path.read_bytes()
    if old_marker is not None:
        (env.data_dir / "Persistent/base_version_hash").write_text(old_marker, encoding="utf-8")

    with pytest.raises(ModApplicationError, match="Start ZZZ once"):
        env.manager.apply_mods(env.streaming_root, env.persistent_root)

    # The first Apply can prepare originals/catalogue, but cannot replace any
    # voice with a mod before the game has processed the new base catalogue.
    assert_baseline_preserved(env, env.original_voice)
    assert (env.persistent_root / env.keys.voice_soundbank).read_bytes() == env.original_voice
    assert env.tracker.get_all_replacements() == {}
    assert env.persist_path.read_bytes() == persistent_catalog_before
    if old_marker is None:
        assert not (env.data_dir / "Persistent/base_version_hash").exists()
    else:
        assert (env.data_dir / "Persistent/base_version_hash").read_text() == old_marker

    acknowledge_prepared_catalog(env)

    summary = env.manager.apply_mods(env.streaming_root, env.persistent_root)

    assert summary == {"applied_pcks": 1, "skipped_missing_original": []}
    assert_baseline_preserved(env, env.original_voice)
    assert bank_wems(env.persistent_root / env.keys.voice_soundbank, VOICE_BNK_ID)[VOICE_WEM_ID] == replacement
    assert env.persist_path.read_bytes() == persistent_catalog_before


def test_disabling_steam_voice_removes_overlay_but_keeps_registered_original(steam_voice_env):
    env = steam_voice_env
    uid, _ = install_voice_mod(env)
    persistent_catalog_before = env.persist_path.read_bytes()
    acknowledge_prepared_catalog(env)
    run_apply(env)

    env.manager.set_mod_enabled(uid, False)
    run_apply(env)

    assert not (env.persistent_root / env.keys.voice_soundbank).exists()
    assert env.tracker.get_all_replacements() == {}
    assert_baseline_preserved(env, env.original_voice)
    assert env.persist_path.read_bytes() == persistent_catalog_before


def test_game_update_refreshes_steam_original_before_rebuilding_enabled_mod(steam_voice_env):
    env = steam_voice_env
    _, replacement = install_voice_mod(env)
    acknowledge_prepared_catalog(env)
    run_apply(env)
    original_catalog = env.persist_path.read_bytes()
    newer_voice = build_pck(
        banks=[(VOICE_BNK_ID, VOICE_LANG_ID, build_bnk(
            VOICE_BNK_ID, {VOICE_WEM_ID: make_wem(901, payload_size=176)},
            language_id=VOICE_LANG_ID,
        ))],
        languages=VOICE_LANGUAGES,
    )
    (env.persistent_root / env.keys.voice_soundbank).write_bytes(newer_voice)
    env.persist_catalog["files"] = [audio_entry(env.keys.voice_soundbank, newer_voice)]
    write_catalog(env.persist_path, env.persist_catalog)
    updated_catalog = env.persist_path.read_bytes()
    assert original_catalog != updated_catalog

    with pytest.raises(ModApplicationError, match="Start ZZZ once"):
        run_apply(env)
    assert_baseline_preserved(env, newer_voice)
    assert not (env.persistent_root / env.keys.voice_soundbank).exists()
    assert env.persist_path.read_bytes() == updated_catalog

    acknowledge_prepared_catalog(env)
    summary = run_apply(env)

    assert summary == {"applied_pcks": 1, "skipped_missing_original": []}
    assert_baseline_preserved(env, newer_voice)
    assert bank_wems(env.persistent_root / env.keys.voice_soundbank, VOICE_BNK_ID)[VOICE_WEM_ID] == replacement
    assert env.persist_path.read_bytes() == updated_catalog
