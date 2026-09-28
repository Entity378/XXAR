import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

from src.core import subprocess_utils
from src.core.subprocess_utils import (
    SUBPROCESS_KWARGS,
    get_bundle_root,
    get_bundled_resource,
    get_bundled_resources_dir,
    is_frozen,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
windows_only = pytest.mark.skipif(sys.platform != "win32", reason="Windows-only process flags")


def load_fresh_subprocess_utils():
    spec = importlib.util.spec_from_file_location("fresh_subprocess_utils", subprocess_utils.__file__)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_source_mode_resolves_the_project_tree():
    assert not is_frozen()
    assert get_bundle_root() == PROJECT_ROOT
    assert get_bundled_resources_dir() == PROJECT_ROOT / "src" / "resources"


def test_bundled_resource_returns_shipped_files_only():
    assert get_bundled_resource("WAVtoWEM", "WAVtoWEM.wproj") == PROJECT_ROOT / "src" / "resources" / "WAVtoWEM" / "WAVtoWEM.wproj"
    assert get_bundled_resource("WAVtoWEM", "missing.wproj") is None


def test_onefile_bundle_resolves_under_meipass(monkeypatch, tmp_path):
    (tmp_path / "resources" / "WAVtoWEM").mkdir(parents=True)
    (tmp_path / "resources" / "WAVtoWEM" / "WAVtoWEM.wproj").write_text("<proj/>", encoding="utf-8")
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert is_frozen()
    assert get_bundle_root() == tmp_path
    assert get_bundled_resources_dir() == tmp_path / "resources"
    assert get_bundled_resource("WAVtoWEM", "WAVtoWEM.wproj") == tmp_path / "resources" / "WAVtoWEM" / "WAVtoWEM.wproj"


def test_onefolder_bundle_resolves_next_to_the_executable(monkeypatch, tmp_path):
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "XXAR.exe"))
    assert is_frozen()
    assert get_bundle_root() == tmp_path.resolve()
    assert get_bundled_resources_dir() == tmp_path.resolve() / "resources"


@windows_only
def test_subprocess_kwargs_hide_the_console_window():
    startupinfo = SUBPROCESS_KWARGS["startupinfo"]
    assert startupinfo.dwFlags & subprocess.STARTF_USESHOWWINDOW
    assert "env" not in SUBPROCESS_KWARGS


@windows_only
def test_frozen_subprocess_kwargs_strip_meipass_from_path(monkeypatch, tmp_path):
    meipass = str(tmp_path / "_MEI12345")
    kept_entries = [r"C:\Windows\System32", str(tmp_path / "tools")]
    monkeypatch.setattr(sys, "_MEIPASS", meipass, raising=False)
    monkeypatch.setenv("PATH", os.pathsep.join([meipass, kept_entries[0], meipass + r"\PyQt6\Qt6\bin", kept_entries[1]]))
    fresh_module = load_fresh_subprocess_utils()
    child_env = fresh_module.SUBPROCESS_KWARGS["env"]
    assert child_env["PATH"].split(os.pathsep) == kept_entries
    assert fresh_module.SUBPROCESS_KWARGS["startupinfo"].dwFlags & subprocess.STARTF_USESHOWWINDOW
    assert os.environ["PATH"].startswith(meipass)


def test_host_spawn_kwargs_extend_the_subprocess_kwargs():
    for key, value in SUBPROCESS_KWARGS.items():
        assert subprocess_utils.HOST_SPAWN_KWARGS[key] is value


def test_flatpak_detection_follows_the_environment(monkeypatch):
    monkeypatch.setenv("XXAR_FLATPAK", "1")
    assert load_fresh_subprocess_utils().IS_FLATPAK
