import pytest

from src.core import temp_cache_manager
from src.core.temp_cache_manager import TempCacheManager


@pytest.fixture
def make_cache(monkeypatch, tmp_path):
    temp_root = tmp_path / "temp"
    temp_root.mkdir()
    monkeypatch.setattr(temp_cache_manager, "get_temp_dir", lambda: temp_root)
    created_caches = []

    def make(max_cached_files=100):
        cache = TempCacheManager(max_cached_files=max_cached_files)
        created_caches.append(cache)
        return cache

    yield make
    for cache in created_caches:
        cache.cleanup()


def test_cache_dir_is_created_under_the_temp_dir(make_cache, tmp_path):
    cache = make_cache()
    assert cache.cache_dir.parent == tmp_path / "temp"
    assert cache.cache_dir.name.startswith("xxar_audio_cache_")
    assert cache.cache_dir.is_dir()


def test_cache_key_uses_the_pck_basename(make_cache, tmp_path):
    cache = make_cache()
    assert cache.get_cache_key(tmp_path / "En" / "SoundBank_SFX_1.pck", 1234, "wem") == "SoundBank_SFX_1.pck:1234:wem"


def test_added_file_round_trips(make_cache):
    cache = make_cache()
    cache_key = "Streamed_SFX_1.pck:77:wem"
    cached_file = cache.add_to_cache(cache_key, b"RIFF-bytes")
    assert cached_file.parent == cache.cache_dir
    assert cached_file.name == "Streamed_SFX_1.pck_77_wem.wav"
    assert cached_file.read_bytes() == b"RIFF-bytes"
    assert cache.get_cached_path(cache_key) == cached_file
    assert cache.get_cached_path("unknown:1:wem") is None


def test_keys_with_slashes_stay_inside_the_cache_dir(make_cache):
    cache = make_cache()
    cached_file = cache.add_to_cache("En/Patch.pck:1:bnk", b"x", extension=".ogg")
    assert cached_file.parent == cache.cache_dir
    assert cached_file.suffix == ".ogg"


def test_least_recently_used_entry_is_evicted(make_cache):
    cache = make_cache(max_cached_files=2)
    first_file = cache.add_to_cache("a.pck:1:wem", b"1")
    second_file = cache.add_to_cache("a.pck:2:wem", b"2")
    assert cache.get_cached_path("a.pck:1:wem") == first_file
    third_file = cache.add_to_cache("a.pck:3:wem", b"3")
    assert cache.get_cached_path("a.pck:2:wem") is None
    assert not second_file.exists()
    assert first_file.exists()
    assert third_file.exists()
    assert list(cache.cache_index) == ["a.pck:1:wem", "a.pck:3:wem"]


def test_deleted_cache_file_is_dropped_from_the_index(make_cache):
    cache = make_cache()
    cached_file = cache.add_to_cache("a.pck:1:wem", b"1")
    cached_file.unlink()
    assert cache.get_cached_path("a.pck:1:wem") is None
    assert "a.pck:1:wem" not in cache.cache_index


def test_cache_info_and_clear(make_cache):
    cache = make_cache(max_cached_files=5)
    cache.add_to_cache("a.pck:1:wem", b"x" * 1024)
    cache.add_to_cache("a.pck:2:wem", b"y" * 2048)
    info = cache.get_cache_info()
    assert info["file_count"] == 2
    assert info["total_size_bytes"] == 3072
    assert info["max_files"] == 5
    assert info["cache_dir"] == str(cache.cache_dir)
    cache.clear_cache()
    assert cache.get_cache_info()["file_count"] == 0
    assert list(cache.cache_dir.iterdir()) == []


def test_cleanup_removes_the_cache_dir_and_is_repeatable(make_cache):
    cache = make_cache()
    cache.add_to_cache("a.pck:1:wem", b"1")
    cache.cleanup()
    assert not cache.cache_dir.exists()
    cache.cleanup()
