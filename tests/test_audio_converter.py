import importlib
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

import src.audio.converter as converter_module
import src.audio.wwise_wrapper as wwise_wrapper
from src.audio.converter import AudioConverter
from src.audio.wwise_wrapper import WwiseConsole
from src.core import subprocess_utils
from src.core.app_config import APP_VERSION
from src.core.config_manager import get_tools_dir

FFMPEG_BUILD_EXE = ("audio", "ffmpeg", "ffmpeg-master-latest-win64-gpl", "bin", "ffmpeg.exe")
FFMPEG_PLAIN_EXE = ("audio", "ffmpeg", "bin", "ffmpeg.exe")
VGMSTREAM_EXE = ("audio", "vgmstream", "vgmstream-cli.exe")
WWISE_CONSOLE_EXE = ("WWIse", "Authoring", "x64", "Release", "bin", "WwiseConsole.exe")

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="the tools-dir lookup and the Wwise call are Windows-only")


def install_fake_tool(root, *parts):
    tool = Path(root).joinpath(*parts)
    tool.parent.mkdir(parents=True, exist_ok=True)
    tool.write_bytes(b"MZ")
    return tool


@pytest.fixture(autouse=True)
def no_bundled_wwise_project(tmp_path, monkeypatch):
    monkeypatch.setattr(wwise_wrapper, "_RESOURCE_DIR", tmp_path / "no_bundled_wwise_project")


@pytest.fixture
def tools_off_path(monkeypatch):
    monkeypatch.setattr(converter_module.shutil, "which", lambda name: None)


@pytest.fixture
def private_temp_dir(tmp_path, monkeypatch):
    temp_dir = tmp_path / "system_temp"
    temp_dir.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(temp_dir))
    return temp_dir


@pytest.fixture
def wwise_project(tmp_path):
    project_file = tmp_path / "project" / "WAVtoWEM" / "WAVtoWEM.wproj"
    project_file.parent.mkdir(parents=True)
    project_file.write_text("<WwiseDocument/>")
    return project_file


@pytest.fixture
def frozen_wwise_wrapper(tmp_path):
    bundled_resources = tmp_path / "bundle" / "resources"
    install_fake_tool(bundled_resources, "WAVtoWEM", "WAVtoWEM.wproj").write_text("<WwiseDocument bundled/>")
    with pytest.MonkeyPatch.context() as frozen_patch:
        frozen_patch.setattr(subprocess_utils, "is_frozen", lambda: True)
        frozen_patch.setattr(subprocess_utils, "get_bundled_resources_dir", lambda: bundled_resources)
        yield lambda: importlib.reload(wwise_wrapper)
    importlib.reload(wwise_wrapper)


@windows_only
@pytest.mark.parametrize(
    ("installed_tools", "expected_tool"),
    [([FFMPEG_BUILD_EXE, FFMPEG_PLAIN_EXE], FFMPEG_BUILD_EXE), ([FFMPEG_PLAIN_EXE], FFMPEG_PLAIN_EXE)],
    ids=["build_folder_first", "plain_bin_folder"],
)
def test_converter_finds_ffmpeg_in_the_tools_dir(tools_off_path, installed_tools, expected_tool):
    for tool_parts in installed_tools:
        install_fake_tool(get_tools_dir(), *tool_parts)
    assert AudioConverter().ffmpeg_path == str(get_tools_dir().joinpath(*expected_tool).resolve())


@windows_only
def test_converter_finds_vgmstream_in_the_tools_dir(tools_off_path):
    install_fake_tool(get_tools_dir(), *VGMSTREAM_EXE)
    assert AudioConverter().vgmstream_path == str(get_tools_dir().joinpath(*VGMSTREAM_EXE).resolve())


@windows_only
def test_converter_falls_back_to_the_tools_on_path(monkeypatch):
    path_tools = {"ffmpeg": "C:/path/ffmpeg.exe", "vgmstream-cli": "C:/path/vgmstream-cli.exe"}
    monkeypatch.setattr(converter_module.shutil, "which", path_tools.get)
    converter = AudioConverter()
    assert (converter.ffmpeg_path, converter.vgmstream_path) == ("C:/path/ffmpeg.exe", "C:/path/vgmstream-cli.exe")


@windows_only
def test_refresh_tools_picks_up_tools_installed_after_startup(tools_off_path):
    converter = AudioConverter()
    assert (converter.ffmpeg_path, converter.vgmstream_path) == (None, None)
    install_fake_tool(get_tools_dir(), *FFMPEG_PLAIN_EXE)
    install_fake_tool(get_tools_dir(), *VGMSTREAM_EXE)
    converter.refresh_tools()
    assert converter.ffmpeg_path.endswith("ffmpeg.exe")
    assert converter.vgmstream_path.endswith("vgmstream-cli.exe")


@windows_only
def test_conversions_without_tools_explain_how_to_install_them(tmp_path, tools_off_path):
    converter = AudioConverter()
    wav_file = tmp_path / "voice.wav"
    wav_file.write_bytes(b"RIFF")
    with pytest.raises(RuntimeError, match="Audio conversion tools not found"):
        converter.wem_to_wav(tmp_path / "voice.wem")
    with pytest.raises(RuntimeError, match="FFmpeg not found"):
        converter.any_to_wav(tmp_path / "voice.mp3", tmp_path / "voice_out.wav")
    with pytest.raises(RuntimeError, match="Wwise is not installed"):
        converter.wav_to_wem(wav_file)
    with pytest.raises(RuntimeError, match="Wwise is not installed"):
        converter.batch_convert_wav_to_wem(tmp_path)


@windows_only
@pytest.mark.xfail(strict=True, reason="bug: any_to_wav leaks its temp output .wav when FFmpeg is missing")
def test_any_to_wav_without_ffmpeg_leaves_no_temp_output(tmp_path, tools_off_path, private_temp_dir):
    wav_file = tmp_path / "voice.wav"
    wav_file.write_bytes(b"RIFF")
    with pytest.raises(RuntimeError, match="FFmpeg not found"):
        AudioConverter().any_to_wav(wav_file)
    assert list(private_temp_dir.iterdir()) == []


def test_wem_to_wav_falls_back_to_ffmpeg_when_vgmstream_fails(tmp_path, monkeypatch):
    commands = []

    def fake_run(command, **kwargs):
        commands.append(command[0])
        if command[0] == "vgmstream-cli.exe":
            raise subprocess.CalledProcessError(1, command)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(converter_module.subprocess, "run", fake_run)
    converter = AudioConverter()
    converter.ffmpeg_path, converter.vgmstream_path = "ffmpeg.exe", "vgmstream-cli.exe"

    assert converter.wem_to_wav(tmp_path / "voice.wem") == tmp_path / "voice.wav"
    assert commands == ["vgmstream-cli.exe", "ffmpeg.exe"]


def test_wem_to_wav_reports_a_wem_neither_tool_can_decode(tmp_path, monkeypatch):
    def failing_run(command, **kwargs):
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(converter_module.subprocess, "run", failing_run)
    converter = AudioConverter()
    converter.ffmpeg_path, converter.vgmstream_path = "ffmpeg.exe", "vgmstream-cli.exe"
    with pytest.raises(RuntimeError, match="Failed to convert voice.wem"):
        converter.wem_to_wav(tmp_path / "voice.wem", tmp_path / "out.wav")


def test_any_to_wem_sends_a_plain_wav_straight_to_wwise(tmp_path, monkeypatch):
    converter = AudioConverter()
    wwise_calls = []
    monkeypatch.setattr(converter, "any_to_wav", lambda *args, **kwargs: pytest.fail("a plain wav needs no re-encode"))
    monkeypatch.setattr(converter, "wav_to_wem", lambda wav_file, output_file=None: wwise_calls.append((Path(wav_file), output_file)) or output_file)

    assert converter.any_to_wem(tmp_path / "voice.wav", tmp_path / "voice.wem") == tmp_path / "voice.wem"
    assert wwise_calls == [(tmp_path / "voice.wav", tmp_path / "voice.wem")]


@pytest.mark.parametrize(("source_name", "normalize"), [("track.mp3", False), ("track.wav", True)])
def test_any_to_wem_reencodes_through_a_temp_wav_named_after_the_input(tmp_path, monkeypatch, private_temp_dir, source_name, normalize):
    converter = AudioConverter()
    reencodes = []

    def fake_any_to_wav(input_file, output_file, normalize, normalize_lufs):
        reencodes.append((Path(input_file).name, normalize, normalize_lufs))
        Path(output_file).write_bytes(b"RIFF wav")

    def fake_wav_to_wem(wav_file, output_file=None):
        wem_file = Path(wav_file).with_suffix(".wem")
        wem_file.write_bytes(b"RIFF wem")
        return wem_file

    monkeypatch.setattr(converter, "any_to_wav", fake_any_to_wav)
    monkeypatch.setattr(converter, "wav_to_wem", fake_wav_to_wem)
    source = tmp_path / "music" / source_name
    source.parent.mkdir()

    wem_file = converter.any_to_wem(source, normalize=normalize, normalize_lufs=-14)

    assert wem_file == source.with_suffix(".wem")
    assert wem_file.read_bytes() == b"RIFF wem"
    assert reencodes == [(source_name, normalize, -14)]
    assert list(private_temp_dir.iterdir()) == []


@windows_only
def test_wwise_console_is_installed_only_with_its_executable(tmp_path, wwise_project):
    wwise_dir = tmp_path / "wwise"
    assert not WwiseConsole(wwise_dir, wwise_project).is_installed()
    install_fake_tool(wwise_dir, *WWISE_CONSOLE_EXE)
    assert WwiseConsole(wwise_dir, wwise_project).is_installed()


def test_wwise_console_recreates_the_project_folders_the_bundle_omits(tmp_path, wwise_project):
    WwiseConsole(tmp_path / "wwise", wwise_project)
    for folder in ("GeneratedSoundBanks", "Originals", "Originals/ExternalSources", "Attenuations", "Conversion Settings", "Actor-Mixer Hierarchy"):
        assert (wwise_project.parent / folder).is_dir()


def test_wwise_console_leaves_a_missing_project_alone(tmp_path):
    missing_project = tmp_path / "missing" / "WAVtoWEM.wproj"
    WwiseConsole(tmp_path / "wwise", missing_project)
    assert not missing_project.parent.exists()


@windows_only
def test_wsources_file_lists_every_wav_against_one_root(tmp_path, wwise_project):
    wav_dir = tmp_path / "wavs"
    wav_dir.mkdir()
    console = WwiseConsole(tmp_path / "wwise", wwise_project)

    wsources_file = console._create_wsources_file([wav_dir / "a.wav", wav_dir / "b c.wav"], wav_dir, tmp_path)

    sources_list = ET.parse(wsources_file).getroot()
    assert sources_list.tag == "ExternalSourcesList"
    assert sources_list.get("Root") == str(wav_dir.resolve())
    assert [(source.get("Path"), source.get("Conversion")) for source in sources_list] == [
        ("a.wav", "Vorbis Quality High"), ("b c.wav", "Vorbis Quality High"),
    ]


@windows_only
def test_wwise_batch_calls_convert_external_source_on_the_project(tmp_path, wwise_project, monkeypatch):
    commands = []
    monkeypatch.setattr(wwise_wrapper.subprocess, "run", lambda command, **kwargs: commands.append(command) or subprocess.CompletedProcess(command, 0, "", ""))
    console = WwiseConsole(tmp_path / "wwise", wwise_project)
    output_dir = tmp_path / "out"
    output_dir.mkdir()

    console._run_wwise_batch([tmp_path / "voice.wav"], tmp_path, output_dir)

    assert commands == [[
        str(console.wwise_console), "convert-external-source", str(wwise_project.resolve()),
        "--source-file", str(output_dir / "list.wsources"), "--output", str(output_dir),
    ]]


def test_batch_convert_runs_wwise_once_per_source_folder_and_cleans_its_artifacts(tmp_path, wwise_project, monkeypatch):
    console = WwiseConsole(tmp_path / "wwise", wwise_project)
    wwise_runs = []

    def fake_wwise_batch(wav_files, wav_dir, output_dir):
        wwise_runs.append((wav_dir, [wav.name for wav in wav_files]))
        console._create_wsources_file(wav_files, wav_dir, output_dir)
        platform_dir = output_dir / "Windows"
        platform_dir.mkdir(exist_ok=True)
        for wav in wav_files:
            (platform_dir / wav.with_suffix(".wem").name).write_bytes(b"RIFF " + wav.name.encode())

    monkeypatch.setattr(console, "_run_wwise_batch", fake_wwise_batch)
    first_dir, second_dir, output_dir = tmp_path / "first", tmp_path / "second", tmp_path / "out"

    converted = console.batch_convert_to_wem([first_dir / "a.wav", second_dir / "b.wav", first_dir / "c.wav"], output_dir)

    assert wwise_runs == [(first_dir.resolve(), ["a.wav", "c.wav"]), (second_dir.resolve(), ["b.wav"])]
    assert converted == [output_dir.resolve() / name for name in ("a.wem", "c.wem", "b.wem")]
    assert (output_dir / "c.wem").read_bytes() == b"RIFF c.wav"
    assert sorted(path.name for path in output_dir.iterdir()) == ["a.wem", "b.wem", "c.wem"]


def test_collect_wems_falls_back_to_the_project_cache(tmp_path, wwise_project):
    console = WwiseConsole(tmp_path / "wwise", wwise_project)
    install_fake_tool(wwise_project.parent, ".cache", "Windows", "SFX", "voice.wem").write_bytes(b"RIFF cached")
    output_dir = tmp_path / "out"
    output_dir.mkdir()

    assert console._collect_wems([tmp_path / "voice.wav"], output_dir) == [output_dir / "voice.wem"]
    assert (output_dir / "voice.wem").read_bytes() == b"RIFF cached"


def test_convert_to_wem_raises_when_wwise_writes_nothing(tmp_path, wwise_project, monkeypatch):
    console = WwiseConsole(tmp_path / "wwise", wwise_project)
    monkeypatch.setattr(console, "_run_wwise_batch", lambda wav_files, wav_dir, output_dir: None)
    wav_file = tmp_path / "voice.wav"
    wav_file.write_bytes(b"RIFF")
    with pytest.raises(RuntimeError, match="WEM file not created from voice.wav"):
        console.convert_to_wem(wav_file, tmp_path / "out")


def test_frozen_build_copies_the_wwise_project_per_version_and_drops_older_copies(frozen_wwise_wrapper):
    project_copies = get_tools_dir() / "wwise_project"
    (project_copies / "1.0.0" / "WAVtoWEM").mkdir(parents=True)
    (project_copies / "0.9.0").mkdir()

    reloaded = frozen_wwise_wrapper()

    current_copy = project_copies / APP_VERSION
    assert reloaded._RESOURCE_DIR == current_copy
    assert (current_copy / "WAVtoWEM" / "WAVtoWEM.wproj").read_text() == "<WwiseDocument bundled/>"
    assert [path.name for path in project_copies.iterdir()] == [APP_VERSION]
    assert reloaded.WwiseConsole().project_path == (current_copy / "WAVtoWEM" / "WAVtoWEM.wproj").resolve()


def test_frozen_build_keeps_an_existing_copy_of_the_current_version(frozen_wwise_wrapper):
    project_copies = get_tools_dir() / "wwise_project"
    install_fake_tool(project_copies, APP_VERSION, "WAVtoWEM", "WAVtoWEM.wproj").write_text("<WwiseDocument local/>")
    (project_copies / "0.9.0").mkdir()

    frozen_wwise_wrapper()

    assert (project_copies / APP_VERSION / "WAVtoWEM" / "WAVtoWEM.wproj").read_text() == "<WwiseDocument local/>"
    assert sorted(path.name for path in project_copies.iterdir()) == sorted(["0.9.0", APP_VERSION])
