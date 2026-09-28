import json

import pytest

from bridge_helpers import (
    STREAMED_PCK,
    STREAMED_WEM_ID,
    game_lock_free,
    holding_game_lock,
    make_zzz_install,
    read_pck_wem,
    sandbox_app_environment,
    write_mod_package,
)
from helpers import configure_game_in_settings, make_wem, read_settings, record_signal, wait_until


@pytest.fixture
def sandbox(monkeypatch):
    return sandbox_app_environment(monkeypatch)


@pytest.fixture
def zzz_install(tmp_path):
    install = make_zzz_install(tmp_path / "games")
    configure_game_in_settings(install)
    return install


@pytest.fixture
def bridge(qapp, zzz_install, sandbox):
    from src.gui.backend.mod_manager_bridge import ModManagerBridge

    mod_manager = ModManagerBridge()
    yield mod_manager
    mod_manager._workers.shutdown()
    assert wait_until(game_lock_free)


def install_and_wait(bridge, *package_paths):
    loaded = record_signal(bridge.modsLoaded)
    bridge.installMods([str(path) for path in package_paths])
    assert wait_until(lambda: loaded and game_lock_free())
    return loaded[-1][0]


def mod_package(tmp_path, name, wem_seed, version="1.0.0"):
    return write_mod_package(
        tmp_path / "packages" / f"{name} {version}.zzar",
        name,
        {STREAMED_PCK: {STREAMED_WEM_ID: make_wem(wem_seed, 256)}},
        version=version,
    )


def persistent_streamed_pck(install):
    return install.persistent_root / STREAMED_PCK


def test_bridge_loads_the_configured_game(bridge, zzz_install):
    assert bridge.active_game_id == "zzz"
    assert bridge.game_audio_dir == str(zzz_install.streaming_root)
    assert bridge.persistent_dir == str(zzz_install.persistent_root)
    assert bridge.getModCreationMode() is False


def test_refresh_mods_on_an_empty_library_emits_an_empty_list(bridge):
    loaded = record_signal(bridge.modsLoaded)

    bridge.refreshMods()

    assert loaded == [([],)]


def test_install_lists_the_mod_for_qml(bridge, tmp_path):
    installed = record_signal(bridge.modInstalled)
    success = record_signal(bridge.modInstallSuccess)

    mods = install_and_wait(bridge, mod_package(tmp_path, "Mod A", 1))

    assert [(mod["name"], mod["version"], mod["author"], mod["enabled"]) for mod in mods] == [("Mod A", "1.0.0", "Tester", False)]
    assert installed == [(mods[0]["uuid"],)]
    assert success[0][0] == "Mod Installed Successfully"
    assert set(mods[0]) >= {"uuid", "description", "priority", "thumbnailPath", "installDate", "fromGameBanana"}


def test_installing_a_newer_version_updates_the_mod_in_place(bridge, tmp_path):
    install_and_wait(bridge, mod_package(tmp_path, "Mod A", 1, version="1.0.0"))
    success = record_signal(bridge.modInstallSuccess)

    mods = install_and_wait(bridge, mod_package(tmp_path, "Mod A", 2, version="2.0.0"))

    assert [(mod["name"], mod["version"]) for mod in mods] == [("Mod A", "2.0.0")]
    assert success[0][0] == "Mod Updated Successfully"


def test_installing_an_older_version_is_skipped(bridge, tmp_path):
    install_and_wait(bridge, mod_package(tmp_path, "Mod A", 2, version="2.0.0"))
    errors = record_signal(bridge.errorOccurred)

    mods = install_and_wait(bridge, mod_package(tmp_path, "Mod A", 1, version="1.0.0"))

    assert [(mod["name"], mod["version"]) for mod in mods] == [("Mod A", "2.0.0")]
    assert errors[0][0] == "Installation Skipped"


def test_installing_an_invalid_package_reports_it(bridge, tmp_path):
    broken = tmp_path / "broken.zzar"
    broken.write_bytes(b"not a zip")
    errors = record_signal(bridge.errorOccurred)

    mods = install_and_wait(bridge, broken)

    assert mods == []
    assert errors[0][0] == "Invalid Mod Package"


def test_get_mod_info_exposes_the_replacements(bridge, tmp_path):
    mods = install_and_wait(bridge, mod_package(tmp_path, "Mod A", 1))

    info = bridge.getModInfo(mods[0]["uuid"])

    assert info["name"] == "Mod A"
    assert info["fileCount"] == 1
    assert list(info["replacements"]) == [STREAMED_PCK]
    assert bridge.getModInfo("missing-uuid") is None


def test_enable_and_disable_persist_in_mod_config(bridge, tmp_path):
    mods = install_and_wait(bridge, mod_package(tmp_path, "Mod A", 1))
    uuid = mods[0]["uuid"]

    bridge.setModEnabled(uuid, True)
    assert [mod["enabled"] for mod in bridge.getInstalledMods()] == [True]

    loaded = record_signal(bridge.modsLoaded)
    bridge.disableAllMods()
    assert [mod["enabled"] for mod in loaded[-1][0]] == [False]

    bridge.enableAllMods()
    assert [mod["enabled"] for mod in loaded[-1][0]] == [True]
    config = json.loads((bridge.mod_package_manager.config_path).read_text(encoding="utf-8"))
    assert config["installed_mods"][uuid]["enabled"] is True


def test_remove_mod_deletes_it_from_the_library(bridge, tmp_path):
    mods = install_and_wait(bridge, mod_package(tmp_path, "Mod A", 1), mod_package(tmp_path, "Mod B", 2))
    removed = record_signal(bridge.modRemoved)
    loaded = record_signal(bridge.modsLoaded)

    bridge.removeMod(mods[0]["uuid"])

    assert removed == [(mods[0]["uuid"],)]
    assert [mod["name"] for mod in loaded[-1][0]] == ["Mod B"]
    assert not (bridge.mod_package_manager.mods_dir / mods[0]["uuid"]).exists()

    bridge.removeMods([mods[1]["uuid"]])
    assert loaded[-1][0] == []


def test_apply_writes_the_overlay_and_releases_the_game_lock(bridge, tmp_path, zzz_install):
    new_wem = make_wem(1, 256)
    mods = install_and_wait(bridge, mod_package(tmp_path, "Mod A", 1))
    bridge.setModEnabled(mods[0]["uuid"], True)
    progress = record_signal(bridge.progressUpdate)
    original_streaming = (zzz_install.streaming_root / STREAMED_PCK).read_bytes()

    bridge.applyMods()

    assert wait_until(lambda: ("Mods applied successfully!",) in progress and game_lock_free())
    assert read_pck_wem(persistent_streamed_pck(zzz_install), STREAMED_WEM_ID) == new_wem
    assert (zzz_install.streaming_root / STREAMED_PCK).read_bytes() == original_streaming
    assert bridge.persistent_mod_manager.get_all_replacements()


def test_clear_mods_removes_the_overlay_but_keeps_mods_enabled(bridge, tmp_path, zzz_install):
    mods = install_and_wait(bridge, mod_package(tmp_path, "Mod A", 1))
    bridge.setModEnabled(mods[0]["uuid"], True)
    progress = record_signal(bridge.progressUpdate)
    bridge.applyMods()
    assert wait_until(lambda: ("Mods applied successfully!",) in progress and game_lock_free())
    loaded = record_signal(bridge.modsLoaded)

    bridge.clearMods()

    assert wait_until(lambda: loaded and game_lock_free())
    assert not persistent_streamed_pck(zzz_install).exists()
    assert bridge.persistent_mod_manager.get_all_replacements() == {}
    assert [mod["enabled"] for mod in loaded[-1][0]] == [True]


def test_apply_with_no_game_directory_reports_it(qapp, sandbox):
    from src.gui.backend.mod_manager_bridge import ModManagerBridge

    bridge = ModManagerBridge()
    errors = record_signal(bridge.errorOccurred)

    bridge.applyMods()

    assert errors == [("Missing Directory", "Game audio directory not set. Please configure it in settings first.")]
    assert game_lock_free()


@pytest.fixture
def conflicting_mods(bridge, tmp_path):
    mods = install_and_wait(bridge, mod_package(tmp_path, "Mod A", 1), mod_package(tmp_path, "Mod B", 2))
    bridge.enableAllMods()
    return mods


def test_apply_with_conflicts_asks_qml_before_writing(bridge, conflicting_mods, zzz_install):
    mod_conflicts = record_signal(bridge.modConflictsDetected)

    bridge.applyMods()

    assert len(mod_conflicts) == 1
    summary, file_conflicts = mod_conflicts[0]
    assert summary == [{
        "mods": ["Mod A", "Mod B"],
        "winner_mod": "Mod B",
        "conflict_count": 1,
        "files": [{"pck": STREAMED_PCK, "file_id": str(STREAMED_WEM_ID)}],
    }]
    assert [(conflict["winner_mod"], conflict["loser_mods"]) for conflict in file_conflicts] == [("Mod B", ["Mod A"])]
    assert game_lock_free()
    assert not persistent_streamed_pck(zzz_install).exists()


def test_mod_creation_mode_sends_file_level_conflicts(bridge, conflicting_mods):
    bridge.setModCreationMode(True)
    conflicts = record_signal(bridge.conflictsDetected)

    bridge.applyMods()

    assert [(conflict["pck"], conflict["file_id"], conflict["winner_mod"]) for conflict in conflicts[0][0]] == [
        (STREAMED_PCK, str(STREAMED_WEM_ID), "Mod B")
    ]
    assert read_settings()["mod_creation_mode"] is True


def test_saved_conflict_preference_picks_the_winner_on_apply(bridge, conflicting_mods, zzz_install):
    preference = [{"pck": STREAMED_PCK, "file_id": str(STREAMED_WEM_ID), "winner_mod": "Mod A"}]
    bridge.saveConflictPreferences(json.dumps(preference))
    mod_conflicts = record_signal(bridge.modConflictsDetected)
    progress = record_signal(bridge.progressUpdate)

    bridge.applyMods()
    assert mod_conflicts[0][0][0]["winner_mod"] == "Mod A"
    bridge.applyModsAfterConflictResolution()

    assert wait_until(lambda: ("Mods applied successfully!",) in progress and game_lock_free())
    assert read_pck_wem(persistent_streamed_pck(zzz_install), STREAMED_WEM_ID) == make_wem(1, 256)
    assert read_settings()["conflict_preferences"] == {f"{STREAMED_PCK}:{STREAMED_WEM_ID}": "Mod A"}


MUTATING_SLOTS = {
    "setModEnabled": lambda bridge, uuid: bridge.setModEnabled(uuid, True),
    "enableAllMods": lambda bridge, uuid: bridge.enableAllMods(),
    "disableAllMods": lambda bridge, uuid: bridge.disableAllMods(),
    "removeMod": lambda bridge, uuid: bridge.removeMod(uuid),
    "removeMods": lambda bridge, uuid: bridge.removeMods([uuid]),
    "installMods": lambda bridge, uuid: bridge.installMods(["unused.zzar"]),
    "applyMods": lambda bridge, uuid: bridge.applyMods(),
    "clearMods": lambda bridge, uuid: bridge.clearMods(),
    "exportMod": lambda bridge, uuid: bridge.exportMod(uuid),
}


@pytest.mark.parametrize("slot_name", sorted(MUTATING_SLOTS))
def test_mutating_slots_refuse_while_another_write_holds_the_game_lock(bridge, tmp_path, slot_name):
    mods = install_and_wait(bridge, mod_package(tmp_path, "Mod A", 1))
    uuid = mods[0]["uuid"]
    config_before = bridge.mod_package_manager.config_path.read_text(encoding="utf-8")
    alerts = record_signal(bridge.alertDialogRequested)

    with holding_game_lock():
        MUTATING_SLOTS[slot_name](bridge, uuid)
        assert [alert[0] for alert in alerts] == ["Operation In Progress"]
        assert not bridge._workers._workers

    assert bridge.mod_package_manager.config_path.read_text(encoding="utf-8") == config_before
    assert [mod["uuid"] for mod in bridge.getInstalledMods()] == [uuid]


def test_refresh_during_a_write_is_deferred_until_the_lock_is_released(bridge, tmp_path):
    install_and_wait(bridge, mod_package(tmp_path, "Mod A", 1))
    loaded = record_signal(bridge.modsLoaded)

    with holding_game_lock():
        bridge.refreshMods()
        assert loaded == []

    assert wait_until(lambda: loaded)
    assert [mod["name"] for mod in loaded[0][0]] == ["Mod A"]


def test_export_writes_a_package_that_installs_again(bridge, tmp_path, sandbox):
    mods = install_and_wait(bridge, mod_package(tmp_path, "Mod A", 1))
    export_path = tmp_path / "exported" / "Mod_A_export"
    export_path.parent.mkdir()
    sandbox.dialog_answers["save_file"] = str(export_path)
    progress = record_signal(bridge.progressUpdate)

    bridge.exportMod(mods[0]["uuid"])

    assert wait_until(lambda: ("Mod exported to Mod_A_export.zzar",) in progress and game_lock_free())
    metadata = bridge.mod_package_manager.validate_mod_package(export_path.with_suffix(".zzar"))
    assert metadata["name"] == "Mod A"
    assert list(metadata["replacements"]) == [STREAMED_PCK]
