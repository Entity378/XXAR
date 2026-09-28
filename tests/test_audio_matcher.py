import inspect
import threading
from pathlib import Path

import numpy as np
import pytest

from src.audio import constellation
from src.audio.matcher import DEFAULT_WEIGHTS, AudioMatcher, _hz_to_mel, _mel_filterbank, _mel_to_hz

SAMPLE_RATE = 48000


def seconds(duration, sample_rate=SAMPLE_RATE):
    return np.arange(int(duration * sample_rate)) / sample_rate


def sine(frequency, duration=2.0, amplitude=0.5, sample_rate=SAMPLE_RATE):
    return (amplitude * np.sin(2 * np.pi * frequency * seconds(duration, sample_rate))).astype(np.float32)


def melody(seed, duration=4.0, note_length=0.25):
    rng = np.random.default_rng(seed)
    note_time = seconds(note_length)
    envelope = np.minimum(1.0, np.minimum(note_time / 0.01, (note_length - note_time) / 0.02))
    notes = []
    for _ in range(int(duration / note_length)):
        frequency = rng.uniform(200, 2000)
        harmonics = sum(0.5 / harmonic * np.sin(2 * np.pi * harmonic * frequency * note_time) for harmonic in (1, 2, 3))
        notes.append(envelope * harmonics)
    return np.concatenate(notes).astype(np.float32)


def log_chirp(duration=4.0, start_hz=100.0, end_hz=6000.0):
    growth = (end_hz / start_hz) ** (1 / duration)
    phase = 2 * np.pi * start_hz * (growth ** seconds(duration) - 1) / np.log(growth)
    return (0.5 * np.sin(phase)).astype(np.float32)


def noise_bursts(seed, duration=4.0):
    rng = np.random.default_rng(seed)
    gate = np.sin(2 * np.pi * 3 * seconds(duration)) > 0.3
    return (rng.normal(0, 0.3, len(gate)) * gate).astype(np.float32)


def vibrato_tone(frequency, duration=4.0):
    time = seconds(duration)
    return (0.5 * np.sin(2 * np.pi * frequency * time) * (1 + 0.3 * np.sin(2 * np.pi * 5 * time))).astype(np.float32)


def click_train(duration=4.0):
    impulses = np.zeros(int(duration * SAMPLE_RATE))
    impulses[:: SAMPLE_RATE // 8] = 0.9
    ring_time = np.arange(2000)
    ring = np.exp(-ring_time / 200) * np.sin(2 * np.pi * 3000 * ring_time / SAMPLE_RATE)
    return np.convolve(impulses, ring, mode="same").astype(np.float32)


def half_gain(signal):
    return signal * 0.5


def delayed_by_100_ms(signal):
    return np.concatenate([np.zeros(SAMPLE_RATE // 10, np.float32), signal])[: len(signal)]


def with_noise_at_30_db_snr(signal):
    noise_power = np.mean(signal**2) / 10**3
    noise = np.random.default_rng(5).normal(0, np.sqrt(noise_power), len(signal))
    return (signal + noise).astype(np.float32)


QUERY_VARIANTS = {"gain": half_gain, "offset": delayed_by_100_ms, "noise": with_noise_at_30_db_snr}


@pytest.fixture(scope="module")
def distinct_sounds():
    return {
        "melody": melody(7),
        "log_chirp": log_chirp(),
        "noise_bursts": noise_bursts(3),
        "vibrato_tone": vibrato_tone(330),
        "click_train": click_train(),
    }


@pytest.fixture(scope="module")
def matcher():
    return AudioMatcher(ffmpeg_path=None, vgmstream_path=None)


@pytest.fixture(scope="module")
def reference_fingerprints(matcher, distinct_sounds):
    return {name: matcher._build_fingerprint(signal, SAMPLE_RATE) for name, signal in distinct_sounds.items()}


@pytest.fixture
def stub_matcher(monkeypatch, reference_fingerprints):
    stub = AudioMatcher(ffmpeg_path=None, vgmstream_path=None)
    extracted = []

    def fingerprint_from_name(wem_bytes):
        extracted.append(wem_bytes)
        if wem_bytes == b"broken":
            raise ValueError("unreadable wem")
        return reference_fingerprints.get(wem_bytes.decode())

    monkeypatch.setattr(stub, "extract_fingerprint_from_bytes", fingerprint_from_name)
    stub.extracted = extracted
    return stub


def test_hz_to_mel_round_trips_and_maps_1000_hz_to_1000_mel():
    frequencies = np.array([0.0, 100.0, 1000.0, 8000.0, 24000.0])
    assert np.allclose(_mel_to_hz(_hz_to_mel(frequencies)), frequencies)
    assert _hz_to_mel(1000.0) == pytest.approx(1000.0, abs=0.1)


def test_mel_filterbank_is_one_unit_triangle_per_band_below_nyquist():
    filterbank = _mel_filterbank(SAMPLE_RATE, 4096, n_mels=40)
    assert filterbank.shape == (40, 2049)
    assert filterbank.min() == 0.0
    assert np.allclose(filterbank.max(axis=1), 1.0)
    assert not filterbank[:, -1].any()
    peak_bins = filterbank.argmax(axis=1)
    assert np.all(np.diff(peak_bins) > 0)
    for band, peak_bin in zip(filterbank, peak_bins):
        support = np.flatnonzero(band)
        assert np.array_equal(support, np.arange(support[0], support[-1] + 1))
        assert np.all(np.diff(band[support[0] : peak_bin + 1]) > 0)
        assert np.all(np.diff(band[peak_bin : support[-1] + 1]) < 0)
    band_widths = (filterbank > 0).sum(axis=1)
    assert band_widths[-1] > 10 * band_widths[0]


def test_fingerprint_needs_at_least_100_ms_of_audio(matcher):
    assert matcher._build_fingerprint(sine(440, duration=0.09), SAMPLE_RATE) is None
    assert matcher._build_fingerprint(sine(440, duration=0.1), SAMPLE_RATE) is not None


def test_fingerprint_shrinks_the_window_for_audio_shorter_than_one_fft(matcher):
    fingerprint = matcher._build_fingerprint(sine(440, duration=0.2, sample_rate=16000), 16000)
    assert len(fingerprint["mfcc"]["mean"]) == 13
    assert fingerprint["duration"] == pytest.approx(0.2)


def test_fingerprint_layout(matcher):
    fingerprint = matcher._build_fingerprint(sine(440), SAMPLE_RATE)
    assert set(fingerprint) == {
        "mfcc", "spectral_centroid", "energy", "chroma", "spectral_contrast", "zero_crossing_rate",
        "spectral_rolloff", "spectral_flatness", "onset_strength", "duration", "sample_rate",
    }
    assert len(fingerprint["mfcc"]["mean"]) == len(fingerprint["mfcc"]["std"]) == 13
    assert len(fingerprint["chroma"]) == 12
    assert sum(fingerprint["chroma"]) == pytest.approx(1.0)
    assert len(fingerprint["spectral_contrast"]) == 6
    assert fingerprint["sample_rate"] == SAMPLE_RATE
    assert fingerprint["duration"] == 2.0


@pytest.mark.parametrize(("frequency", "pitch_class"), [(440.0, 0), (880.0, 0), (523.25, 3), (329.63, 7)])
def test_sine_fingerprint_describes_its_pitch(matcher, frequency, pitch_class):
    fingerprint = matcher._build_fingerprint(sine(frequency), SAMPLE_RATE)
    assert int(np.argmax(fingerprint["chroma"])) == pitch_class
    assert fingerprint["spectral_centroid"]["mean"] == pytest.approx(frequency, rel=0.02)
    assert fingerprint["zero_crossing_rate"] == pytest.approx(2 * frequency / SAMPLE_RATE, rel=0.02)


def test_noise_is_flatter_and_crosses_zero_more_than_a_sine(matcher):
    white_noise = np.random.default_rng(1234).normal(0, 0.3, 2 * SAMPLE_RATE).astype(np.float32)
    noise_fingerprint = matcher._build_fingerprint(white_noise, SAMPLE_RATE)
    sine_fingerprint = matcher._build_fingerprint(sine(440), SAMPLE_RATE)
    assert noise_fingerprint["spectral_flatness"]["mean"] > 100 * sine_fingerprint["spectral_flatness"]["mean"]
    assert noise_fingerprint["zero_crossing_rate"] == pytest.approx(0.5, abs=0.02)


def test_energy_profile_is_the_rms_of_the_signal(matcher):
    fingerprint = matcher._build_fingerprint(sine(440, amplitude=0.5), SAMPLE_RATE)
    assert fingerprint["energy"]["mean"] == pytest.approx(0.5 / np.sqrt(2), rel=0.01)


def test_fingerprint_covers_the_whole_audio_without_truncation(matcher):
    # Matching long tracks from a partial query needs the full audio, so nothing past 30 s may be dropped.
    silence_then_tone = np.concatenate([np.zeros(35 * SAMPLE_RATE, np.float32), sine(1000, duration=5.0)])
    fingerprint = matcher._build_fingerprint(silence_then_tone, SAMPLE_RATE)
    assert fingerprint["duration"] == 40.0
    assert fingerprint["energy"]["max"] == pytest.approx(0.5 / np.sqrt(2), rel=0.01)


def test_matcher_decodes_at_48_khz_by_default():
    for method in (AudioMatcher.extract_fingerprint, AudioMatcher.extract_fingerprint_from_bytes):
        assert inspect.signature(method).parameters["sample_rate"].default == 48000
    assert constellation.SAMPLE_RATE == 48000


def test_extract_fingerprint_routes_wems_through_vgmstream_and_other_files_through_ffmpeg(tmp_path, monkeypatch):
    decode_calls = []

    def fake_decode_file(ffmpeg_path, audio_path, sample_rate):
        decode_calls.append(("file", ffmpeg_path, Path(audio_path).name, sample_rate))
        return sine(440)

    def fake_decode_wem_bytes(ffmpeg_path, wem_bytes, vgmstream_path, sample_rate):
        decode_calls.append(("wem", ffmpeg_path, wem_bytes, vgmstream_path, sample_rate))
        return sine(440)

    monkeypatch.setattr(constellation, "decode_file", fake_decode_file)
    monkeypatch.setattr(constellation, "decode_wem_bytes", fake_decode_wem_bytes)
    wem_file = tmp_path / "sound.WEM"
    wem_file.write_bytes(b"RIFF file")
    matcher = AudioMatcher("ffmpeg.exe", "vgmstream-cli.exe")

    assert matcher.extract_fingerprint(wem_file)["sample_rate"] == 48000
    assert matcher.extract_fingerprint(tmp_path / "query.mp3") is not None
    assert matcher.extract_fingerprint_from_bytes(b"RIFF bytes") is not None
    assert decode_calls == [
        ("wem", "ffmpeg.exe", b"RIFF file", "vgmstream-cli.exe", 48000),
        ("file", "ffmpeg.exe", "query.mp3", 48000),
        ("wem", "ffmpeg.exe", b"RIFF bytes", "vgmstream-cli.exe", 48000),
    ]


@pytest.mark.parametrize("decoded", [None, np.zeros(0, np.float32)])
def test_extract_fingerprint_returns_none_when_decoding_yields_nothing(tmp_path, monkeypatch, decoded):
    monkeypatch.setattr(constellation, "decode_file", lambda *args, **kwargs: decoded)
    monkeypatch.setattr(constellation, "decode_wem_bytes", lambda *args, **kwargs: decoded)
    matcher = AudioMatcher("ffmpeg.exe", "vgmstream-cli.exe")
    assert matcher.extract_fingerprint(tmp_path / "query.wav") is None
    assert matcher.extract_fingerprint_from_bytes(b"RIFF") is None


def test_identical_fingerprints_score_100(matcher, reference_fingerprints):
    assert sum(DEFAULT_WEIGHTS.values()) == pytest.approx(1.0)
    for fingerprint in reference_fingerprints.values():
        assert matcher.compare_fingerprints(fingerprint, fingerprint) == pytest.approx(100.0)


def test_missing_fingerprint_scores_zero(matcher, reference_fingerprints):
    fingerprint = reference_fingerprints["melody"]
    assert matcher.compare_fingerprints(None, fingerprint) == 0.0
    assert matcher.compare_fingerprints(fingerprint, None) == 0.0


@pytest.mark.parametrize("variant", sorted(QUERY_VARIANTS))
@pytest.mark.parametrize("sound_name", ["melody", "log_chirp", "noise_bursts", "vibrato_tone", "click_train"])
def test_compare_ranks_the_same_sound_above_different_sounds(matcher, distinct_sounds, reference_fingerprints, sound_name, variant):
    query = QUERY_VARIANTS[variant](distinct_sounds[sound_name])
    query_fingerprint = matcher._build_fingerprint(query, SAMPLE_RATE)
    scores = {name: matcher.compare_fingerprints(query_fingerprint, fingerprint) for name, fingerprint in reference_fingerprints.items()}
    assert max(scores, key=scores.get) == sound_name


@pytest.mark.parametrize(("duration_ratio", "penalty"), [(0.25, 0.4), (0.4, 0.6), (0.6, 0.85), (0.8, 1.0)])
def test_duration_mismatch_scales_the_score(matcher, reference_fingerprints, duration_ratio, penalty):
    fingerprint = reference_fingerprints["vibrato_tone"]
    shorter = dict(fingerprint, duration=fingerprint["duration"] * duration_ratio)
    assert matcher.compare_fingerprints(fingerprint, shorter) == pytest.approx(100.0 * penalty)


def test_find_matches_returns_the_top_n_by_descending_score(matcher, stub_matcher, distinct_sounds, reference_fingerprints):
    query_fingerprint = matcher._build_fingerprint(half_gain(distinct_sounds["log_chirp"]), SAMPLE_RATE)
    candidates = [(name.encode(), {"id": name}) for name in reference_fingerprints]
    progress = []

    matches = stub_matcher.find_matches(
        query_fingerprint, candidates, top_n=3, progress_callback=lambda done, total: progress.append((done, total)),
    )

    expected_scores = sorted((matcher.compare_fingerprints(query_fingerprint, fingerprint) for fingerprint in reference_fingerprints.values()), reverse=True)
    assert [score for score, _ in matches] == pytest.approx(expected_scores[:3])
    assert matches[0][1] == {"id": "log_chirp"}
    assert progress == [(done, len(candidates)) for done in range(1, len(candidates) + 1)]


def test_find_matches_drops_candidates_that_cannot_be_fingerprinted(stub_matcher, reference_fingerprints):
    candidates = [(b"undecodable", {"id": "undecodable"}), (b"broken", {"id": "broken"}), (b"melody", {"id": "melody"})]
    progress = []

    matches = stub_matcher.find_matches(
        reference_fingerprints["melody"], candidates, progress_callback=lambda done, total: progress.append(done),
    )

    assert [info["id"] for _, info in matches] == ["melody"]
    assert progress == [1, 2, 3]


def test_find_matches_without_candidates_returns_nothing(stub_matcher, reference_fingerprints):
    assert stub_matcher.find_matches(reference_fingerprints["melody"], []) == []


def test_find_matches_submits_nothing_once_cancelled(stub_matcher, reference_fingerprints):
    cancel_event = threading.Event()
    cancel_event.set()
    candidates = [(name.encode(), {"id": name}) for name in reference_fingerprints]

    assert stub_matcher.find_matches(reference_fingerprints["melody"], candidates, cancel_event=cancel_event) == []
    assert stub_matcher.extracted == []


def test_find_matches_stops_collecting_when_cancelled_midway(stub_matcher, reference_fingerprints):
    cancel_event = threading.Event()
    candidates = [(name.encode(), {"id": name}) for name in reference_fingerprints]
    progress = []

    def cancel_after_first(done, total):
        progress.append(done)
        cancel_event.set()

    matches = stub_matcher.find_matches(
        reference_fingerprints["melody"], candidates, progress_callback=cancel_after_first,
        cancel_event=cancel_event, max_workers=1,
    )

    assert progress == [1]
    assert len(matches) == 1


def test_find_matches_reuses_cached_fingerprints_and_caches_new_ones(stub_matcher, reference_fingerprints):
    class FakeFingerprintDatabase:
        def __init__(self):
            self.cached = {b"melody": reference_fingerprints["melody"]}
            self.added = []

        def get_fingerprint(self, wem_bytes):
            return self.cached.get(wem_bytes)

        def add_fingerprint(self, wem_bytes, fingerprint):
            self.added.append(wem_bytes)

    stub_matcher.fingerprint_db = FakeFingerprintDatabase()
    candidates = [(b"melody", {"id": "melody"}), (b"log_chirp", {"id": "log_chirp"})]

    matches = stub_matcher.find_matches(reference_fingerprints["melody"], candidates)

    assert stub_matcher.extracted == [b"log_chirp"]
    assert stub_matcher.fingerprint_db.added == [b"log_chirp"]
    assert matches[0][1] == {"id": "melody"}
