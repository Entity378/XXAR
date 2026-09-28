import subprocess

import numpy as np
import pytest
from scipy.io import wavfile

from real_game.real_game_helpers import GAME_IDS, audio_pcks, game_pck_index, installed_game, read_entries, smallest_pck
from src.audio import constellation
from src.audio.matcher import AudioMatcher
from src.core.game_registry import get_game
from src.gui.backend.audio_games.base_handler import BaseBrowserHandler

pytestmark = [pytest.mark.real_game, pytest.mark.tools]

FFMPEG_EXE = ("audio", "ffmpeg", "ffmpeg-master-latest-win64-gpl", "bin", "ffmpeg.exe")
VGMSTREAM_EXE = ("audio", "vgmstream", "vgmstream-cli.exe")
CANDIDATE_COUNT = 8


@pytest.fixture
def decoder_tools(real_tools_dir, tmp_path, monkeypatch):
    ffmpeg_path, vgmstream_path = real_tools_dir.joinpath(*FFMPEG_EXE), real_tools_dir.joinpath(*VGMSTREAM_EXE)
    if not (ffmpeg_path.is_file() and vgmstream_path.is_file()):
        pytest.skip("FFmpeg or vgmstream is missing from the real XXAR tools dir")
    app_temp = tmp_path / "app_temp"
    app_temp.mkdir()
    monkeypatch.setattr(constellation, "get_temp_dir", lambda: app_temp)
    return ffmpeg_path, vgmstream_path


def loose_wems(game_dirs, count):
    game = get_game(game_dirs.game_id)
    source = smallest_pck(
        [pck for pck in audio_pcks(game_dirs.streaming_root) if not game.is_protected_pck(pck.name)],
        lambda pck: len(game_pck_index(pck)["sounds"]) + len(game_pck_index(pck)["externals"]) >= count,
        f"with {count} loose WEMs",
    )
    entries = read_entries(source)
    return [(key[1], entries[key]) for key in entries if key[0] != "banks"][:count]


@pytest.mark.parametrize("game_id", GAME_IDS)
def test_real_loose_wems_decode_to_the_duration_in_their_header(real_game_audio_dirs, decoder_tools, game_id, tmp_path):
    game_dirs = installed_game(real_game_audio_dirs, game_id)
    ffmpeg_path, vgmstream_path = decoder_tools
    for wem_id, wem_bytes in loose_wems(game_dirs, 3):
        wem_file = tmp_path / f"{wem_id}.wem"
        wem_file.write_bytes(wem_bytes)
        header_ms = BaseBrowserHandler._get_wem_duration_ms(wem_file)
        decoded = constellation.decode_wem_bytes(str(ffmpeg_path), wem_bytes, str(vgmstream_path))
        assert decoded is not None and len(decoded) > 0, wem_id
        assert len(decoded) / 48 == pytest.approx(header_ms, abs=25), wem_id


@pytest.mark.parametrize("game_id", GAME_IDS)
def test_real_matcher_finds_a_quieter_recording_of_a_game_wem(real_game_audio_dirs, decoder_tools, game_id, tmp_path):
    game_dirs = installed_game(real_game_audio_dirs, game_id)
    ffmpeg_path, vgmstream_path = decoder_tools
    candidates = [(wem_bytes, {"id": wem_id}) for wem_id, wem_bytes in loose_wems(game_dirs, CANDIDATE_COUNT)]
    target_bytes, target_info = candidates[len(candidates) // 2]
    decoded_wav = tmp_path / "decoded.wav"
    (tmp_path / "target.wem").write_bytes(target_bytes)
    subprocess.run([str(vgmstream_path), "-o", str(decoded_wav), str(tmp_path / "target.wem")], check=True, capture_output=True)
    sample_rate, samples = wavfile.read(decoded_wav)
    recording = tmp_path / "recording.wav"
    wavfile.write(recording, sample_rate, (samples * 0.5).astype(samples.dtype))
    matcher = AudioMatcher(str(ffmpeg_path), str(vgmstream_path))

    matches = matcher.find_matches(matcher.extract_fingerprint(recording), candidates, top_n=3)

    assert matches[0][1] == target_info
    assert matches[0][0] > matches[1][0]
    assert np.isfinite(matches[0][0])
