from pathlib import Path

import pytest

from bridge_helpers import (
    EMBEDDED_WEM_IDS,
    SFX_BANK_ID,
    SOUNDBANK_PCK,
    STREAMED_PCK,
    STREAMED_WEM_ID,
    game_lock_free,
    holding_game_lock,
    make_genshin_install,
    make_zzz_install,
    read_pck_wem,
    sandbox_app_environment,
    write_mod_package,
)
from helpers import (
    build_bnk,
    build_pck,
    configure_game_in_settings,
    make_game_install,
    make_wem,
    read_settings,
    record_signal,
    wait_until,
)

JP_BANK_ID = 200
JP_WEM_ID = 51
PATCH_ONLY_WEM_ID = 13


@pytest.fixture
def sandbox(monkeypatch):
    return sandbox_app_environment(monkeypatch)


@pytest.fixture
def browser(qapp, sandbox):
    from src.gui.backend.audio_browser_bridge import AudioBrowserBridge

    bridge = AudioBrowserBridge()
    yield bridge
    bridge.cleanup()
    assert wait_until(game_lock_free)


@pytest.fixture
def zzz_install(tmp_path):
    install = make_zzz_install(tmp_path / "games")
    configure_game_in_settings(install)
    return install


def load_browser(browser):
    browser.loadFromSettings()
    assert wait_until(lambda: browser.index_ready)


def last_items(tree_emissions):
    return tree_emissions[-1][0]


def item_names(items):
    return [item["fileName"] for item in items]


def replacement_wem(tmp_path, seed=7):
    path = tmp_path / "replacement" / f"custom_{seed}.wem"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(make_wem(seed, 200))
    return path


def stage_replacement(browser, sandbox, wem_path, item_id, pck_path, parent_bnk=""):
    counts = record_signal(browser.changesCountUpdated)
    sandbox.dialog_answers["open_file"] = str(wem_path)
    browser.replaceWithCustomAudio(item_id, "WEM", str(pck_path), True, parent_bnk)
    assert wait_until(lambda: counts and game_lock_free())
    return counts


def run_write(browser, slot, done_message):
    status = record_signal(browser.statusUpdate)
    slot()
    assert wait_until(lambda: any(done_message in message[0] for message in status) and game_lock_free())
    return status


def test_load_from_settings_emits_tabs_and_the_first_tab_tree(browser, zzz_install):
    directories = record_signal(browser.gameDirectoryReady)
    tabs = record_signal(browser.languageTabsReady)
    trees = record_signal(browser.treeItemsReady)

    load_browser(browser)

    assert directories == [(str(zzz_install.data_dir),)]
    assert tabs == [(["SFX/Music (2)"],)]
    items = last_items(trees)
    assert item_names(items) == ["SoundBank_SFX_1.pck", "Streamed_SFX_1.pck"]
    assert {item["itemType"] for item in items} == {"PCK"}
    assert items[0]["pckPath"] == str(zzz_install.streaming_root / SOUNDBANK_PCK)


def test_expanding_a_pck_then_its_bnk_lists_the_embedded_wems(browser, zzz_install):
    load_browser(browser)
    trees = record_signal(browser.treeItemsReady)

    browser.expandPckItem(str(zzz_install.streaming_root / SOUNDBANK_PCK))
    bank_items = last_items(trees)
    browser.onTreeItemExpanded(str(SFX_BANK_ID), "BNK")
    wem_items = last_items(trees)

    assert [(item["fileName"], item["itemType"], item["depth"]) for item in bank_items] == [(f"{SFX_BANK_ID}.bnk", "BNK", 1)]
    assert [(item["itemId"], item["parentBnk"], item["depth"]) for item in wem_items] == [
        (str(wem_id), str(SFX_BANK_ID), 2) for wem_id in EMBEDDED_WEM_IDS
    ]


def test_expanding_a_streamed_pck_lists_its_wems(browser, zzz_install):
    load_browser(browser)
    trees = record_signal(browser.treeItemsReady)

    browser.expandPckItem(str(zzz_install.streaming_root / STREAMED_PCK))

    assert [(item["itemId"], item["itemType"]) for item in last_items(trees)] == [(str(STREAMED_WEM_ID), "WEM")]


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        (str(EMBEDDED_WEM_IDS[0]), [("wem_embedded", "SoundBank_SFX_1.pck", str(SFX_BANK_ID))]),
        (str(STREAMED_WEM_ID), [("wem", "Streamed_SFX_1.pck", "")]),
        (str(SFX_BANK_ID), [("bnk", "SoundBank_SFX_1.pck", "")]),
    ],
)
def test_search_finds_ids_in_the_current_tab(browser, zzz_install, query, expected):
    load_browser(browser)
    results = record_signal(browser.searchResultsReady)

    browser.search(query)

    assert len(results) == 1
    assert results[0][0] == query
    assert [(match["type"], Path(match["pckPath"]).name, match["bnkId"]) for match in results[0][1]] == expected


def test_search_without_matches_only_reports_status(browser, zzz_install):
    load_browser(browser)
    results = record_signal(browser.searchResultsReady)
    status = record_signal(browser.statusUpdate)

    browser.search("987654")

    assert results == []
    assert status[-1] == ("No files found matching '987654'",)


def test_navigate_to_search_result_expands_and_points_qml_at_the_item(browser, zzz_install):
    load_browser(browser)
    navigations = record_signal(browser.navigateToItem)
    soundbank_path = str(zzz_install.streaming_root / SOUNDBANK_PCK)

    browser.navigateToSearchResult(str(EMBEDDED_WEM_IDS[1]), "wem_embedded", soundbank_path, str(SFX_BANK_ID))

    assert wait_until(lambda: navigations, timeout=3)
    assert navigations == [(str(EMBEDDED_WEM_IDS[1]), soundbank_path, str(SFX_BANK_ID))]


def test_missing_streamed_pcks_raise_an_alert(browser, tmp_path):
    sfx_bank = build_bnk(SFX_BANK_ID, {11: make_wem(11)})
    install = make_game_install(tmp_path / "games", "zzz", {SOUNDBANK_PCK: build_pck(banks=[(SFX_BANK_ID, 0, sfx_bank)])})
    configure_game_in_settings(install)
    alerts = record_signal(browser.alertDialogRequested)

    load_browser(browser)

    assert wait_until(lambda: alerts, timeout=5)
    assert alerts[0][0] == "Missing Streaming Audio Files"


@pytest.fixture
def staged_browser(browser, zzz_install, tmp_path, sandbox):
    load_browser(browser)
    streamed_path = zzz_install.streaming_root / STREAMED_PCK
    browser.expandPckItem(str(streamed_path))
    wem_path = replacement_wem(tmp_path)
    counts = stage_replacement(browser, sandbox, wem_path, str(STREAMED_WEM_ID), streamed_path)
    assert counts[-1] == (1,)
    browser.staged_wem_path = wem_path
    return browser


def test_replace_stages_a_change_that_show_changes_lists(staged_browser):
    changes = record_signal(staged_browser.changesReady)

    staged_browser.showChanges()

    assert len(changes) == 1
    [change] = changes[0][0]
    assert (change["fileId"], change["pckFile"], change["itemType"], change["wemPath"]) == (
        str(STREAMED_WEM_ID), STREAMED_PCK, "wem", str(staged_browser.staged_wem_path)
    )
    assert change["loopPointEditable"] is True


def test_apply_writes_the_overlay_and_reset_removes_it(staged_browser, zzz_install):
    overlay = zzz_install.persistent_root / STREAMED_PCK
    original = (zzz_install.streaming_root / STREAMED_PCK).read_bytes()

    run_write(staged_browser, staged_browser.applyAllChanges, "Successfully applied 1 change(s)!")

    assert read_pck_wem(overlay, STREAMED_WEM_ID) == staged_browser.staged_wem_path.read_bytes()
    assert (zzz_install.streaming_root / STREAMED_PCK).read_bytes() == original

    counts = record_signal(staged_browser.changesCountUpdated)
    run_write(staged_browser, staged_browser.resetAllChanges, "All changes reset")

    assert wait_until(lambda: counts and counts[-1] == (0,))
    assert not overlay.exists()
    assert (zzz_install.streaming_root / STREAMED_PCK).read_bytes() == original
    assert staged_browser.mod_manager.get_all_replacements() == {}


def test_remove_last_change_closes_the_changes_dialog(staged_browser):
    counts = record_signal(staged_browser.changesCountUpdated)
    closed = record_signal(staged_browser.closeChangesDialog)

    staged_browser.removeChange(STREAMED_PCK, str(STREAMED_WEM_ID))

    assert counts == [(0,)]
    assert closed == [()]


def test_change_audio_settings_are_normalized_into_the_tracker(staged_browser):
    tracker_key = str(STREAMED_WEM_ID)

    staged_browser.setChangeLoopPointMode(STREAMED_PCK, tracker_key, "manual")
    staged_browser.setChangeLoopPointManualMs(STREAMED_PCK, tracker_key, "01:02.5")
    staged_browser.setChangeVolumeDb(STREAMED_PCK, tracker_key, "30")
    staged_browser.setChangeVolumeEnabled(STREAMED_PCK, tracker_key, False)

    entry = staged_browser.mod_manager.get_all_replacements()[STREAMED_PCK][tracker_key]
    assert (entry["loop_point_mode"], entry["loop_point_manual_ms"], entry["volume_db"], entry["volume_enabled"]) == ("manual", 62500, 24.0, False)


def test_invalid_loop_duration_is_rejected_with_a_status(staged_browser):
    status = record_signal(staged_browser.statusUpdate)

    staged_browser.setChangeLoopPointManualMs(STREAMED_PCK, str(STREAMED_WEM_ID), "abc")

    assert status == [("Invalid loop duration format. Use mm:ss.SSS.",)]


def test_create_mod_package_exports_the_staged_changes(staged_browser, tmp_path, sandbox):
    from src.mods.package_manager import ModPackageManager

    sandbox.dialog_answers["save_file"] = str(tmp_path / "export" / "Browser Mod")
    (tmp_path / "export").mkdir()

    run_write(staged_browser, lambda: staged_browser.createModPackage("Browser Mod", "Tester", "1.0.0", "desc", ""), "Mod package created")

    metadata = ModPackageManager(game_id="zzz").validate_mod_package(tmp_path / "export" / "Browser Mod.zzar")
    assert metadata["name"] == "Browser Mod"
    assert list(metadata["replacements"]) == [STREAMED_PCK]


def test_import_mod_for_editing_replaces_the_staged_changes(browser, zzz_install, tmp_path):
    load_browser(browser)
    package = write_mod_package(tmp_path / "Imported.zzar", "Imported", {STREAMED_PCK: {STREAMED_WEM_ID: make_wem(9, 256)}})
    success = record_signal(browser.successDialogRequested)
    counts = record_signal(browser.changesCountUpdated)

    browser.importModForEditing(str(package))

    assert wait_until(lambda: success and counts and game_lock_free())
    assert success[0][0] == "Mod Imported for Editing"
    assert counts[-1] == (1,)
    assert list(browser.mod_manager.get_all_replacements()) == [STREAMED_PCK]
    assert browser._imported_mod_metadata["name"] == "Imported"


def test_mute_without_wwise_asks_for_wwise_and_stages_nothing(browser, zzz_install):
    load_browser(browser)
    browser.expandPckItem(str(zzz_install.streaming_root / STREAMED_PCK))
    wwise_errors = record_signal(browser.wwiseErrorDialog)

    browser.muteAudio(str(STREAMED_WEM_ID), "WEM", str(zzz_install.streaming_root / STREAMED_PCK), "")

    assert [error[0] for error in wwise_errors] == ["Wwise Required"]
    assert browser.mod_manager.get_all_replacements() == {}


def test_apply_without_a_game_directory_reports_nothing_to_apply(browser):
    errors = record_signal(browser.errorOccurred)

    browser.applyAllChanges()

    assert errors == [("No Changes", "No changes to apply.")]
    assert game_lock_free()


WRITE_SLOTS = {
    "scanLanguageFolders": lambda browser, install: browser.scanLanguageFolders(str(install.data_dir)),
    "replaceWithCustomAudio": lambda browser, install: browser.replaceWithCustomAudio(str(STREAMED_WEM_ID), "WEM", str(install.streaming_root / STREAMED_PCK), True, ""),
    "muteAudio": lambda browser, install: browser.muteAudio(str(STREAMED_WEM_ID), "WEM", str(install.streaming_root / STREAMED_PCK), ""),
    "applyAllChanges": lambda browser, install: browser.applyAllChanges(),
    "resetAllChanges": lambda browser, install: browser.resetAllChanges(),
    "removeChange": lambda browser, install: browser.removeChange(STREAMED_PCK, str(STREAMED_WEM_ID)),
    "importModForEditing": lambda browser, install: browser.importModForEditing("unused.zzar"),
    "createModPackage": lambda browser, install: browser.createModPackage("Mod", "Tester", "1.0.0", "", ""),
    "setChangeVolumeEnabled": lambda browser, install: browser.setChangeVolumeEnabled(STREAMED_PCK, str(STREAMED_WEM_ID), False),
}


@pytest.mark.parametrize("slot_name", sorted(WRITE_SLOTS))
def test_write_slots_refuse_while_another_write_holds_the_game_lock(staged_browser, zzz_install, slot_name):
    tracker_before = dict(staged_browser.mod_manager.get_all_replacements()[STREAMED_PCK][str(STREAMED_WEM_ID)])
    alerts = record_signal(staged_browser.alertDialogRequested)

    with holding_game_lock():
        WRITE_SLOTS[slot_name](staged_browser, zzz_install)
        assert [alert[0] for alert in alerts] == ["Operation In Progress"]

    assert staged_browser.mod_manager.get_all_replacements()[STREAMED_PCK][str(STREAMED_WEM_ID)] == tracker_before
    assert not (zzz_install.persistent_root / STREAMED_PCK).exists()


def test_game_switch_reloads_the_browser_for_the_new_game(staged_browser, tmp_path):
    import src.core.app_config as app_config

    genshin = make_genshin_install(tmp_path / "games")
    configure_game_in_settings(genshin)
    app_config.switch_active_game("genshin")
    merge = record_signal(staged_browser.mergeWemChanged)
    tabs = record_signal(staged_browser.languageTabsReady)
    trees = record_signal(staged_browser.treeItemsReady)
    counts = record_signal(staged_browser.changesCountUpdated)

    load_browser(staged_browser)

    assert staged_browser.game_mode == "genshin"
    assert merge[-1] == (False,)
    assert tabs == [(["SFX/Music (2)", "English (1)"],)]
    assert item_names(last_items(trees)) == ["Banks0.pck", "Streamed0.pck"]
    assert counts[0] == (0,)
    assert staged_browser.mod_manager.get_all_replacements() == {}


@pytest.mark.parametrize(
    ("slot_name", "value", "settings_key", "signal_name"),
    [
        ("setHideEmptyBnk", False, "hide_empty_bnk", "hideEmptyBnkChanged"),
        ("setNormalizeAudio", False, "normalize_audio", "normalizeAudioChanged"),
        ("setNormalizeTargetLufs", -14, "normalize_target_lufs", "normalizeTargetLufsChanged"),
    ],
)
def test_browser_options_persist_to_settings(browser, zzz_install, slot_name, value, settings_key, signal_name):
    emissions = record_signal(getattr(browser, signal_name))

    getattr(browser, slot_name)(value)

    assert emissions == [(value,)]
    assert read_settings()[settings_key] == value


@pytest.fixture
def persistent_only_language_install(tmp_path):
    jp_bank = build_bnk(JP_BANK_ID, {JP_WEM_ID: make_wem(JP_WEM_ID)})
    install = make_zzz_install(
        tmp_path / "games",
        persistent_files={"Full/Jp/SoundBank_Jp.pck": build_pck(banks=[(JP_BANK_ID, 0, jp_bank)])},
    )
    configure_game_in_settings(install)
    return install


def test_a_tab_scanned_from_persistent_repoints_when_the_promoted_copy_exists(browser, persistent_only_language_install):
    install = persistent_only_language_install
    tabs = record_signal(browser.languageTabsReady)
    load_browser(browser)
    assert tabs == [(["SFX/Music (2)", "Japanese (1)"],)]
    trees = record_signal(browser.treeItemsReady)
    browser.onLanguageTabChanged(1)
    assert last_items(trees)[0]["pckPath"] == str(install.persistent_root / "Full/Jp/SoundBank_Jp.pck")

    promoted = install.streaming_root / "Full/Jp/SoundBank_Jp.pck"
    promoted.parent.mkdir(parents=True)
    promoted.write_bytes((install.persistent_root / "Full/Jp/SoundBank_Jp.pck").read_bytes())
    browser.onLanguageTabChanged(0)
    browser.onLanguageTabChanged(1)

    assert last_items(trees)[0]["pckPath"] == str(promoted)


def test_reset_promotes_a_persistent_only_tab_and_reloads_it_from_streaming(browser, persistent_only_language_install):
    install = persistent_only_language_install
    load_browser(browser)
    browser.onLanguageTabChanged(1)
    trees = record_signal(browser.treeItemsReady)

    run_write(browser, browser.resetAllChanges, "All changes reset")

    assert wait_until(lambda: trees)
    assert last_items(trees)[0]["pckPath"] == str(install.streaming_root / "Full/Jp/SoundBank_Jp.pck")
    assert (install.streaming_root / "Full/Jp/SoundBank_Jp.pck").exists()
    assert not (install.persistent_root / "Full/Jp/SoundBank_Jp.pck").exists()


@pytest.fixture
def patch_override_install(tmp_path):
    patch_bank = build_bnk(SFX_BANK_ID, {EMBEDDED_WEM_IDS[0]: make_wem(111), PATCH_ONLY_WEM_ID: make_wem(PATCH_ONLY_WEM_ID)})
    install = make_zzz_install(
        tmp_path / "games",
        persistent_files={"Full/Patch.pck": build_pck(banks=[(SFX_BANK_ID, 0, patch_bank)])},
    )
    configure_game_in_settings(install)
    return install


def expanded_bank_wem_ids(browser, soundbank_path):
    trees = record_signal(browser.treeItemsReady)
    browser.expandPckItem(soundbank_path)
    browser.onTreeItemExpanded(str(SFX_BANK_ID), "BNK")
    return [item["itemId"] for item in last_items(trees)]


def search_locations(browser, query):
    results = record_signal(browser.searchResultsReady)
    browser.search(query)
    return [(match["type"], Path(match["pckPath"]).name, match["bnkId"]) for match in results[0][1]] if results else []


def test_patch_override_wems_stay_reachable_after_apply_nulls_the_live_bank(browser, patch_override_install, tmp_path, sandbox):
    from src.wwise.pck_indexer import PCKIndexer

    install = patch_override_install
    soundbank_path = str(install.streaming_root / SOUNDBANK_PCK)
    load_browser(browser)
    assert expanded_bank_wem_ids(browser, soundbank_path) == ["11", "12", str(PATCH_ONLY_WEM_ID)]
    assert search_locations(browser, str(PATCH_ONLY_WEM_ID)) == [("wem_embedded", "SoundBank_SFX_1.pck", str(SFX_BANK_ID))]

    stage_replacement(browser, sandbox, replacement_wem(tmp_path), str(PATCH_ONLY_WEM_ID), soundbank_path, str(SFX_BANK_ID))
    run_write(browser, browser.applyAllChanges, "Successfully applied 1 change(s)!")
    live_bank_ids = [bank["id"] for bank in PCKIndexer(str(install.persistent_root / "Full/Patch.pck")).build_index()["banks"]]
    assert live_bank_ids == [0]

    load_browser(browser)
    assert expanded_bank_wem_ids(browser, soundbank_path) == ["11", "12", str(PATCH_ONLY_WEM_ID)]
    assert search_locations(browser, str(PATCH_ONLY_WEM_ID)) == [("wem_embedded", "SoundBank_SFX_1.pck", str(SFX_BANK_ID))]
