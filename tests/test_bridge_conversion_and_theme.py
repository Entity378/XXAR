import threading

import pytest

from helpers import record_signal, wait_until


class FakeConverter:
    calls = []
    failure = None
    gate = None

    def _record(self, method, *args, **kwargs):
        if FakeConverter.gate is not None:
            FakeConverter.gate.wait(10)
        if FakeConverter.failure:
            raise RuntimeError(FakeConverter.failure)
        FakeConverter.calls.append((method, args, kwargs))

    def wem_to_wav(self, input_file, output_file=None):
        self._record("wem_to_wav", input_file, output_file)
        return output_file or "out.wav"

    def any_to_wav(self, input_file, output_file=None, sample_rate=48000, normalize=True, normalize_lufs=-9):
        self._record("any_to_wav", input_file, output_file, sample_rate=sample_rate, normalize=normalize, normalize_lufs=normalize_lufs)
        return output_file or "out.wav"

    def any_to_wem(self, input_file, output_file=None, normalize=True, normalize_lufs=-9):
        self._record("any_to_wem", input_file, output_file, normalize=normalize, normalize_lufs=normalize_lufs)
        return output_file or "out.wem"

    def batch_convert_wem_to_wav(self, input_dir, output_dir=None):
        self._record("batch_convert_wem_to_wav", input_dir, output_dir)
        return ["a.wav", "b.wav"]


@pytest.fixture
def conversion(qapp, monkeypatch):
    from src.gui.backend import audio_conversion_bridge

    FakeConverter.calls = []
    FakeConverter.failure = None
    FakeConverter.gate = None
    monkeypatch.setattr(audio_conversion_bridge, "AudioConverter", FakeConverter)
    bridge = audio_conversion_bridge.AudioConversionBridge()
    yield bridge
    if FakeConverter.gate is not None:
        FakeConverter.gate.set()
    bridge._workers.shutdown()


def convert_and_wait(bridge, *args):
    finished = record_signal(bridge.conversionFinished)
    bridge.convertAudio(*args)
    assert wait_until(lambda: finished and not bridge._workers.is_running("convert"))


@pytest.mark.parametrize(
    ("input_path", "expected_message"),
    [("", "Please select an input file or directory"), ("C:/definitely/missing/input.wem", "Input path does not exist:\nC:/definitely/missing/input.wem")],
)
def test_convert_rejects_a_missing_input(conversion, input_path, expected_message):
    errors = record_signal(conversion.errorOccurred)
    started = record_signal(conversion.conversionStarted)

    conversion.convertAudio(0, input_path, "", 48000, True, -9)

    assert errors == [("Error", expected_message)]
    assert started == []


@pytest.mark.parametrize(
    ("mode", "suffix", "expected_call"),
    [
        (0, ".wem", ("wem_to_wav", {})),
        (1, ".mp3", ("any_to_wav", {"sample_rate": 44100, "normalize": False, "normalize_lufs": -14})),
        (2, ".wav", ("any_to_wem", {"normalize": False, "normalize_lufs": -14})),
    ],
)
def test_convert_runs_the_mode_and_reports_success(conversion, tmp_path, mode, suffix, expected_call):
    source = tmp_path / f"voice{suffix}"
    source.write_bytes(b"audio")
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    started = record_signal(conversion.conversionStarted)
    logs = record_signal(conversion.logMessage)
    successes = record_signal(conversion.conversionSuccess)

    convert_and_wait(conversion, mode, str(source), str(output_dir), 44100, False, -14)

    output_suffix = ".wem" if mode == 2 else ".wav"
    expected_output = str(output_dir / f"voice{output_suffix}")
    assert started == [()]
    assert [(method, args, kwargs) for method, args, kwargs in FakeConverter.calls] == [
        (expected_call[0], (str(source), expected_output), expected_call[1])
    ]
    assert successes == [("Conversion Complete", f"Converted to: {expected_output}")]
    assert logs[0] == (f"Input: {source}",)
    assert ("Normalize: Off",) in logs


def test_convert_a_directory_uses_the_batch_converter(conversion, tmp_path):
    successes = record_signal(conversion.conversionSuccess)

    convert_and_wait(conversion, 0, str(tmp_path), "", 48000, True, -9)

    assert FakeConverter.calls[0][0] == "batch_convert_wem_to_wav"
    assert successes == [("Conversion Complete", "Converted 2 WEM files to WAV")]


def test_a_converter_failure_opens_the_error_dialog(conversion, tmp_path):
    source = tmp_path / "voice.wem"
    source.write_bytes(b"audio")
    FakeConverter.failure = "vgmstream exploded"
    dialogs = record_signal(conversion.conversionErrorDialog)

    convert_and_wait(conversion, 0, str(source), "", 48000, True, -9)

    assert dialogs == [("Conversion Error", "Conversion failed:\nvgmstream exploded")]


def test_a_second_conversion_is_refused_while_one_runs(conversion, tmp_path):
    source = tmp_path / "voice.wem"
    source.write_bytes(b"audio")
    FakeConverter.gate = threading.Event()
    errors = record_signal(conversion.errorOccurred)
    finished = record_signal(conversion.conversionFinished)

    conversion.convertAudio(0, str(source), "", 48000, True, -9)
    conversion.convertAudio(0, str(source), "", 48000, True, -9)
    FakeConverter.gate.set()

    assert errors == [("Busy", "A conversion is already in progress.")]
    assert wait_until(lambda: finished and not conversion._workers.is_running("convert"))
    assert len(FakeConverter.calls) == 1


@pytest.fixture
def theme(qapp):
    from src.gui.backend.ui_theme_bridge import UIThemeBridge

    return UIThemeBridge("zzz")


def theme_properties(bridge):
    return tuple(bridge.property(name) for name in ("gameId", "accentColor", "accentColorLight", "accentColorDark"))


def test_theme_starts_on_the_requested_game(qapp):
    from src.gui.backend.ui_theme_bridge import UIThemeBridge

    assert theme_properties(UIThemeBridge("hsr")) == ("hsr", "#3f9ec3", "#62b8d8", "#2d7a99")


def test_theme_switch_notifies_qml_once(theme):
    changes = record_signal(theme.themeChanged)

    theme.setThemeForGame("genshin")
    theme.setThemeForGame("genshin")

    assert changes == [()]
    assert theme_properties(theme) == ("genshin", "#34c27a", "#6fe3a5", "#238a58")


def test_unknown_game_falls_back_to_the_default_palette(theme):
    theme.setThemeForGame("genshin")

    theme.setThemeForGame("not-a-game")

    assert theme_properties(theme) == ("zzz", "#d8fa00", "#e8ff33", "#a8c800")
