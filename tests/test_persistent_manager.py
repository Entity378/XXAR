import json

import pytest

from src.core.config_manager import get_game_mod_tracker_file
from src.mods.persistent_manager import PersistentModManager


def read_tracker_file(manager):
    return json.loads(manager.mod_tracker_path.read_text(encoding="utf-8"))


def without_dates(tracker):
    return {pck_key: {key: {field: value for field, value in info.items() if field != "date_modified"} for key, info in entries.items()}
            for pck_key, entries in tracker.items()}


@pytest.mark.parametrize("game_id", ["zzz", "genshin", "hsr"])
def test_tracker_lives_in_the_per_game_mod_library(game_id):
    manager = PersistentModManager(game_id=game_id)
    manager.add_replacement("Full/Streamed_SFX_1.pck", 5001, "mod.wem")

    assert manager.mod_tracker_path == get_game_mod_tracker_file(game_id)
    assert manager.mod_tracker_path.parent.name == "mod_library"
    assert manager.mod_tracker_path.parent.parent.name == game_id
    assert list(read_tracker_file(manager)) == ["Full/Streamed_SFX_1.pck"]


def test_add_replacement_keys_entries_by_bank_and_wem_with_default_audio_settings(tmp_path):
    manager = PersistentModManager(tracker_path=tmp_path / "mod_tracker.json")

    manager.add_replacement("Full/Streamed_SFX_1.pck", 5001, "direct.wem")
    manager.add_replacement("Full/SoundBank_SFX_1.pck", 7001, "embedded.wem", file_type="bnk", lang_id=1, bnk_id=700)
    manager.add_replacement("Full/SoundBank_SFX_1.pck", 7002, "nulled.wem", file_type="bnk", bnk_id=0)

    assert without_dates(read_tracker_file(manager)) == {
        "Full/Streamed_SFX_1.pck": {"5001": {
            "wem_path": "direct.wem", "file_type": "wem", "lang_id": 0, "bnk_id": None,
            "loop_point_mode": "auto", "loop_point_manual_ms": 0, "volume_enabled": True, "volume_db": 0.0,
        }},
        "Full/SoundBank_SFX_1.pck": {
            "700|7001": {
                "wem_path": "embedded.wem", "file_type": "bnk", "lang_id": 1, "bnk_id": 700,
                "loop_point_mode": "auto", "loop_point_manual_ms": 0, "volume_enabled": True, "volume_db": 0.0,
            },
            "0|7002": {
                "wem_path": "nulled.wem", "file_type": "bnk", "lang_id": 0, "bnk_id": 0,
                "loop_point_mode": "auto", "loop_point_manual_ms": 0, "volume_enabled": True, "volume_db": 0.0,
            },
        },
    }


def test_audio_settings_survive_a_reload_from_disk(tmp_path):
    tracker_path = tmp_path / "mod_tracker.json"
    manager = PersistentModManager(tracker_path=tracker_path)
    manager.add_replacement(
        "Full/Streamed_SFX_1.pck", 5001, "mod.wem",
        loop_point_mode="manual", loop_point_manual_ms=1234, volume_enabled=False, volume_db=-6.5,
    )

    reloaded = PersistentModManager(tracker_path=tracker_path)

    assert reloaded.get_all_replacements() == manager.get_all_replacements()
    entry = reloaded.get_replacements("Full/Streamed_SFX_1.pck")["5001"]
    assert (entry["loop_point_mode"], entry["loop_point_manual_ms"], entry["volume_enabled"], entry["volume_db"]) == ("manual", 1234, False, -6.5)


def test_update_replacement_fields_merges_fields_and_refreshes_the_date(tmp_path):
    manager = PersistentModManager(tracker_path=tmp_path / "mod_tracker.json")
    manager.add_replacement("Full/SoundBank_SFX_1.pck", 7001, "mod.wem", file_type="bnk", bnk_id=700)
    manager.mod_tracker["Full/SoundBank_SFX_1.pck"]["700|7001"]["date_modified"] = "2000-01-01T00:00:00"

    assert manager.update_replacement_fields("Full/SoundBank_SFX_1.pck", "700|7001", volume_db=-3.0, loop_point_mode="disabled")

    entry = read_tracker_file(manager)["Full/SoundBank_SFX_1.pck"]["700|7001"]
    assert (entry["volume_db"], entry["loop_point_mode"], entry["wem_path"]) == (-3.0, "disabled", "mod.wem")
    assert entry["date_modified"] != "2000-01-01T00:00:00"


@pytest.mark.parametrize(("pck_key", "tracker_key", "fields"), [
    ("Missing.pck", "700|7001", {"volume_db": -3.0}),
    ("Full/SoundBank_SFX_1.pck", "700|9999", {"volume_db": -3.0}),
    ("Full/SoundBank_SFX_1.pck", "700|7001", {}),
])
def test_update_replacement_fields_rejects_unknown_targets(tmp_path, pck_key, tracker_key, fields):
    manager = PersistentModManager(tracker_path=tmp_path / "mod_tracker.json")
    manager.add_replacement("Full/SoundBank_SFX_1.pck", 7001, "mod.wem", file_type="bnk", bnk_id=700)

    assert not manager.update_replacement_fields(pck_key, tracker_key, **fields)


def test_remove_replacement_drops_the_entry_and_its_empty_pck(tmp_path):
    manager = PersistentModManager(tracker_path=tmp_path / "mod_tracker.json")
    manager.add_replacement("Full/SoundBank_SFX_1.pck", 7001, "a.wem", file_type="bnk", bnk_id=700)
    manager.add_replacement("Full/Streamed_SFX_1.pck", 5001, "b.wem")
    manager.add_replacement("Full/Streamed_SFX_1.pck", 5002, "c.wem")

    assert manager.remove_replacement("Full/SoundBank_SFX_1.pck", 7001, bnk_id=700)
    assert manager.remove_replacement("Full/Streamed_SFX_1.pck", "5001")
    assert not manager.remove_replacement("Full/Streamed_SFX_1.pck", "5001")
    assert not manager.remove_replacement("Missing.pck", "5001")

    assert list(read_tracker_file(manager)) == ["Full/Streamed_SFX_1.pck"]
    assert list(manager.get_replacements("Full/Streamed_SFX_1.pck")) == ["5002"]
    assert not manager.has_replacements("Full/SoundBank_SFX_1.pck")
    assert manager.has_replacements("Full/Streamed_SFX_1.pck")


def test_clearing_one_pck_or_everything(tmp_path):
    manager = PersistentModManager(tracker_path=tmp_path / "mod_tracker.json")
    manager.add_replacement("Full/Streamed_SFX_1.pck", 5001, "a.wem")
    manager.add_replacement("Full/Streamed_SFX_2.pck", 6001, "b.wem")

    assert manager.clear_pck_mods("Full/Streamed_SFX_1.pck")
    assert not manager.clear_pck_mods("Full/Streamed_SFX_1.pck")
    assert list(read_tracker_file(manager)) == ["Full/Streamed_SFX_2.pck"]

    manager.clear_all_replacements()
    assert read_tracker_file(manager) == {}


def test_get_stats_counts_pcks_and_replacements(tmp_path):
    manager = PersistentModManager(tracker_path=tmp_path / "mod_tracker.json")
    manager.add_replacement("Full/Streamed_SFX_1.pck", 5001, "a.wem")
    manager.add_replacement("Full/Streamed_SFX_1.pck", 5002, "b.wem")
    manager.add_replacement("Full/SoundBank_SFX_1.pck", 7001, "c.wem", file_type="bnk", bnk_id=700)

    assert manager.get_stats() == {
        "modded_pcks": 2,
        "total_replacements": 3,
        "pcks": ["Full/Streamed_SFX_1.pck", "Full/SoundBank_SFX_1.pck"],
    }


def test_import_replacements_from_mods_replaces_the_whole_tracker(tmp_path):
    tracker_path = tmp_path / "mod_tracker.json"
    manager = PersistentModManager(tracker_path=tracker_path)
    manager.add_replacement("Full/Stale.pck", 1, "stale.wem")
    applied = {"Full/SoundBank_SFX_1.pck": {"7001": {
        "wem_path": "mod.wem", "file_type": "bnk", "lang_id": 0, "bnk_id": 700,
        "date_modified": "2026-01-01T00:00:00", "source": "mod_manager", "volume_db": -2.0,
    }}}

    manager.import_replacements_from_mods(applied)

    assert PersistentModManager(tracker_path=tracker_path).get_all_replacements() == applied


def test_corrupt_tracker_loads_as_empty(tmp_path):
    tracker_path = tmp_path / "mod_tracker.json"
    tracker_path.write_text("{not json", encoding="utf-8")

    assert PersistentModManager(tracker_path=tracker_path).get_all_replacements() == {}


def test_persistent_pck_path_requires_the_persistent_root(tmp_path):
    manager = PersistentModManager(tracker_path=tmp_path / "mod_tracker.json")
    with pytest.raises(ValueError):
        manager.get_persistent_pck_path("Full/Streamed_SFX_1.pck")

    manager.set_persistent_path(tmp_path / "Persistent")

    assert manager.get_persistent_pck_path("Full/Streamed_SFX_1.pck") == tmp_path / "Persistent" / "Full" / "Streamed_SFX_1.pck"


def test_export_mod_list_writes_the_tracker(tmp_path):
    manager = PersistentModManager(tracker_path=tmp_path / "mod_tracker.json")
    manager.add_replacement("Full/Streamed_SFX_1.pck", 5001, "a.wem")
    export_path = tmp_path / "export.json"

    manager.export_mod_list(export_path)

    assert json.loads(export_path.read_text(encoding="utf-8")) == manager.get_all_replacements()
