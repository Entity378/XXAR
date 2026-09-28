import json
import shutil
import struct
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from scipy.io import wavfile

import src.audio.converter as converter_module
import src.audio.wwise_wrapper as wwise_wrapper
from src.audio import constellation
from src.audio.converter import TRUE_PEAK_CEILING_DBTP, AudioConverter
from src.audio.matcher import AudioMatcher
from src.audio.wwise_wrapper import WwiseConsole
from src.core.subprocess_utils import get_bundled_resources_dir
from src.gui.backend.audio_games.base_handler import BaseBrowserHandler

pytestmark = pytest.mark.tools

SAMPLE_RATE = 48000
WWISE_VORBIS_FORMAT_TAG = 0xFFFF


def seconds(duration, sample_rate=SAMPLE_RATE):
    return np.arange(int(duration * sample_rate)) / sample_rate


def sine(frequency, duration, amplitude=0.5, sample_rate=SAMPLE_RATE):
    return amplitude * np.sin(2 * np.pi * frequency * seconds(duration, sample_rate))


def log_chirp(duration=4.0, start_hz=100.0, end_hz=6000.0):
    growth = (end_hz / start_hz) ** (1 / duration)
    return 0.5 * np.sin(2 * np.pi * start_hz * (growth ** seconds(duration) - 1) / np.log(growth))


def noise_bursts(duration=4.0):
    gate = np.sin(2 * np.pi * 3 * seconds(duration)) > 0.3
    return np.random.default_rng(3).normal(0, 0.3, len(gate)) * gate


def click_train(duration=4.0):
    impulses = np.zeros(int(duration * SAMPLE_RATE))
    impulses[:: SAMPLE_RATE // 8] = 0.9
    ring_time = np.arange(2000)
    return np.convolve(impulses, np.exp(-ring_time / 200) * np.sin(2 * np.pi * 3000 * ring_time / SAMPLE_RATE), mode="same")


def quiet_tone_with_loud_clicks(duration=4.0):
    signal = sine(1000, duration, amplitude=0.02)
    for click_start in range(0, len(signal), SAMPLE_RATE // 2):
        signal[click_start : click_start + 48] = 0.9
    return signal


def write_wav(path, signal, sample_rate=SAMPLE_RATE):
    path.parent.mkdir(parents=True, exist_ok=True)
    wavfile.write(path, sample_rate, np.clip(np.asarray(signal) * 32767, -32768, 32767).astype(np.int16))
    return path


def stereo(signal):
    return np.stack([signal, signal], axis=1)


def encode_with_ffmpeg(converter, source, target, *output_options):
    subprocess.run([converter.ffmpeg_path, "-v", "error", "-y", "-i", str(source), *output_options, str(target)], check=True, capture_output=True)
    return target


def probe(converter, audio_file):
    ffprobe_path = Path(converter.ffmpeg_path).with_name("ffprobe.exe")
    result = subprocess.run(
        [str(ffprobe_path), "-v", "error", "-show_entries", "stream=sample_rate,channels,codec_name:format=duration", "-of", "json", str(audio_file)],
        check=True, capture_output=True, text=True,
    )
    report = json.loads(result.stdout)
    stream = report["streams"][0]
    return SimpleNamespace(
        sample_rate=int(stream["sample_rate"]), channels=int(stream["channels"]),
        codec=stream["codec_name"], duration=float(report["format"]["duration"]),
    )


def measure_loudness(converter, audio_file):
    result = subprocess.run(
        [converter.ffmpeg_path, "-hide_banner", "-i", str(audio_file), "-af", "loudnorm=print_format=json", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    report = result.stderr
    measured = json.loads(report[report.rfind("{") : report.rfind("}") + 1])
    return float(measured["input_i"]), float(measured["input_tp"])


def dominant_frequency(wav_file):
    sample_rate, samples = wavfile.read(wav_file)
    channel = samples[:, 0] if samples.ndim == 2 else samples
    spectrum = np.abs(np.fft.rfft(channel.astype(np.float64)))
    return np.fft.rfftfreq(len(channel), 1 / sample_rate)[int(np.argmax(spectrum))]


def wem_format_tag(wem_bytes):
    assert wem_bytes[:4] == b"RIFF" and wem_bytes[8:12] == b"WAVE"
    fmt_chunk = wem_bytes.index(b"fmt ")
    return struct.unpack_from("<H", wem_bytes, fmt_chunk + 8)[0]


def file_snapshot(root):
    return {str(path): (path.stat().st_size, path.stat().st_mtime_ns) for path in root.rglob("*") if path.is_file()}


@pytest.fixture(scope="module")
def untouched_real_tools(real_tools_dir):
    before = file_snapshot(real_tools_dir)
    yield real_tools_dir
    assert file_snapshot(real_tools_dir) == before, "the audio tests wrote inside the real XXAR tools dir"


@pytest.fixture(scope="module")
def wwise_project_root(tmp_path_factory, untouched_real_tools):
    project_root = tmp_path_factory.mktemp("wwise_project")
    shutil.copytree(get_bundled_resources_dir() / "WAVtoWEM", project_root / "WAVtoWEM", ignore=shutil.ignore_patterns(".cache"))
    return project_root


@pytest.fixture(scope="module")
def module_wwise(untouched_real_tools, wwise_project_root):
    console = WwiseConsole(untouched_real_tools / "wwise", wwise_project_root / "WAVtoWEM" / "WAVtoWEM.wproj")
    if not console.is_installed():
        pytest.skip("Wwise is not installed in the real XXAR tools dir")
    return console


@pytest.fixture(scope="module")
def reference_wems(module_wwise, tmp_path_factory):
    wav_dir = tmp_path_factory.mktemp("reference_wavs")
    reference_sounds = {
        "stereo_tone": stereo(sine(440, 2.0)),
        "log_chirp": log_chirp(),
        "noise_bursts": noise_bursts(),
        "click_train": click_train(),
    }
    wav_files = [write_wav(wav_dir / f"{name}.wav", signal) for name, signal in reference_sounds.items()]
    wem_files = module_wwise.batch_convert_to_wem(wav_files, tmp_path_factory.mktemp("reference_wems"))
    assert len(wem_files) == len(reference_sounds)
    return {wem_file.stem: wem_file.read_bytes() for wem_file in wem_files}


@pytest.fixture
def private_temp_dirs(tmp_path, monkeypatch):
    system_temp = tmp_path / "system_temp"
    app_temp = tmp_path / "app_temp"
    system_temp.mkdir()
    app_temp.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(system_temp))
    monkeypatch.setattr(constellation, "get_temp_dir", lambda: app_temp)
    return SimpleNamespace(system_temp=system_temp, app_temp=app_temp)


@pytest.fixture
def audio_converter(untouched_real_tools, wwise_project_root, private_temp_dirs, monkeypatch):
    monkeypatch.setattr(converter_module, "get_tools_dir", lambda: untouched_real_tools)
    monkeypatch.setattr(wwise_wrapper, "get_tools_dir", lambda: untouched_real_tools)
    monkeypatch.setattr(wwise_wrapper, "_RESOURCE_DIR", wwise_project_root)
    converter = AudioConverter()
    if not (converter.ffmpeg_path and converter.vgmstream_path):
        pytest.skip("FFmpeg or vgmstream is missing from the real XXAR tools dir")
    monkeypatch.setenv("FFMPEG_PATH", converter.ffmpeg_path)
    return converter


@pytest.fixture
def wwise_converter(audio_converter):
    if not audio_converter.wwise_console.is_installed():
        pytest.skip("Wwise is not installed in the real XXAR tools dir")
    return audio_converter


def test_converter_uses_the_tools_installed_in_the_tools_dir(audio_converter, untouched_real_tools):
    for tool_path in (audio_converter.ffmpeg_path, audio_converter.vgmstream_path):
        assert Path(tool_path).is_relative_to(untouched_real_tools.resolve())
    version = subprocess.run([audio_converter.ffmpeg_path, "-version"], capture_output=True, text=True)
    assert version.returncode == 0 and version.stdout.startswith("ffmpeg version")


@pytest.mark.parametrize(
    ("sample_rate", "channels", "expected_peak"),
    [(48000, 2, 0.5 / np.sqrt(2)), (22050, 1, 0.5)],
    ids=["mono_to_48k_stereo_at_minus_3_db", "mono_to_22k_mono"],
)
def test_any_to_wav_without_normalization_resamples_and_remixes(audio_converter, tmp_path, sample_rate, channels, expected_peak):
    source = write_wav(tmp_path / "source.wav", sine(440, 1.5, sample_rate=44100), sample_rate=44100)

    output = audio_converter.any_to_wav(source, tmp_path / "out.wav", sample_rate=sample_rate, channels=channels, normalize=False)

    converted = probe(audio_converter, output)
    assert (converted.sample_rate, converted.channels, converted.codec) == (sample_rate, channels, "pcm_f32le")
    assert converted.duration == pytest.approx(1.5, abs=0.01)
    assert np.abs(wavfile.read(output)[1]).max() == pytest.approx(expected_peak, abs=0.02)


def test_any_to_wav_normalizes_loudness_to_the_target(audio_converter, tmp_path):
    source = write_wav(tmp_path / "quiet.wav", sine(1000, 3.0, amplitude=0.05))
    assert audio_converter._reachable_lufs(source, -16) == -16

    output = audio_converter.any_to_wav(source, tmp_path / "normalized.wav", normalize=True, normalize_lufs=-16)

    integrated_lufs, true_peak = measure_loudness(audio_converter, output)
    assert integrated_lufs == pytest.approx(-16, abs=1.0)
    assert true_peak <= TRUE_PEAK_CEILING_DBTP + 0.3
    converted = probe(audio_converter, output)
    assert (converted.sample_rate, converted.channels) == (48000, 2)


def test_any_to_wav_lowers_an_unreachable_target_to_keep_the_gain_linear(audio_converter, tmp_path):
    source = write_wav(tmp_path / "peaky.wav", quiet_tone_with_loud_clicks())
    source_lufs, source_peak = measure_loudness(audio_converter, source)
    reachable_lufs = audio_converter._reachable_lufs(source, -9)
    assert reachable_lufs == pytest.approx(source_lufs + TRUE_PEAK_CEILING_DBTP - source_peak, abs=0.1)
    assert reachable_lufs < -20

    output = audio_converter.any_to_wav(source, tmp_path / "normalized.wav", normalize=True, normalize_lufs=-9)

    integrated_lufs, true_peak = measure_loudness(audio_converter, output)
    assert integrated_lufs == pytest.approx(reachable_lufs, abs=1.0)
    assert true_peak <= TRUE_PEAK_CEILING_DBTP + 0.3


def test_wav_to_wem_and_back_preserves_duration_and_pitch(wwise_converter, tmp_path):
    source = write_wav(tmp_path / "tone.wav", stereo(sine(440, 2.0)))

    wem_file = wwise_converter.wav_to_wem(source, tmp_path / "wem" / "tone.wem")
    decoded = wwise_converter.wem_to_wav(wem_file, tmp_path / "decoded.wav")

    assert wem_file == tmp_path / "wem" / "tone.wem"
    assert wem_format_tag(wem_file.read_bytes()) == WWISE_VORBIS_FORMAT_TAG
    assert BaseBrowserHandler._get_wem_duration_ms(wem_file) == pytest.approx(2000, abs=50)
    round_trip = probe(wwise_converter, decoded)
    assert (round_trip.sample_rate, round_trip.channels) == (48000, 2)
    assert round_trip.duration == pytest.approx(2.0, abs=0.05)
    assert dominant_frequency(decoded) == pytest.approx(440, abs=2)


def test_any_to_wem_names_the_output_after_the_input(wwise_converter, tmp_path, private_temp_dirs):
    voice = write_wav(tmp_path / "voice.wav", sine(660, 1.0))
    song = encode_with_ffmpeg(wwise_converter, write_wav(tmp_path / "song_source.wav", log_chirp(2.0)), tmp_path / "song.mp3")

    song_wem = wwise_converter.any_to_wem(song)
    voice_wem = wwise_converter.any_to_wem(voice, normalize=True, normalize_lufs=-16)

    assert (Path(song_wem), Path(voice_wem)) == (tmp_path / "song.wem", tmp_path / "voice.wem")
    assert wem_format_tag(Path(song_wem).read_bytes()) == WWISE_VORBIS_FORMAT_TAG
    assert BaseBrowserHandler._get_wem_duration_ms(Path(voice_wem)) == pytest.approx(1000, abs=50)
    assert list(private_temp_dirs.system_temp.iterdir()) == []


def test_batch_conversions_take_other_formats_to_wem_and_back(wwise_converter, tmp_path):
    sources_dir = tmp_path / "sources"
    sources_dir.mkdir()
    durations = {"a": 1.0, "b": 1.5, "c": 2.0}
    for (stem, duration), suffix in zip(durations.items(), (".mp3", ".flac", ".ogg")):
        encode_with_ffmpeg(wwise_converter, write_wav(tmp_path / "raw" / f"{stem}.wav", sine(440, duration)), sources_dir / f"{stem}{suffix}")
    (sources_dir / "notes.txt").write_text("not audio")

    wav_files = wwise_converter.batch_convert_to_wav(sources_dir, tmp_path / "wav", normalize=False)
    wem_files = wwise_converter.batch_convert_wav_to_wem(tmp_path / "wav", tmp_path / "wem")
    normalized_wem_files = wwise_converter.batch_convert_wav_to_wem(tmp_path / "wav", tmp_path / "wem_normalized", normalize=True, normalize_lufs=-16)
    decoded_files = wwise_converter.batch_convert_wem_to_wav(tmp_path / "wem", tmp_path / "decoded")

    assert sorted(path.name for path in wav_files) == ["a.wav", "b.wav", "c.wav"]
    assert sorted(Path(path).name for path in wem_files) == ["a.wem", "b.wem", "c.wem"]
    assert sorted(Path(path).name for path in normalized_wem_files) == ["a.wem", "b.wem", "c.wem"]
    assert all(Path(path).is_file() for path in normalized_wem_files)
    for decoded in decoded_files:
        assert probe(wwise_converter, decoded).duration == pytest.approx(durations[decoded.stem], abs=0.05)
    assert len(decoded_files) == 3


def test_decode_file_returns_the_whole_audio_as_48_khz_mono(audio_converter, tmp_path):
    source = write_wav(tmp_path / "long.wav", stereo(sine(440, 35.0, sample_rate=44100)), sample_rate=44100)

    decoded = constellation.decode_file(audio_converter.ffmpeg_path, source)

    assert decoded.dtype == np.float32
    assert len(decoded) == pytest.approx(35.0 * 48000, rel=0.001)
    assert np.abs(decoded).max() == pytest.approx(0.5, abs=0.01)


def test_decode_wem_bytes_decodes_a_wwise_wem(audio_converter, reference_wems, private_temp_dirs):
    decoded = constellation.decode_wem_bytes(audio_converter.ffmpeg_path, reference_wems["stereo_tone"], audio_converter.vgmstream_path)

    assert len(decoded) / 48000 == pytest.approx(2.0, abs=0.05)
    assert list(private_temp_dirs.app_temp.iterdir()) == []


def test_decode_wem_bytes_rejects_bytes_that_are_not_a_wem(audio_converter, private_temp_dirs):
    assert constellation.decode_wem_bytes(audio_converter.ffmpeg_path, b"not a wem", audio_converter.vgmstream_path) is None
    assert list(private_temp_dirs.app_temp.iterdir()) == []


@pytest.mark.parametrize("file_sample_rate", [48000, 44100])
def test_fingerprint_of_a_wav_file_matches_the_fingerprint_of_its_samples(audio_converter, tmp_path, file_sample_rate):
    signal = log_chirp()
    wav_file = write_wav(tmp_path / "chirp.wav", signal)
    if file_sample_rate != SAMPLE_RATE:
        wav_file = encode_with_ffmpeg(audio_converter, wav_file, tmp_path / "chirp_resampled.wav", "-ar", str(file_sample_rate))
    matcher = AudioMatcher(audio_converter.ffmpeg_path, audio_converter.vgmstream_path)

    file_fingerprint = matcher.extract_fingerprint(wav_file)
    samples_fingerprint = matcher._build_fingerprint(signal.astype(np.float32), SAMPLE_RATE)

    assert file_fingerprint["sample_rate"] == 48000
    assert file_fingerprint["duration"] == pytest.approx(4.0, abs=0.001)
    assert matcher.compare_fingerprints(file_fingerprint, samples_fingerprint) > 98


def test_matcher_finds_a_quieter_recording_among_real_wems(audio_converter, reference_wems, tmp_path):
    query = write_wav(tmp_path / "recording.wav", 0.5 * log_chirp(), sample_rate=SAMPLE_RATE)
    matcher = AudioMatcher(audio_converter.ffmpeg_path, audio_converter.vgmstream_path)

    query_fingerprint = matcher.extract_fingerprint(query)
    candidates = [(wem_bytes, {"id": name}) for name, wem_bytes in reference_wems.items()]
    matches = matcher.find_matches(query_fingerprint, candidates, top_n=2)

    assert query_fingerprint["duration"] == pytest.approx(4.0, abs=0.01)
    assert [info["id"] for _, info in matches][0] == "log_chirp"
