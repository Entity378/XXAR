import subprocess
from collections import Counter, defaultdict

import numpy as np
import pytest

from src.audio import constellation

SAMPLE_RATE = constellation.SAMPLE_RATE
PCM_SAMPLES = np.array([0, 2**30, -(2**31), 2**31 - 1], dtype="<i4")


def melody(seed, duration=4.0, note_length=0.25):
    rng = np.random.default_rng(seed)
    note_time = np.arange(int(note_length * SAMPLE_RATE)) / SAMPLE_RATE
    envelope = np.minimum(1.0, np.minimum(note_time / 0.01, (note_length - note_time) / 0.02))
    notes = []
    for _ in range(int(duration / note_length)):
        frequency = rng.uniform(200, 2000)
        harmonics = sum(0.5 / harmonic * np.sin(2 * np.pi * harmonic * frequency * note_time) for harmonic in (1, 2, 3))
        notes.append(envelope * harmonics)
    return np.concatenate(notes).astype(np.float32)


def delayed(signal, delay_samples):
    return np.concatenate([np.zeros(delay_samples, np.float32), signal])


def time_offset_votes(reference_hashes, query_hashes):
    reference_times = defaultdict(list)
    for hash_value, anchor_time in reference_hashes:
        reference_times[hash_value].append(anchor_time)
    votes = Counter()
    for hash_value, anchor_time in query_hashes:
        for reference_time in reference_times.get(hash_value, ()):
            votes[round(anchor_time - reference_time, 3)] += 1
    return votes.most_common()


@pytest.fixture(scope="module")
def reference_melody():
    return melody(7)


@pytest.fixture(scope="module")
def reference_hashes(reference_melody):
    return constellation.extract_hashes(reference_melody)


@pytest.fixture
def recorded_commands(monkeypatch):
    commands = []

    def fake_run(command, **kwargs):
        commands.append(list(command))
        if "-o" in command:
            with open(command[command.index("-o") + 1], "wb") as wav_file:
                wav_file.write(b"RIFF decoded")
            return subprocess.CompletedProcess(command, 0, stdout=b"", stderr=b"")
        return subprocess.CompletedProcess(command, 0, stdout=PCM_SAMPLES.tobytes(), stderr=b"")

    monkeypatch.setattr(constellation.subprocess, "run", fake_run)
    return commands


@pytest.fixture
def private_temp_dir(tmp_path, monkeypatch):
    temp_dir = tmp_path / "temp"
    temp_dir.mkdir()
    monkeypatch.setattr(constellation, "get_temp_dir", lambda: temp_dir)
    return temp_dir


def test_extract_hashes_is_deterministic(reference_melody, reference_hashes):
    assert reference_hashes
    assert constellation.extract_hashes(reference_melody.copy()) == reference_hashes


@pytest.mark.parametrize(
    "audio",
    [None, np.zeros(0, np.float32), np.ones(constellation.N_FFT - 1, np.float32), np.zeros(2 * SAMPLE_RATE, np.float32)],
    ids=["none", "empty", "shorter_than_one_window", "silence"],
)
def test_extract_hashes_returns_nothing_without_peaks(audio):
    assert constellation.extract_hashes(audio) == []


def test_hashes_pack_two_close_frequencies_and_a_bounded_time_delta(reference_melody, reference_hashes):
    duration = len(reference_melody) / SAMPLE_RATE
    for hash_value, anchor_time in reference_hashes:
        assert 0 <= hash_value < 2**32
        anchor_frequency = hash_value >> (constellation.FREQ_BITS + constellation.DT_BITS)
        target_frequency = (hash_value >> constellation.DT_BITS) & constellation.FREQ_Q_MAX
        delta_ms = hash_value & constellation.DT_Q_MAX
        assert anchor_frequency > 0 and target_frequency > 0
        assert abs(np.log2(target_frequency / anchor_frequency)) <= constellation.DF_MAX_OCTAVES + 0.1
        assert constellation.DT_MIN_S * 1000 <= delta_ms <= constellation.DT_MAX_S * 1000
        assert 0.0 <= anchor_time <= duration
    anchor_times = [anchor_time for _, anchor_time in reference_hashes]
    assert anchor_times == sorted(anchor_times)


def test_peaks_are_capped_per_second_and_fanned_out_to_at_most_three_targets(reference_hashes):
    anchor_shift = constellation.FREQ_BITS + constellation.DT_BITS
    hashes_per_anchor = Counter((anchor_time, hash_value >> anchor_shift) for hash_value, anchor_time in reference_hashes)
    assert max(hashes_per_anchor.values()) <= constellation.FAN_OUT
    anchors_per_second = Counter(int(anchor_time) for anchor_time, _ in hashes_per_anchor)
    assert max(anchors_per_second.values()) <= constellation.PEAKS_PER_SECOND


@pytest.mark.parametrize("delay_samples", [5 * constellation.HOP, 6 * constellation.HOP + 57])
def test_delayed_audio_votes_for_its_delay(reference_melody, reference_hashes, delay_samples):
    votes = time_offset_votes(reference_hashes, constellation.extract_hashes(delayed(reference_melody, delay_samples)))
    (best_offset, best_votes), (_, runner_up_votes) = votes[0], votes[1]
    assert best_offset == pytest.approx(delay_samples / SAMPLE_RATE, abs=constellation.HOP / SAMPLE_RATE)
    assert best_votes >= 10
    assert best_votes >= 2 * runner_up_votes


def test_unrelated_audio_shares_almost_no_hashes(reference_hashes):
    reference_values = {hash_value for hash_value, _ in reference_hashes}
    for seed in (99, 1234):
        other_values = {hash_value for hash_value, _ in constellation.extract_hashes(melody(seed))}
        assert len(reference_values & other_values) <= 0.05 * len(reference_values)


def test_decode_file_asks_ffmpeg_for_the_whole_audio_as_48_khz_mono_s32le(tmp_path, recorded_commands):
    decoded = constellation.decode_file("ffmpeg.exe", tmp_path / "query.mp3")
    assert recorded_commands == [[
        "ffmpeg.exe", "-i", str(tmp_path / "query.mp3"), "-ar", "48000", "-ac", "1",
        "-f", "s32le", "-acodec", "pcm_s32le", "-",
    ]]
    assert decoded.dtype == np.float32
    assert decoded.tolist() == pytest.approx([0.0, 0.5, -1.0, 1.0], abs=1e-6)


def test_decode_file_returns_none_when_ffmpeg_fails(tmp_path, monkeypatch):
    def failing_run(command, **kwargs):
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(constellation.subprocess, "run", failing_run)
    assert constellation.decode_file("ffmpeg.exe", tmp_path / "query.mp3") is None


def test_decode_wem_bytes_runs_vgmstream_then_ffmpeg_and_removes_its_temp_files(private_temp_dir, recorded_commands):
    decoded = constellation.decode_wem_bytes("ffmpeg.exe", b"RIFF wem", "vgmstream-cli.exe")

    vgmstream_command, ffmpeg_command = recorded_commands
    assert vgmstream_command[:2] == ["vgmstream-cli.exe", "-o"]
    assert vgmstream_command[3].endswith(".wem")
    assert ffmpeg_command == [
        "ffmpeg.exe", "-i", vgmstream_command[2], "-ar", "48000", "-ac", "1",
        "-f", "s32le", "-acodec", "pcm_s32le", "-",
    ]
    assert decoded.tolist() == pytest.approx([0.0, 0.5, -1.0, 1.0], abs=1e-6)
    assert list(private_temp_dir.iterdir()) == []


def test_decode_wem_bytes_returns_none_and_cleans_up_when_vgmstream_fails(private_temp_dir, monkeypatch):
    def failing_vgmstream(command, **kwargs):
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(constellation.subprocess, "run", failing_vgmstream)
    assert constellation.decode_wem_bytes("ffmpeg.exe", b"RIFF wem", "vgmstream-cli.exe") is None
    assert list(private_temp_dir.iterdir()) == []
