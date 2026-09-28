import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from bridge_helpers import STREAMED_PCK, make_genshin_install, make_hsr_install, make_zzz_install, write_mod_package
from helpers import make_wem

pytestmark = [pytest.mark.gui, pytest.mark.slow]

REPO_ROOT = Path(__file__).resolve().parent.parent
DRIVER = Path(__file__).with_name("gui_driver.py")
GAME_SHORT_LABELS = {"zzz": "ZZZ", "genshin": "GI", "hsr": "HSR"}
QML_ERROR_PATTERNS = ("TypeError", "ReferenceError", "is not a type", "Binding loop", "Cannot read property", "Unable to assign", "is not defined")


def smoke_settings(installs):
    from src.core.game_registry import get_audio_settings_keys

    settings = {
        "selected_game": "zzz",
        "first_launch_complete": True,
        "mod_creation_mode": True,
        "hirc_editor_enabled": True,
        "language": "en",
        "auto_check_updates": False,
        "enable_gb_thumbnails": False,
        "tag_db_notify_dismissed": True,
    }
    for install in installs:
        streaming_key, persistent_key = get_audio_settings_keys(install.game.id)
        settings[streaming_key] = str(install.streaming_root)
        settings[persistent_key] = str(install.persistent_root)
    settings["game_audio_dir"] = settings["zzz_game_audio_dir"]
    settings["persistent_audio_dir"] = settings["zzz_persistent_audio_dir"]
    return settings


def smoke_env(root):
    env = dict(os.environ)
    env.pop("XXAR_UPDATE_FORCE_PORTABLE", None)
    env.update({
        "APPDATA": str(root / "Roaming"),
        "LOCALAPPDATA": str(root / "Local"),
        "XDG_CONFIG_HOME": str(root / "Roaming"),
        "XDG_DATA_HOME": str(root / "Local"),
        "QML_DISK_CACHE_PATH": str(root / "Local" / "XXAR" / "cache" / "qml"),
        "QT_QPA_PLATFORM": "offscreen",
        "QT_QUICK_CONTROLS_STYLE": "Basic",
        "XXAR_UPDATE_API_URL_OVERRIDE": "http://127.0.0.1:9/xxar-tests-no-network",
        "XXAR_SMOKE_PROJECT_ROOT": str(root / "project"),
        "XXAR_LOG_LEVEL": "INFO",
    })
    return env


def install_enabled_mod(root, env):
    from src.core import config_manager
    from src.mods.package_manager import ModPackageManager

    package = write_mod_package(root / "packages" / "Smoke Mod.zzar", "Smoke Mod", {STREAMED_PCK: {21: make_wem(3, 256)}})
    with pytest.MonkeyPatch.context() as patch:
        for name in ("APPDATA", "LOCALAPPDATA", "XDG_CONFIG_HOME", "XDG_DATA_HOME"):
            patch.setenv(name, env[name])
        patch.setattr(config_manager, "_config_manager", config_manager.ConfigManager())
        manager = ModPackageManager(mod_library_path=config_manager.get_game_mod_library_dir("zzz"), game_id="zzz")
        mod_uuid = manager.install_mod(package)["uuid"]
        manager.set_mod_enabled(mod_uuid, True)


@pytest.fixture(scope="module")
def smoke_report(tmp_path_factory):
    root = tmp_path_factory.mktemp("gui_smoke")
    (root / "project").mkdir()
    installs = [make_zzz_install(root / "games"), make_genshin_install(root / "games"), make_hsr_install(root / "games")]
    settings_file = root / "Roaming" / "XXAR" / "settings.json"
    settings_file.parent.mkdir(parents=True)
    settings_file.write_text(json.dumps(smoke_settings(installs), indent=2), encoding="utf-8")
    env = smoke_env(root)
    install_enabled_mod(root, env)
    report_path = root / "report.json"

    completed = subprocess.run(
        [sys.executable, str(DRIVER), str(report_path)],
        cwd=REPO_ROOT, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=240,
    )
    (root / "driver_output.txt").write_text(completed.stdout + "\n--- stderr ---\n" + completed.stderr, encoding="utf-8")
    assert report_path.exists(), f"driver wrote no report (exit {completed.returncode}):\n{completed.stderr[-4000:]}"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["returncode"] = completed.returncode
    report["output_file"] = str(root / "driver_output.txt")
    return report


def qml_problems(report):
    problems = list(report["engine_warnings"])
    for message in report["messages"]:
        if message["type"] not in ("warning", "critical", "fatal"):
            continue
        from_qml = message["file"].endswith(".qml") or ".qml:" in message["text"] or message["category"] in ("qml", "js")
        if from_qml:
            problems.append(message["text"])
    return sorted(set(problems))


def is_gamebanana_link_hover_warning(problem):
    return "GameBananaModDialog.qml" in problem and "Unable to assign [undefined] to bool" in problem


def is_half_switched_logo_warning(problem):
    return "MainWindow.qml" in problem and "QQuickImage: Cannot open" in problem and "-Logo2-256.png" in problem


def unexplained_qml_problems(report):
    known_bugs = (is_gamebanana_link_hover_warning, is_half_switched_logo_warning)
    return [problem for problem in qml_problems(report) if not any(is_known(problem) for is_known in known_bugs)]


def test_app_boots_offscreen_and_exits_cleanly(smoke_report):
    assert smoke_report["scenario_error"] is None, smoke_report["scenario_error"]
    assert smoke_report["exit_code"] == 0
    assert smoke_report["returncode"] == 0, f"see {smoke_report['output_file']}"
    root_window = smoke_report["root_window"]
    assert root_window["class"].startswith("MainWindow")
    assert root_window["title"].startswith("XXAR - ")
    assert root_window["visible"] is True


def test_every_page_is_shown_for_every_game(smoke_report):
    visited = [(entry["game"], entry["tab"]) for entry in smoke_report["visited"]]

    assert visited == [(game_id, tab) for game_id in ("zzz", "genshin", "hsr", "zzz") for tab in (0, 1, 2, 5, 3, 4)]
    assert all(entry["switched"] for entry in smoke_report["visited"])
    assert all(entry["current_tab"] == entry["tab"] for entry in smoke_report["visited"])
    assert all(entry["active_game_short"] == GAME_SHORT_LABELS[entry["game"]] for entry in smoke_report["visited"])


def test_shutdown_leaves_no_worker_running(smoke_report):
    assert "application/smoke_probe" in smoke_report["workers_alive_at_quit"]
    assert smoke_report["workers_running_after_quit"] == []
    assert smoke_report["registries_not_empty"] == []
    assert smoke_report["game_lock_holder_after_quit"] is None


def test_no_unexpected_errors_are_logged(smoke_report):
    output = Path(smoke_report["output_file"]).read_text(encoding="utf-8")
    error_lines = [line for line in output.splitlines() if "[ERROR]" in line or "[CRITICAL]" in line or "Traceback" in line]

    assert [line for line in error_lines if "network disabled in the GUI smoke test" not in line] == []


@pytest.mark.parametrize("pattern", QML_ERROR_PATTERNS)
def test_no_qml_errors_of_a_known_kind(smoke_report, pattern):
    assert [problem for problem in unexplained_qml_problems(smoke_report) if pattern in problem] == []


def test_no_other_qml_warnings(smoke_report):
    other = [problem for problem in unexplained_qml_problems(smoke_report) if not any(pattern in problem for pattern in QML_ERROR_PATTERNS)]

    assert other == []


def test_gamebanana_link_hover_binds_an_existing_property(smoke_report):
    assert [problem for problem in qml_problems(smoke_report) if is_gamebanana_link_hover_warning(problem)] == []


def test_game_switch_never_loads_a_missing_logo(smoke_report):
    assert [problem for problem in qml_problems(smoke_report) if is_half_switched_logo_warning(problem)] == []


def test_the_logo_follows_every_game_switch(smoke_report):
    from src.core.game_registry import get_game

    for entry in smoke_report["visited"]:
        game = get_game(entry["game"])
        assert entry["logo_source"] == f"../assets/{game.assets_dir}/{game.logo_256}"
