import json

import pytest

from bridge_helpers import (
    game_lock_free,
    holding_game_lock,
    make_zzz_install,
    music_track,
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
    record_signal,
    wait_until,
)

MUSIC_BANK_ID = 500
TRACK_ID = 9001
TRACK_SOURCE_ID = 7001
NEW_WEM_ID = 123456


@pytest.fixture
def sandbox(monkeypatch):
    return sandbox_app_environment(monkeypatch)


def activate(game_id):
    import src.core.app_config as app_config

    app_config.switch_active_game(game_id)


@pytest.fixture
def genshin_install(tmp_path):
    music_bank = build_bnk(MUSIC_BANK_ID, hirc_objects=[music_track(TRACK_ID, TRACK_SOURCE_ID)])
    install = make_game_install(tmp_path / "games", "genshin", {
        "Banks0.pck": build_pck(banks=[(MUSIC_BANK_ID, 0, music_bank), (501, 0, build_bnk(501, {31: make_wem(31)}))]),
        "Music0.pck": build_pck(sounds=[(TRACK_SOURCE_ID, 0, make_wem(TRACK_SOURCE_ID, 128))]),
        "Streamed0.pck": build_pck(sounds=[(32, 0, make_wem(32, 128))]),
    })
    configure_game_in_settings(install)
    activate("genshin")
    return install


@pytest.fixture
def editor(qapp, sandbox):
    from src.gui.backend.hirc_editor_bridge import HircEditorBridge

    bridge = HircEditorBridge()
    yield bridge
    bridge._workers.shutdown()
    assert wait_until(game_lock_free)


def new_wem_file(tmp_path, wem_id=NEW_WEM_ID):
    path = tmp_path / "audio" / f"{wem_id}.wem"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(make_wem(wem_id, 96))
    return path


def stage_new_wem(editor, tmp_path, pck_name, wem_id=NEW_WEM_ID):
    staged = record_signal(editor.wemStaged)
    editor.stageAddWem(pck_name, wem_id, str(new_wem_file(tmp_path, wem_id)), 0)
    assert wait_until(lambda: staged and game_lock_free())
    return staged


def stage_track_loop(editor, loop_ms="1500"):
    remaps = json.dumps([{"slot": "src", "index": 0, "old_source_id": TRACK_SOURCE_ID, "new_source_id": NEW_WEM_ID}])
    editor.stageTrackEdits("Banks0.pck", MUSIC_BANK_ID, TRACK_ID, remaps, loop_ms, "")


def test_refresh_without_a_configured_game_emits_an_empty_list(editor):
    lists = record_signal(editor.bnkListReady)
    status = record_signal(editor.statusUpdate)

    editor.refreshBnkList()

    assert lists == [([],)]
    assert status == [("No game audio directory configured for the active game.",)]


def test_refresh_lists_only_banks_with_music_objects(editor, genshin_install):
    lists = record_signal(editor.bnkListReady)

    editor.refreshBnkList()

    assert wait_until(lambda: lists)
    [entry] = lists[0][0]
    assert (entry["pck_name"], entry["bnk_id"], entry["music_object_count"], entry["is_override"]) == ("Banks0.pck", MUSIC_BANK_ID, 1, False)
    assert str(TRACK_SOURCE_ID) in entry["search"].split()
    assert str(TRACK_ID) in entry["search"].split()


def test_load_bnk_hirc_emits_the_music_objects(editor, genshin_install):
    ready = record_signal(editor.bnkHircReady)

    editor.loadBnkHirc("Banks0.pck", MUSIC_BANK_ID)

    [(pck_name, bnk_id, objects)] = ready
    assert (pck_name, bnk_id) == ("Banks0.pck", MUSIC_BANK_ID)
    assert [(obj["obj_id"], obj["type"], [source["source_id"] for source in obj["sources"]]) for obj in objects] == [
        (TRACK_ID, "MusicTrack", [TRACK_SOURCE_ID])
    ]


def test_load_bnk_hirc_of_a_missing_bank_reports_an_error(editor, genshin_install):
    errors = record_signal(editor.errorOccurred)

    editor.loadBnkHirc("Banks0.pck", 424242)

    assert [error[0] for error in errors] == ["HIRC Load Error"]


def test_list_music_pcks_offers_only_music_media_pcks(editor, genshin_install):
    lists = record_signal(editor.musicPckListReady)

    editor.listMusicPcks()

    assert [entry["pck_name"] for entry in lists[0][0]] == ["Music0.pck"]


def test_list_music_pcks_offers_zzz_pcks_from_the_full_folder(editor, tmp_path):
    install = make_zzz_install(tmp_path / "games")
    configure_game_in_settings(install)
    activate("zzz")
    lists = record_signal(editor.musicPckListReady)

    editor.listMusicPcks()

    assert [(entry["pck_name"], entry["pck_path"]) for entry in lists[0][0]] == [
        ("Streamed_SFX_1.pck", str(install.streaming_root / "Full" / "Streamed_SFX_1.pck"))
    ]


def test_track_edits_are_staged_persisted_and_dropped_when_emptied(editor, genshin_install):
    from src.core.config_manager import get_game_hirc_draft_file

    counts = record_signal(editor.draftChangesCount)
    changes = record_signal(editor.draftChangesReady)

    stage_track_loop(editor)
    editor.showDraftChanges()

    assert counts == [(1,)]
    [row] = changes[-1][0]
    assert (row["kind"], row["bnk_id"], row["track_obj_id"], row["loop_ms"]) == ("track", MUSIC_BANK_ID, TRACK_ID, "1500")
    assert row["current_sources"] == [f"Source[0]: {TRACK_SOURCE_ID}"]
    assert len(json.loads(get_game_hirc_draft_file("genshin").read_text(encoding="utf-8"))["track_patches"]) == 1

    editor.setDraftRemapTarget("Banks0.pck", MUSIC_BANK_ID, TRACK_ID, "src", 0, "")
    editor.setDraftTrackLoop("Banks0.pck", MUSIC_BANK_ID, TRACK_ID, "")

    assert counts[-1] == (0,)
    assert changes[-1] == ([],)


@pytest.mark.parametrize(
    ("wem_id", "audio_exists", "expected_error"),
    [
        ("abc", True, "Invalid WEM id."),
        (2 ** 32, True, f"WEM id {2 ** 32} out of u32 range."),
        (NEW_WEM_ID, False, "Audio file not found"),
    ],
)
def test_stage_add_wem_validates_its_arguments(editor, genshin_install, tmp_path, wem_id, audio_exists, expected_error):
    errors = record_signal(editor.errorOccurred)
    audio_path = new_wem_file(tmp_path) if audio_exists else tmp_path / "missing.wem"

    editor.stageAddWem("Music0.pck", wem_id, str(audio_path), 0)

    assert errors[0][0] == "Add WEM"
    assert errors[0][1].startswith(expected_error)
    assert game_lock_free()


def test_stage_add_wem_rejects_an_id_already_in_the_game(editor, genshin_install, tmp_path):
    errors = record_signal(editor.errorOccurred)
    counts = record_signal(editor.draftChangesCount)

    editor.stageAddWem("Music0.pck", TRACK_SOURCE_ID, str(new_wem_file(tmp_path, TRACK_SOURCE_ID)), 0)

    assert wait_until(lambda: errors and game_lock_free())
    assert "already exists in the game's original files" in errors[0][1]
    assert counts == []


def test_stage_add_wem_copies_a_wem_into_the_draft(editor, genshin_install, tmp_path):
    from src.core.config_manager import get_game_hirc_draft_wem_dir

    counts = record_signal(editor.draftChangesCount)

    staged = stage_new_wem(editor, tmp_path, "Music0.pck")

    assert staged == [("Music0.pck", NEW_WEM_ID, f"{NEW_WEM_ID}.wem")]
    assert counts == [(1,)]
    assert (get_game_hirc_draft_wem_dir("genshin") / f"{NEW_WEM_ID}.wem").read_bytes() == make_wem(NEW_WEM_ID, 96)


def test_apply_with_an_empty_draft_reports_nothing_staged(editor, genshin_install):
    errors = record_signal(editor.errorOccurred)

    editor.applyDraftLive()

    assert errors == [("Apply", "Nothing staged to apply.")]


def test_apply_draft_adds_the_wem_to_the_persistent_overlay(editor, genshin_install, tmp_path):
    stage_new_wem(editor, tmp_path, "Music0.pck")
    applied = record_signal(editor.draftApplied)

    editor.applyDraftLive()

    assert wait_until(lambda: applied and game_lock_free())
    assert applied == [(True, "Draft applied to the live game.")]
    assert read_pck_wem(genshin_install.persistent_root / "Music0.pck", NEW_WEM_ID) == make_wem(NEW_WEM_ID, 96)
    assert read_pck_wem(genshin_install.streaming_root / "Music0.pck", TRACK_SOURCE_ID) == make_wem(TRACK_SOURCE_ID, 128)


def test_apply_draft_adds_the_wem_to_a_zzz_music_pck(editor, tmp_path):
    install = make_zzz_install(tmp_path / "games")
    configure_game_in_settings(install)
    activate("zzz")
    stage_new_wem(editor, tmp_path, "Streamed_SFX_1.pck")
    applied = record_signal(editor.draftApplied)

    editor.applyDraftLive()

    assert wait_until(lambda: applied and game_lock_free())
    assert applied[0][0] is True
    assert read_pck_wem(install.persistent_root / "Full/Streamed_SFX_1.pck", NEW_WEM_ID) == make_wem(NEW_WEM_ID, 96)


def test_draft_exports_as_a_hirc_mod_and_imports_back(editor, genshin_install, tmp_path, sandbox):
    from src.mods.package_manager import ModPackageManager, is_hirc_mod

    stage_new_wem(editor, tmp_path, "Music0.pck")
    stage_track_loop(editor)
    sandbox.dialog_answers["save_file"] = str(tmp_path / "export" / "Hirc Mod")
    (tmp_path / "export").mkdir()
    exported = record_signal(editor.modExported)

    editor.createModPackage("Hirc Mod", "Tester", "", "desc", "")

    assert wait_until(lambda: exported and game_lock_free())
    assert exported == [(True, "Hirc Mod.giar")]
    package = tmp_path / "export" / "Hirc Mod.giar"
    metadata = ModPackageManager(game_id="genshin").validate_mod_package(package)
    assert is_hirc_mod(metadata)
    assert metadata["version"] == "1.0.0"

    counts = record_signal(editor.draftChangesCount)
    editor.resetDraft()
    editor.importModForEditing(str(package))

    assert wait_until(lambda: counts and counts[-1] == (2,) and game_lock_free())


def test_importing_a_plain_replacement_mod_is_refused(editor, genshin_install, tmp_path):
    package = write_mod_package(tmp_path / "Plain.giar", "Plain", {"Music0.pck": {TRACK_SOURCE_ID: make_wem(1)}})
    errors = record_signal(editor.errorOccurred)

    editor.importModForEditing(str(package))

    assert [error[0] for error in errors] == ["Wrong mod type"]
    assert game_lock_free()


def test_the_draft_is_kept_per_game(editor, genshin_install):
    stage_track_loop(editor)
    counts = record_signal(editor.draftChangesCount)

    activate("hsr")
    editor.refreshDraft()
    activate("genshin")
    editor.refreshDraft()

    assert counts == [(0,), (1,)]


DRAFT_SLOTS = {
    "stageTrackEdits": lambda editor, audio: stage_track_loop(editor, "2000"),
    "stageAddWem": lambda editor, audio: editor.stageAddWem("Music0.pck", NEW_WEM_ID + 1, str(audio), 0),
    "setDraftTrackLoop": lambda editor, audio: editor.setDraftTrackLoop("Banks0.pck", MUSIC_BANK_ID, TRACK_ID, ""),
    "setDraftTrackVolume": lambda editor, audio: editor.setDraftTrackVolume("Banks0.pck", MUSIC_BANK_ID, TRACK_ID, "3"),
    "removeDraftTrackPatch": lambda editor, audio: editor.removeDraftTrackPatch("Banks0.pck", MUSIC_BANK_ID, TRACK_ID),
    "removeDraftMediaAdd": lambda editor, audio: editor.removeDraftMediaAdd("Music0.pck", NEW_WEM_ID),
    "resetDraft": lambda editor, audio: editor.resetDraft(),
    "applyDraftLive": lambda editor, audio: editor.applyDraftLive(),
    "createModPackage": lambda editor, audio: editor.createModPackage("Mod", "Tester", "1.0.0", "", ""),
}


@pytest.mark.parametrize("slot_name", sorted(DRAFT_SLOTS))
def test_draft_slots_refuse_while_another_write_holds_the_game_lock(editor, genshin_install, tmp_path, slot_name):
    from src.core.config_manager import get_game_hirc_draft_file

    stage_new_wem(editor, tmp_path, "Music0.pck")
    stage_track_loop(editor)
    draft_before = get_game_hirc_draft_file("genshin").read_text(encoding="utf-8")
    errors = record_signal(editor.errorOccurred)
    audio_path = new_wem_file(tmp_path, NEW_WEM_ID + 1)

    with holding_game_lock():
        DRAFT_SLOTS[slot_name](editor, audio_path)
        assert [error[0] for error in errors] == ["Operation In Progress"]

    assert get_game_hirc_draft_file("genshin").read_text(encoding="utf-8") == draft_before
    assert not (genshin_install.persistent_root / "Music0.pck").exists()
