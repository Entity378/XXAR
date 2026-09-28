import sys
from pathlib import Path

from src.core import paths
from src.core.paths import get_base_path, get_temp_dir

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_base_path_is_the_project_root_in_source_mode():
    assert get_base_path() == PROJECT_ROOT


def test_base_path_is_meipass_when_frozen(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert get_base_path() == tmp_path


def test_source_temp_dir_lives_in_the_project_root(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "_PROJECT_ROOT", tmp_path)
    assert get_temp_dir() == tmp_path / "temp"
    assert (tmp_path / "temp").is_dir()


def test_frozen_temp_dir_lives_in_local_appdata(monkeypatch, tmp_path, isolated_user_dirs):
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "bundle"), raising=False)
    assert get_temp_dir() == isolated_user_dirs.data_dir / "temp"
    assert get_temp_dir().is_dir()


def test_flatpak_temp_dir_lives_in_xdg_data_home(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "IS_FLATPAK", True)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg_data"))
    assert get_temp_dir() == tmp_path / "xdg_data" / "XXAR" / "temp"
