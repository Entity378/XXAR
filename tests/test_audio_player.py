import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from scipy.io import wavfile

import src.audio.player as player_module
import src.core.temp_cache_manager as temp_cache_module
from src.core.config_manager import get_tools_dir
from src.core.temp_cache_manager import TempCacheManager
from helpers import record_signal

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="the ffplay-driven player is the Windows backend")

FFMPEG_BIN = ("audio", "ffmpeg", "ffmpeg-master-latest-win64-gpl", "bin")


class FakeFfplay:
    def __init__(self, command, **kwargs):
        self.command = command
        self.returncode = None

    def poll(self):
        return self.returncode

    def terminate(self):
        self.returncode = 1

    def wait(self, timeout=None):
        return self.returncode

    def kill(self):
        self.returncode = -9


class FakeConverter:
    def __init__(self):
        self.converted = []

    def wem_to_wav(self, wem_file):
        self.converted.append(Path(wem_file).read_bytes())
        wav_file = Path(wem_file).with_suffix(".wav")
        wav_file.write_bytes(b"RIFF decoded")
        return wav_file

    def refresh_tools(self):
        pass


class ManualClock:
    def __init__(self):
        self.now = 100.0

    def monotonic(self):
        return self.now


@pytest.fixture
def launched_ffplays(monkeypatch):
    launched = []

    def fake_popen(command, **kwargs):
        launched.append(FakeFfplay(command))
        return launched[-1]

    monkeypatch.setattr(player_module.subprocess, "Popen", fake_popen)
    return launched


@pytest.fixture
def clock(monkeypatch):
    manual_clock = ManualClock()
    monkeypatch.setattr(player_module, "time", SimpleNamespace(monotonic=manual_clock.monotonic))
    return manual_clock


@pytest.fixture
def app_temp_dir(tmp_path, monkeypatch):
    temp_dir = tmp_path / "app_temp"
    temp_dir.mkdir()
    monkeypatch.setattr(player_module, "get_temp_dir", lambda: temp_dir)
    monkeypatch.setattr(temp_cache_module, "get_temp_dir", lambda: temp_dir)
    return temp_dir


@pytest.fixture
def player(qapp, launched_ffplays, clock, app_temp_dir):
    audio_player = player_module.AudioPlayer(FakeConverter(), TempCacheManager())
    audio_player._ffplay_path = "ffplay.exe"
    audio_player._ffprobe_path = None
    yield audio_player
    audio_player.cleanup()


def install_fake_tool(*parts):
    tool = get_tools_dir().joinpath(*parts)
    tool.parent.mkdir(parents=True, exist_ok=True)
    tool.write_bytes(b"MZ")
    return tool


def test_player_finds_ffplay_and_ffprobe_in_the_tools_dir(qapp, monkeypatch):
    monkeypatch.setattr(player_module.shutil, "which", lambda name: None)
    ffplay = install_fake_tool(*FFMPEG_BIN, "ffplay.exe")
    ffprobe = install_fake_tool(*FFMPEG_BIN, "ffprobe.exe")
    audio_player = player_module.AudioPlayer(FakeConverter(), None)
    assert (audio_player._ffplay_path, audio_player._ffprobe_path) == (str(ffplay), str(ffprobe))


def test_play_wem_decodes_once_then_plays_from_the_cache(player, launched_ffplays, app_temp_dir):
    states = record_signal(player.state_changed)

    player.play_wem(b"RIFF first", "Banks0.pck:42:wem")
    player.play_wem(b"RIFF second", "Banks0.pck:42:wem")

    assert player.audio_converter.converted == [b"RIFF first"]
    cached_wav = Path(launched_ffplays[-1].command[-1])
    assert cached_wav.read_bytes() == b"RIFF decoded"
    assert sorted(path.suffix for path in app_temp_dir.rglob("*") if path.is_file()) == [".wav"]
    assert launched_ffplays[0].command[:5] == ["ffplay.exe", "-nodisp", "-autoexit", "-volume", "100"]
    assert launched_ffplays[0].returncode == 1
    assert states == [("playing",), ("playing",)]


def test_play_wem_without_ffplay_reports_the_missing_tool(player):
    player._ffplay_path = None
    errors = record_signal(player.error_occurred)
    with pytest.raises(RuntimeError, match="ffplay not found"):
        player.play_wem(b"RIFF", "Banks0.pck:42:wem")
    assert errors and "ffplay not found" in errors[0][0]


def test_pause_then_play_resumes_from_the_elapsed_position(player, launched_ffplays, clock):
    player.play_url("C:/music/track.wav")
    clock.now += 2.5
    player.pause()
    clock.now += 10.0
    assert player.get_state() == "paused"
    assert launched_ffplays[0].returncode == 1

    player.play()

    assert player.get_state() == "playing"
    assert launched_ffplays[1].command[-3:] == ["-ss", "2.500", "C:/music/track.wav"]


def test_volume_change_restarts_playback_at_the_same_position(player, launched_ffplays, clock):
    player.play_url("C:/music/track.wav")
    clock.now += 1.25
    player.set_volume(40)
    assert launched_ffplays[1].command[3:5] == ["-volume", "40"]
    assert launched_ffplays[1].command[-3:-1] == ["-ss", "1.250"]


def test_stop_resets_the_position(player, launched_ffplays):
    positions = record_signal(player.position_changed)
    player.play_url("C:/music/track.wav")
    player.stop()
    assert player.get_state() == "stopped"
    assert positions[-1] == (0,)
    assert launched_ffplays[0].returncode == 1


def test_poll_reports_stopped_when_ffplay_exits_on_its_own(player, launched_ffplays):
    states = record_signal(player.state_changed)
    player.play_url("C:/music/track.wav")
    launched_ffplays[0].returncode = 0
    player._poll_ffplay_status()
    assert player.get_state() == "stopped"
    assert states == [("playing",), ("stopped",)]


def test_poll_reports_the_elapsed_position_capped_at_the_duration(player, clock):
    positions = record_signal(player.position_changed)
    player.play_url("C:/music/track.wav")
    player._duration_ms = 3000
    clock.now += 1.0
    player._poll_ffplay_status()
    clock.now += 5.0
    player._poll_ffplay_status()
    assert positions == [(1000,), (3000,)]


@pytest.mark.tools
def test_ffprobe_measures_the_duration_of_a_wav(qapp, real_tools_dir, tmp_path, monkeypatch):
    monkeypatch.setattr(player_module, "get_tools_dir", lambda: real_tools_dir)
    wav_file = tmp_path / "tone.wav"
    wavfile.write(wav_file, 48000, (0.5 * np.sin(2 * np.pi * 440 * np.arange(72000) / 48000) * 32767).astype(np.int16))
    audio_player = player_module.AudioPlayer(FakeConverter(), None)
    if not audio_player._ffprobe_path:
        pytest.skip("ffprobe is missing from the real XXAR tools dir")
    assert audio_player._get_duration_ffprobe(wav_file) == pytest.approx(1500, abs=5)
