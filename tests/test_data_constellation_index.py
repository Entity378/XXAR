import hashlib

import pytest

from src.data.constellation_index import ConstellationIndex


@pytest.fixture
def open_index(tmp_path):
    opened_indexes = []

    def open_at(index_path=tmp_path / "matcher" / "constellation_index.sqlite"):
        index = ConstellationIndex(index_path)
        opened_indexes.append(index)
        return index

    yield open_at
    for index in opened_indexes:
        index.close()


def sha256(file_bytes):
    return hashlib.sha256(file_bytes).hexdigest()


def constellation(hash_values, start_seconds=0.0, step_seconds=0.5):
    return [(hash_value, start_seconds + index * step_seconds) for index, hash_value in enumerate(hash_values)]


def test_new_index_is_empty_and_creates_its_folder(open_index, tmp_path):
    index = open_index()
    assert (tmp_path / "matcher").is_dir()
    assert index.stats() == {"files": 0, "hashes": 0}
    assert not index.has_file(b"wem-a")
    assert index.query(constellation([1, 2, 3])) == []


def test_added_file_is_indexed_once(open_index):
    index = open_index()
    index.add_file(b"wem-a", constellation([11, 12, 13]))
    index.add_file(b"wem-a", constellation([99, 98]))
    assert index.has_file(b"wem-a")
    assert index.stats() == {"files": 1, "hashes": 3}


def test_file_without_hashes_is_still_recorded(open_index):
    index = open_index()
    index.add_file(b"silence", [])
    assert index.has_file(b"silence")
    assert index.stats() == {"files": 1, "hashes": 0}


def test_index_persists_across_connections(open_index, tmp_path):
    index_path = tmp_path / "persist.sqlite"
    first_index = open_index(index_path)
    first_index.add_file(b"wem-a", constellation([1, 2, 3]))
    first_index.close()
    reopened_index = open_index(index_path)
    assert reopened_index.has_file(b"wem-a")
    assert reopened_index.query(constellation([1, 2, 3]))[0][0] == sha256(b"wem-a")


def test_query_ranks_by_aligned_votes_and_reports_the_offset(open_index):
    index = open_index()
    index.add_file(b"full-track", constellation([101, 102, 103, 104, 105, 106]))
    index.add_file(b"partial-overlap", constellation([103, 999, 104]))
    index.add_file(b"unrelated", constellation([500, 501, 502]))
    clip_from_two_seconds = constellation([105, 106], start_seconds=0.0)
    clip_from_one_second = constellation([103, 104, 105, 106], start_seconds=0.0)
    results = index.query(clip_from_one_second)
    assert [file_hash for file_hash, _, _ in results] == [sha256(b"full-track"), sha256(b"partial-overlap")]
    best_hash, best_votes, best_offset_seconds = results[0]
    assert best_votes == 4
    assert best_offset_seconds == pytest.approx(1.0)
    assert index.query(clip_from_two_seconds)[0][2] == pytest.approx(2.0)


def test_query_votes_only_for_consistent_offsets(open_index):
    index = open_index()
    index.add_file(b"track", [(1, 0.0), (2, 1.0), (3, 2.0)])
    scattered_clip = [(1, 0.0), (2, 5.0), (3, 9.0)]
    [(file_hash, votes, offset_seconds)] = index.query(scattered_clip)
    assert file_hash == sha256(b"track")
    assert votes == 1


def test_query_top_k_limits_results(open_index):
    index = open_index()
    for file_number in range(5):
        index.add_file(f"wem-{file_number}".encode(), constellation([7, 8]))
    assert len(index.query(constellation([7, 8]))) == 5
    assert len(index.query(constellation([7, 8]), top_k=2)) == 2


def test_query_with_unknown_hashes_returns_nothing(open_index):
    index = open_index()
    index.add_file(b"wem-a", constellation([1, 2, 3]))
    assert index.query(constellation([40, 41])) == []
    assert index.query([]) == []


def test_query_spans_more_hashes_than_one_sqlite_chunk(open_index):
    long_track_hashes = list(range(10_000, 12_000))
    index = open_index()
    index.add_file(b"long-track", constellation(long_track_hashes, step_seconds=0.01))
    [(file_hash, votes, offset_seconds)] = index.query(constellation(long_track_hashes, step_seconds=0.01))
    assert file_hash == sha256(b"long-track")
    assert votes == len(long_track_hashes)
    assert offset_seconds == pytest.approx(0.0)
