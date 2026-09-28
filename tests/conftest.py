import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

REAL_APPDATA = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
REAL_LOCALAPPDATA = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
REAL_SETTINGS_FILE = REAL_APPDATA / "XXAR" / "settings.json"
REAL_TOOLS_DIR = REAL_LOCALAPPDATA / "XXAR" / "tools"
REAL_GAME_TESTS_ENABLED = os.environ.get("XXAR_REAL_GAME_TESTS") == "1"

# Every user dir points at a throwaway root before src is imported, so no test can reach the real XXAR config.
_SESSION_ROOT = Path(tempfile.mkdtemp(prefix="xxar_tests_"))
os.environ["APPDATA"] = str(_SESSION_ROOT / "Roaming")
os.environ["LOCALAPPDATA"] = str(_SESSION_ROOT / "Local")
os.environ["XDG_CONFIG_HOME"] = str(_SESSION_ROOT / "Roaming")
os.environ["XDG_DATA_HOME"] = str(_SESSION_ROOT / "Local")
os.environ["QML_DISK_CACHE_PATH"] = str(_SESSION_ROOT / "Local" / "XXAR" / "cache" / "qml")
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QT_QUICK_CONTROLS_STYLE"] = "Basic"
os.environ["XXAR_UPDATE_API_URL_OVERRIDE"] = "http://127.0.0.1:9/xxar-tests-no-network"
os.environ.pop("XXAR_UPDATE_FORCE_PORTABLE", None)


def pytest_collection_modifyitems(config, items):
    if REAL_GAME_TESTS_ENABLED:
        return
    skip_real_game = pytest.mark.skip(reason="set XXAR_REAL_GAME_TESTS=1 to read the installed games")
    for item in items:
        if "real_game" in item.keywords:
            item.add_marker(skip_real_game)


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(_SESSION_ROOT, ignore_errors=True)


@pytest.fixture(autouse=True)
def isolated_user_dirs(tmp_path, monkeypatch):
    from src.core import config_manager
    import src.core.app_config as app_config
    from src.core.game_registry import DEFAULT_GAME_ID

    roaming = tmp_path / "user" / "Roaming"
    local = tmp_path / "user" / "Local"
    monkeypatch.setenv("APPDATA", str(roaming))
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(roaming))
    monkeypatch.setenv("XDG_DATA_HOME", str(local))
    monkeypatch.setattr(config_manager, "_config_manager", config_manager.ConfigManager())
    app_config.switch_active_game(DEFAULT_GAME_ID)
    yield SimpleNamespace(config_dir=roaming / "XXAR", data_dir=local / "XXAR")
    app_config.switch_active_game(DEFAULT_GAME_ID)


@pytest.fixture(autouse=True)
def isolated_app_temp_dir(tmp_path, monkeypatch):
    # Source runs put the app temp dir inside the repo, so every module holding get_temp_dir gets a tmp one.
    from src.core import paths

    app_temp_dir = tmp_path / "app_temp"

    def get_isolated_temp_dir():
        app_temp_dir.mkdir(parents=True, exist_ok=True)
        return app_temp_dir

    original_get_temp_dir = paths.get_temp_dir
    for module_name, module in list(sys.modules.items()):
        if module_name.startswith("src.") and getattr(module, "get_temp_dir", None) is original_get_temp_dir:
            monkeypatch.setattr(module, "get_temp_dir", get_isolated_temp_dir)
    return app_temp_dir


@pytest.fixture(autouse=True)
def no_native_dialogs(monkeypatch):
    from src.gui.utils.native_dialogs import NativeDialogs

    def refuse_dialog(*args, **kwargs):
        raise AssertionError("a test tried to open a native file dialog")

    for dialog_name in ("get_open_file", "get_open_files", "get_save_file", "get_directory"):
        monkeypatch.setattr(NativeDialogs, dialog_name, staticmethod(refuse_dialog))


@pytest.fixture(autouse=True)
def empty_original_id_index_cache():
    from src.wwise.original_id_index import clear_cache

    clear_cache()
    yield
    clear_cache()


@pytest.fixture(scope="session")
def qapp():
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(["xxar-tests"])
    yield app


@pytest.fixture(scope="session")
def real_tools_dir():
    if not REAL_TOOLS_DIR.is_dir():
        pytest.skip(f"XXAR tools are not installed in {REAL_TOOLS_DIR}")
    return REAL_TOOLS_DIR


def _snapshot_tree(roots):
    snapshot = {}
    for root in roots:
        for path in root.rglob("*"):
            if path.is_file():
                stat = path.stat()
                snapshot[str(path)] = (stat.st_size, stat.st_mtime_ns)
    return snapshot


@pytest.fixture(scope="session")
def real_game_audio_dirs():
    # Read-only view of the installed games; the session fails if any of their files changed.
    if not REAL_GAME_TESTS_ENABLED:
        pytest.skip("set XXAR_REAL_GAME_TESTS=1 to read the installed games")
    if not REAL_SETTINGS_FILE.exists():
        pytest.skip(f"no XXAR settings at {REAL_SETTINGS_FILE}")
    from src.core.game_registry import get_audio_settings_keys, get_supported_game_ids

    real_settings = json.loads(REAL_SETTINGS_FILE.read_text(encoding="utf-8"))
    audio_dirs = {}
    for game_id in get_supported_game_ids():
        streaming_key, persistent_key = get_audio_settings_keys(game_id)
        streaming_root = Path(real_settings.get(streaming_key) or "")
        if not real_settings.get(streaming_key) or not streaming_root.is_dir():
            continue
        persistent_root = Path(real_settings.get(persistent_key) or "")
        audio_dirs[game_id] = SimpleNamespace(
            game_id=game_id,
            streaming_root=streaming_root,
            persistent_root=persistent_root if real_settings.get(persistent_key) else None,
        )
    if not audio_dirs:
        pytest.skip("no installed game configured in the real XXAR settings")

    watched_roots = [dirs.streaming_root for dirs in audio_dirs.values()]
    watched_roots += [dirs.persistent_root for dirs in audio_dirs.values() if dirs.persistent_root and dirs.persistent_root.is_dir()]
    before = _snapshot_tree(watched_roots)
    yield audio_dirs
    after = _snapshot_tree(watched_roots)
    changed = sorted(path for path in set(before) | set(after) if before.get(path) != after.get(path))
    assert not changed, f"tests modified installed game files: {changed[:20]}"
