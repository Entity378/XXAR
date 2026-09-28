# Boots the real XXAR app offscreen, walks every page for every game, quits and writes a JSON report.
# Run in a subprocess by test_gui_smoke.py with APPDATA/LOCALAPPDATA already pointing at a throwaway root.

import json
import os
import socket
import sys
import threading
import traceback
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
GAME_ORDER = ("zzz", "genshin", "hsr", "zzz")
TAB_ORDER = (0, 1, 2, 5, 3, 4)
WATCHDOG_SECONDS = 150

report = {
    "exit_code": None,
    "root_window": None,
    "visited": [],
    "messages": [],
    "engine_warnings": [],
    "workers_alive_at_quit": [],
    "workers_running_after_quit": [],
    "registries_not_empty": [],
    "game_lock_holder_after_quit": None,
    "blocked_urls": [],
    "scenario_error": None,
}


def write_report(report_path):
    Path(report_path).write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")


def block_network():
    # Loopback stays reachable so the dead update override URL fails fast like it does in production.
    real_getaddrinfo = socket.getaddrinfo

    def guarded_getaddrinfo(host, *args, **kwargs):
        if host not in ("127.0.0.1", "localhost", "::1"):
            raise socket.gaierror(f"network disabled in the GUI smoke test: {host}")
        return real_getaddrinfo(host, *args, **kwargs)

    def offline_urlopen(request, *args, **kwargs):
        url = getattr(request, "full_url", request)
        report["blocked_urls"].append(str(url))
        raise urllib.error.URLError("network disabled in the GUI smoke test")

    socket.getaddrinfo = guarded_getaddrinfo
    urllib.request.urlopen = offline_urlopen


def install_message_handler():
    from PyQt6.QtCore import QtMsgType, qInstallMessageHandler

    names = {
        QtMsgType.QtDebugMsg: "debug",
        QtMsgType.QtInfoMsg: "info",
        QtMsgType.QtWarningMsg: "warning",
        QtMsgType.QtCriticalMsg: "critical",
        QtMsgType.QtFatalMsg: "fatal",
    }

    def handler(msg_type, context, text):
        report["messages"].append({
            "type": names.get(msg_type, str(msg_type)),
            "category": context.category or "",
            "file": context.file or "",
            "line": context.line,
            "text": text,
        })

    qInstallMessageHandler(handler)


def pump(seconds):
    from PyQt6.QtCore import QEventLoop, QTimer

    loop = QEventLoop()
    QTimer.singleShot(int(seconds * 1000), loop.quit)
    loop.exec()


def pump_until(predicate, timeout):
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        pump(0.05)
    return predicate()


def live_workers():
    from src.gui.backend import base_worker

    workers = []
    for ref in list(base_worker._registries):
        registry = ref()
        if registry is None:
            continue
        for name, worker in list(registry._workers.items()):
            workers.append((registry._owner_name, name, worker))
    return workers


def run_scenario(application):
    from src.gui.backend.base_worker import game_lock_holder

    root = application.root
    report["root_window"] = {
        "class": root.metaObject().className(),
        "title": root.property("title"),
        "visible": root.property("visible"),
        "width": root.property("width"),
        "height": root.property("height"),
    }
    pump(1.5)
    short_labels = {"zzz": "ZZZ", "genshin": "GI", "hsr": "HSR"}
    for game_id in GAME_ORDER:
        if root.property("activeGameShort") != short_labels[game_id]:
            root.selectGameRequested.emit(game_id)
        switched = pump_until(
            lambda: root.property("activeGameShort") == short_labels[game_id]
            and not root.property("gameSwitchInProgress")
            and game_lock_holder(skip_current_thread=False) is None,
            timeout=15,
        )
        pump(1.0)
        for tab in TAB_ORDER:
            root.setProperty("currentTab", tab)
            pump(0.4)
            report["visited"].append({
                "game": game_id,
                "switched": switched,
                "active_game_short": root.property("activeGameShort"),
                "tab": tab,
                "current_tab": root.property("currentTab"),
            })


def main():
    report_path = sys.argv[1]
    sys.path.insert(0, str(REPO_ROOT))
    os.chdir(REPO_ROOT)
    block_network()

    # In source mode the app's temp dir sits in the repo; the smoke test keeps it inside the throwaway root.
    import src.core.paths as paths
    paths._PROJECT_ROOT = Path(os.environ["XXAR_SMOKE_PROJECT_ROOT"])

    def abort_hung_run():
        report["scenario_error"] = "watchdog timeout"
        write_report(report_path)
        os._exit(3)

    watchdog = threading.Timer(WATCHDOG_SECONDS, abort_hung_run)
    watchdog.daemon = True
    watchdog.start()

    import XXAR
    import src.gui.main_qml as main_qml
    from PyQt6.QtQml import QQmlApplicationEngine
    from PyQt6.QtWidgets import QApplication

    # main_qml forces the Windows platform plugin on import; the smoke test must stay offscreen.
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    install_message_handler()

    class RecordingEngine(QQmlApplicationEngine):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.warnings.connect(lambda errors: report["engine_warnings"].extend(error.toString() for error in errors))

    main_qml.QQmlApplicationEngine = RecordingEngine
    application = XXAR.Application(version=XXAR.__version__)
    real_exec = QApplication.exec

    def scripted_exec(qt_app):
        from PyQt6.QtCore import QTimer
        from src.gui.backend.base_worker import game_lock_holder

        snapshot = []

        def scenario():
            from src.gui.backend.base_worker import FunctionWorker

            try:
                run_scenario(application)
            except Exception:
                report["scenario_error"] = traceback.format_exc()
            # A worker still busy at quit time proves that aboutToQuit cancels and joins it.
            probe_cancel = threading.Event()
            application._app_workers.start("smoke_probe", FunctionWorker(lambda: probe_cancel.wait(60), cancel_event=probe_cancel))
            snapshot.extend(live_workers())
            report["workers_alive_at_quit"] = [f"{owner}/{name}" for owner, name, worker in snapshot if worker.isRunning()]
            qt_app.quit()

        QTimer.singleShot(0, scenario)
        exit_code = real_exec()
        for owner, name, worker in snapshot:
            try:
                running = worker.isRunning()
            except RuntimeError:
                running = False
            if running:
                report["workers_running_after_quit"].append(f"{owner}/{name}")
        report["registries_not_empty"] = [f"{owner}/{name}" for owner, name, _ in live_workers()]
        report["game_lock_holder_after_quit"] = game_lock_holder(skip_current_thread=False)
        return exit_code

    QApplication.exec = scripted_exec
    try:
        report["exit_code"] = application.run()
    except SystemExit as exit_request:
        report["exit_code"] = exit_request.code
    except Exception:
        report["scenario_error"] = traceback.format_exc()
    watchdog.cancel()
    write_report(report_path)
    return 0 if report["exit_code"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
