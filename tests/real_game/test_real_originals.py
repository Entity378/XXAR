import hashlib
from collections import Counter

import pytest

from real_game.real_game_helpers import GAME_IDS, audio_pcks, by_size, installed_game
from src.core.game_registry import get_game
from src.mods.persistent_originals import _ground_truth, _parse_hash_sidecar, load_manifest_md5s

pytestmark = pytest.mark.real_game

LAUNCHER_MANIFEST_COVERS_EVERY_PCK = {"zzz": True, "genshin": True, "hsr": False}


def md5_of(path):
    digest = hashlib.md5()
    with open(path, "rb") as pck_file:
        for block in iter(lambda: pck_file.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


@pytest.mark.parametrize("game_id", GAME_IDS)
def test_real_every_streaming_pck_has_ground_truth_matching_its_size(real_game_audio_dirs, game_id):
    game_dirs = installed_game(real_game_audio_dirs, game_id)
    streaming_root = game_dirs.streaming_root
    manifest = load_manifest_md5s(streaming_root)
    pcks = audio_pcks(streaming_root)
    sidecar_cache = {}
    ground_truth = {pck: _ground_truth(manifest, sidecar_cache, pck, pck.relative_to(streaming_root).as_posix()) for pck in pcks}

    assert manifest
    assert set(manifest) <= {pck.relative_to(streaming_root).as_posix() for pck in pcks}
    assert [pck.name for pck, (original_md5, _) in ground_truth.items() if original_md5 is None] == []
    assert [pck.name for pck, (_, size) in ground_truth.items() if size >= 0 and size != pck.stat().st_size] == []
    if LAUNCHER_MANIFEST_COVERS_EVERY_PCK[game_id]:
        assert len(manifest) == len(pcks)


@pytest.mark.parametrize("game_id", GAME_IDS)
def test_real_smallest_streaming_pcks_hash_to_their_ground_truth(real_game_audio_dirs, game_id):
    game_dirs = installed_game(real_game_audio_dirs, game_id)
    streaming_root = game_dirs.streaming_root
    game = get_game(game_id)
    manifest = load_manifest_md5s(streaming_root)
    smallest_pcks = [pck for pck in by_size(audio_pcks(streaming_root)) if not game.is_protected_pck(pck.name)][:3]

    for pck in smallest_pcks:
        original_md5, _ = _ground_truth(manifest, {}, pck, pck.relative_to(streaming_root).as_posix())
        assert md5_of(pck) == original_md5, pck.name


def test_real_hsr_hash_sidecars_sit_next_to_the_pck_they_describe(real_game_audio_dirs):
    game_dirs = installed_game(real_game_audio_dirs, "hsr")
    streaming_sidecars = sorted(game_dirs.streaming_root.rglob("*.hash"))
    persistent_sidecars = sorted(game_dirs.persistent_root.rglob("*.hash")) if game_dirs.persistent_root else []

    parsed = {sidecar: _parse_hash_sidecar(sidecar.name) for sidecar in streaming_sidecars + persistent_sidecars}

    assert streaming_sidecars
    assert [sidecar.name for sidecar, parsed_name in parsed.items() if parsed_name is None] == []
    assert [sidecar.name for sidecar in streaming_sidecars if not (sidecar.parent / parsed[sidecar][0]).is_file()] == []
    sidecars_per_pck = Counter((sidecar.parent, parsed[sidecar][0]) for sidecar in streaming_sidecars)
    assert [pck_name for (_, pck_name), count in sidecars_per_pck.items() if count > 1] == []
    assert all(len(md5_hex) == 32 and md5_hex == md5_hex.lower() for _, md5_hex in parsed.values())
