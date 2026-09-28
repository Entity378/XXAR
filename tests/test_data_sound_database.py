import hashlib
import json

import pytest

from src.core.config_manager import get_sound_database_file
from src.data.sound_database import SoundDatabase


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "sound_database.json"


def sha256(file_bytes):
    return hashlib.sha256(file_bytes).hexdigest()


def test_default_path_is_the_default_game_database():
    assert SoundDatabase().db_path == get_sound_database_file()


def test_added_sound_round_trips_through_disk(db_path):
    database = SoundDatabase(db_path)
    sound_hash = database.add_sound(b"wem-a", "Ellen Voice", tags=["voice", "ellen"], notes="line 1", file_id=123)
    assert sound_hash == sha256(b"wem-a")
    reloaded = SoundDatabase(db_path)
    info = reloaded.get_sound_info(b"wem-a")
    assert info["name"] == "Ellen Voice"
    assert info["tags"] == ["voice", "ellen"]
    assert info["notes"] == "line 1"
    assert info["file_ids"] == [123]
    assert reloaded.get_sound_info(b"unknown") is None


def test_database_is_loaded_lazily(db_path):
    SoundDatabase(db_path).add_sound(b"wem-a", "A")
    lazy_database = SoundDatabase(db_path)
    assert lazy_database.database == {}
    assert lazy_database.search_by_name("a")
    assert len(lazy_database.database) == 1


def test_adding_the_same_bytes_updates_the_entry(db_path):
    database = SoundDatabase(db_path)
    database.add_sound(b"wem-a", "Old", tags=["old"], file_id=1)
    first_added = database.get_sound_info(b"wem-a")["date_added"]
    database.add_sound(b"wem-a", "New", tags=["new"], notes="n", file_id=2)
    database.add_sound(b"wem-a", "New", tags=["new"], notes="n", file_id=2)
    info = database.get_sound_info(b"wem-a")
    assert len(database.database) == 1
    assert info["name"] == "New"
    assert info["tags"] == ["new"]
    assert info["file_ids"] == [1, 2]
    assert info["date_added"] == first_added


def test_search_by_name_and_tag_are_case_insensitive_substrings(db_path):
    database = SoundDatabase(db_path)
    ellen_hash = database.add_sound(b"wem-a", "Ellen Attack", tags=["Combat", "Ellen"])
    lycaon_hash = database.add_sound(b"wem-b", "Lycaon Idle", tags=["idle"])
    assert set(database.search_by_name("ELLEN")) == {ellen_hash}
    assert set(database.search_by_name("")) == {ellen_hash, lycaon_hash}
    assert set(database.search_by_tag("comb")) == {ellen_hash}
    assert set(database.search_by_tag("IDLE")) == {lycaon_hash}
    assert database.search_by_tag("music") == {}


def test_search_by_id_matches_int_and_string_ids(db_path):
    database = SoundDatabase(db_path)
    sound_hash = database.add_sound(b"wem-a", "A", file_id=4242)
    assert set(database.search_by_id(4242)) == {sound_hash}
    assert set(database.search_by_id("4242")) == {sound_hash}
    assert set(database.search_by_id(" 4242 ")) == {sound_hash}
    assert database.search_by_id(1) == {}


def test_search_by_id_index_follows_changes(db_path):
    database = SoundDatabase(db_path)
    first_hash = database.add_sound(b"wem-a", "A", file_id=7)
    assert set(database.search_by_id(7)) == {first_hash}
    second_hash = database.add_sound(b"wem-b", "B", file_id=7)
    assert set(database.search_by_id(7)) == {first_hash, second_hash}
    assert database.delete_sound(first_hash)
    assert set(database.search_by_id(7)) == {second_hash}


def test_delete_sound_persists(db_path):
    database = SoundDatabase(db_path)
    sound_hash = database.add_sound(b"wem-a", "A")
    assert database.delete_sound(sound_hash)
    assert not database.delete_sound(sound_hash)
    assert SoundDatabase(db_path).get_sound_info(b"wem-a") is None


def test_corrupt_database_file_loads_empty(db_path):
    db_path.write_text("{corrupt", encoding="utf-8")
    database = SoundDatabase(db_path)
    assert database.search_by_name("") == {}
    database.add_sound(b"wem-a", "A")
    assert json.loads(db_path.read_text(encoding="utf-8"))[sha256(b"wem-a")]["name"] == "A"


def test_export_then_merge_import_counts_only_new_entries(tmp_path):
    source_database = SoundDatabase(tmp_path / "source.json")
    shared_hash = source_database.add_sound(b"shared", "Shared From Source", tags=["x"])
    new_hash = source_database.add_sound(b"new", "Only In Source")
    export_path = tmp_path / "export.json"
    source_database.export_to_file(export_path)

    target_database = SoundDatabase(tmp_path / "target.json")
    kept_hash = target_database.add_sound(b"kept", "Only In Target")
    target_database.add_sound(b"shared", "Shared From Target")
    assert target_database.import_from_file(export_path) == 1
    assert set(target_database.database) == {shared_hash, new_hash, kept_hash}
    assert target_database.database[shared_hash]["name"] == "Shared From Source"
    assert set(SoundDatabase(tmp_path / "target.json").search_by_name("")) == {shared_hash, new_hash, kept_hash}


def test_replace_import_drops_existing_entries(tmp_path):
    export_path = tmp_path / "export.json"
    source_database = SoundDatabase(tmp_path / "source.json")
    imported_hash = source_database.add_sound(b"new", "New")
    source_database.export_to_file(export_path)
    target_database = SoundDatabase(tmp_path / "target.json")
    target_database.add_sound(b"old", "Old")
    assert target_database.import_from_file(export_path, merge=False) == 1
    assert set(target_database.database) == {imported_hash}


def test_stats_and_tags(db_path):
    database = SoundDatabase(db_path)
    database.add_sound(b"a", "A", tags=["voice", "ellen"])
    database.add_sound(b"b", "B", tags=["voice"])
    database.add_sound(b"c", "C")
    assert database.get_stats() == {
        "total_sounds": 3,
        "tagged_sounds": 2,
        "total_unique_tags": 2,
        "all_tags": ["ellen", "voice"],
    }
    assert database.get_all_tags() == ["ellen", "voice"]


def test_non_ascii_names_are_stored_verbatim(db_path):
    SoundDatabase(db_path).add_sound(b"a", "エレン 叫び", tags=["日本語"])
    assert "エレン 叫び" in db_path.read_text(encoding="utf-8")
    assert SoundDatabase(db_path).get_all_tags() == ["日本語"]
