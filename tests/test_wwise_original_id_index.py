import pytest

from helpers import build_bnk, build_pck, make_wem, write_files
from src.wwise import original_id_index
from src.wwise.original_id_index import allocate_free_ids, build_original_id_index, clear_cache, get_original_id_index

EXTERNAL_ID = 0x1_0000_0001
REALLOC_BASE = 0xF0000000


@pytest.fixture
def streaming_root(tmp_path):
    root = tmp_path / "StreamingAssets" / "Audio" / "Windows" / "Full"
    write_files(root, {
        "SoundBank_SFX_1.pck": build_pck(banks=[(1001, 0, build_bnk(1001))], sounds=[(2001, 0, make_wem(1))]),
        "En/Streamed_VO_1.pck": build_pck(
            sounds=[(3001, 1, make_wem(2))],
            externals=[(EXTERNAL_ID, 1, make_wem(3))],
            languages={1: "English(US)"},
        ),
        "broken.pck": b"NOPE" + b"\x00" * 32,
        "notes.txt": b"not a pck",
    })
    return root


def add_pck(root, name, sound_id):
    write_files(root, {name: build_pck(sounds=[(sound_id, 0, make_wem(sound_id))])})


def test_build_collects_every_id_and_skips_unreadable_pcks(streaming_root):
    assert build_original_id_index(streaming_root) == {1001, 2001, 3001, EXTERNAL_ID}


def test_missing_root_yields_no_ids(tmp_path):
    assert build_original_id_index(tmp_path / "missing") == set()
    assert get_original_id_index(None) == set()


def test_index_is_cached_until_refreshed_or_cleared(streaming_root):
    assert get_original_id_index(streaming_root) == {1001, 2001, 3001, EXTERNAL_ID}
    add_pck(streaming_root, "Streamed_SFX_2.pck", 4001)

    assert 4001 not in get_original_id_index(streaming_root)
    assert 4001 in get_original_id_index(streaming_root, refresh=True)
    add_pck(streaming_root, "Streamed_SFX_3.pck", 5001)
    clear_cache(streaming_root)
    assert 5001 in get_original_id_index(streaming_root)


def test_clear_cache_without_root_forgets_every_root(tmp_path, streaming_root):
    other_root = tmp_path / "OtherGame"
    add_pck(other_root, "Banks0.pck", 6001)
    get_original_id_index(streaming_root)
    get_original_id_index(other_root)
    add_pck(streaming_root, "Streamed_SFX_2.pck", 4001)
    add_pck(other_root, "Banks1.pck", 6002)

    clear_cache()

    assert 4001 in get_original_id_index(streaming_root)
    assert get_original_id_index(other_root) == {6001, 6002}


def test_callers_cannot_corrupt_the_cached_index(streaming_root):
    get_original_id_index(streaming_root).add(999)

    assert 999 not in get_original_id_index(streaming_root)


@pytest.mark.parametrize(
    "colliding_ids, extra_used_ids",
    [
        ([2001], set()),
        ([1001, 2001, 3001], {REALLOC_BASE, REALLOC_BASE + 1, REALLOC_BASE + 3}),
        (list(range(1, 200)), set(range(REALLOC_BASE, REALLOC_BASE + 150, 2))),
    ],
    ids=["one", "used_block_at_base", "many"],
)
def test_allocate_free_ids_never_reuses_an_id(colliding_ids, extra_used_ids):
    used_ids = set(colliding_ids) | extra_used_ids

    rename = allocate_free_ids(colliding_ids, used_ids)

    new_ids = list(rename.values())
    assert list(rename) == colliding_ids
    assert len(set(new_ids)) == len(new_ids)
    assert not set(new_ids) & used_ids
    assert all(0 < new_id <= 0xFFFFFFFF for new_id in new_ids)


def test_allocate_free_ids_takes_the_first_free_ids_above_the_base():
    rename = allocate_free_ids([10, 20], {10, 20, REALLOC_BASE, REALLOC_BASE + 1, REALLOC_BASE + 3})

    assert rename == {10: REALLOC_BASE + 2, 20: REALLOC_BASE + 4}


def test_allocate_free_ids_wraps_around_past_the_last_id(monkeypatch):
    monkeypatch.setattr(original_id_index, "_REALLOC_BASE", 0xFFFFFFFE)

    rename = allocate_free_ids([10, 20], {10, 20, 0xFFFFFFFE, 0xFFFFFFFF, 1})

    assert rename == {10: 2, 20: 3}


@pytest.mark.xfail(strict=True, reason="bug: the id after 0xFFFFFFFF is handed out before wrapping around")
def test_allocate_free_ids_stays_within_32_bits_at_the_end_of_the_range(monkeypatch):
    monkeypatch.setattr(original_id_index, "_REALLOC_BASE", 0xFFFFFFFF)

    rename = allocate_free_ids([10, 20], {10, 20})

    assert all(0 < new_id <= 0xFFFFFFFF for new_id in rename.values())
