import hashlib
import json

import pytest

from src.core.config_manager import get_fingerprint_database_file
from src.data.fingerprint_database import FingerprintDatabase

SAMPLE_FINGERPRINT = {"fft": [0.1, 0.2, 0.3], "dct": [1, 2, 3], "duration": 1.5}


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "fingerprints" / "fingerprint_database.json"


def test_default_path_is_the_default_game_database():
    assert FingerprintDatabase().db_path == get_fingerprint_database_file()


def test_fingerprint_round_trips_through_save_and_load(db_path):
    database = FingerprintDatabase(db_path)
    database.add_fingerprint(b"wem-a", SAMPLE_FINGERPRINT)
    assert database.get_fingerprint(b"wem-a") == SAMPLE_FINGERPRINT
    assert database.has_fingerprint(b"wem-a")
    database.save()
    reloaded = FingerprintDatabase(db_path)
    assert reloaded.get_fingerprint(b"wem-a") == SAMPLE_FINGERPRINT
    assert reloaded.get_fingerprint(b"wem-b") is None
    assert not reloaded.has_fingerprint(b"wem-b")


def test_outdated_fingerprint_version_is_ignored(db_path):
    db_path.parent.mkdir(parents=True)
    outdated_entry = {"fingerprint": SAMPLE_FINGERPRINT, "version": "1.0", "generated": "2025-01-01T00:00:00"}
    db_path.write_text(json.dumps({hashlib.sha256(b"wem-a").hexdigest(): outdated_entry}), encoding="utf-8")
    database = FingerprintDatabase(db_path)
    assert database.get_fingerprint(b"wem-a") is None
    assert not database.has_fingerprint(b"wem-a")
    database.add_fingerprint(b"wem-b", SAMPLE_FINGERPRINT)
    assert database.get_stats() == {"total_fingerprints": 2, "current_version_count": 1, "outdated_count": 1}


def test_database_autosaves_every_hundred_fingerprints(db_path):
    database = FingerprintDatabase(db_path)
    for index in range(99):
        database.add_fingerprint(f"wem-{index}".encode(), {"index": index})
    assert not db_path.exists()
    database.add_fingerprint(b"wem-99", {"index": 99})
    assert len(json.loads(db_path.read_text(encoding="utf-8"))) == 100
    assert database._pending_saves == 0


def test_corrupt_database_file_loads_empty(db_path):
    db_path.parent.mkdir(parents=True)
    db_path.write_text("{corrupt", encoding="utf-8")
    database = FingerprintDatabase(db_path)
    assert database.get_stats()["total_fingerprints"] == 0
    database.add_fingerprint(b"wem-a", SAMPLE_FINGERPRINT)
    database.save()
    assert FingerprintDatabase(db_path).get_fingerprint(b"wem-a") == SAMPLE_FINGERPRINT


def test_same_bytes_overwrite_the_previous_fingerprint(db_path):
    database = FingerprintDatabase(db_path)
    database.add_fingerprint(b"wem-a", {"fft": [1]})
    database.add_fingerprint(b"wem-a", {"fft": [2]})
    assert database.get_fingerprint(b"wem-a") == {"fft": [2]}
    assert database.get_stats()["total_fingerprints"] == 1
