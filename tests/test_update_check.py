import io
import json
import socket
import sys
import tarfile
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.core.app_config import APP_VERSION
from src.core.config_manager import get_updates_dir
from src.gui.backend import update_manager_bridge
from src.gui.backend.update_manager_bridge import UpdateCheckWorker, UpdateDownloadWorker, UpdateManagerBridge
from helpers import read_settings, record_signal, wait_until, write_settings

RELEASE_NOTES = "Fixed things."
OLDER_VERSION = "1.0.0"
NEWER_TAG = "v99.0.0"
NEWER_VERSION = "99.0.0"


class ReleaseServer:
    def __init__(self):
        self.routes = {}
        self.requests = []
        self.response_gate = None
        release_server = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                release_server.requests.append(SimpleNamespace(path=self.path, headers=dict(self.headers)))
                if release_server.response_gate is not None:
                    release_server.response_gate.wait(10)
                status, body = release_server.routes.get(self.path, (404, b'{"message": "Not Found"}'))
                self.send_response(status)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
        self.thread.start()

    def url(self, path):
        return f"http://127.0.0.1:{self.httpd.server_address[1]}{path}"

    def serve_bytes(self, path, body, status=200):
        self.routes[path] = (status, body)

    def serve_release(self, tag, asset_names, status=200):
        assets = [
            {"name": name, "browser_download_url": self.url(f"/download/{name}"), "url": self.url(f"/api/assets/{name}")}
            for name in asset_names
        ]
        release = {"tag_name": tag, "body": RELEASE_NOTES, "assets": assets}
        self.serve_bytes("/releases/latest", json.dumps(release).encode(), status)

    def close(self):
        if self.response_gate is not None:
            self.response_gate.set()
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(5)


@pytest.fixture
def release_server(monkeypatch):
    for proxy_variable in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
        monkeypatch.delenv(proxy_variable, raising=False)
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    server = ReleaseServer()
    monkeypatch.setattr(update_manager_bridge, "GITHUB_API_URL", server.url("/releases/latest"))
    yield server
    server.close()


@pytest.fixture(autouse=True)
def portable_by_default(monkeypatch):
    # The real registry is never read; tests opt into a managed install explicitly.
    monkeypatch.delenv("XXAR_UPDATE_FORCE_PORTABLE", raising=False)
    monkeypatch.setattr(update_manager_bridge, "_read_install_location", lambda: None)
    monkeypatch.setattr(update_manager_bridge, "IS_WINDOWS", True)


@pytest.fixture
def managed_install(monkeypatch):
    monkeypatch.setattr(update_manager_bridge, "_read_install_location", lambda: Path(sys.executable).resolve().parent)
    assert update_manager_bridge._is_managed_install()


@pytest.fixture
def launched_processes(monkeypatch):
    launches = []

    class RecordingPopen:
        def __init__(self, args, **kwargs):
            launches.append(SimpleNamespace(args=args, kwargs=kwargs))

    monkeypatch.setattr(update_manager_bridge.subprocess, "Popen", RecordingPopen)
    return launches


@pytest.fixture
def bridge(qapp):
    update_bridge = UpdateManagerBridge()
    update_bridge.setCurrentVersion(APP_VERSION)
    yield update_bridge
    update_bridge._workers.shutdown(timeout_ms=5000)


def run_check(current_version=APP_VERSION, github_token=""):
    worker = UpdateCheckWorker(current_version, github_token)
    outcome = SimpleNamespace(
        available=record_signal(worker.updateAvailable),
        not_available=record_signal(worker.noUpdateAvailable),
        errors=record_signal(worker.errorOccurred),
    )
    worker.work()
    return outcome


def test_managed_install_gets_the_installer_download_url(release_server, managed_install):
    release_server.serve_release(NEWER_TAG, ["XXAR-Installer-v99.0.0.msi", "XXAR-Installer-v99.0.0.exe", "XXAR-v99.0.0.zip"])
    outcome = run_check()
    download_url = release_server.url("/download/XXAR-Installer-v99.0.0.exe")
    assert outcome.available == [(NEWER_VERSION, download_url, "XXAR-Installer-v99.0.0.exe", RELEASE_NOTES)]
    assert outcome.errors == []


def test_github_token_selects_the_api_asset_url(release_server, managed_install):
    release_server.serve_release(NEWER_TAG, ["XXAR-Setup-v99.0.0.exe"])
    outcome = run_check(github_token="secret-token")
    assert outcome.available[0][1] == release_server.url("/api/assets/XXAR-Setup-v99.0.0.exe")
    assert release_server.requests[0].headers["Authorization"] == "token secret-token"


def test_check_request_identifies_the_updater(release_server):
    release_server.serve_release(NEWER_TAG, [])
    run_check()
    [request] = release_server.requests
    assert request.path == "/releases/latest"
    assert request.headers["User-Agent"] == "XXAR-Updater"
    assert request.headers["Accept"] == "application/vnd.github.v3+json"
    assert "Authorization" not in request.headers


@pytest.mark.parametrize(
    "scenario",
    ["portable_forced_by_env", "no_registry_marker", "managed_without_assets", "managed_with_unknown_formats", "linux_without_flatpak"],
)
def test_release_the_client_cannot_install_is_a_manual_update_not_an_error(release_server, monkeypatch, scenario):
    asset_names = ["XXAR-Installer-v99.0.0.exe"]
    if scenario == "portable_forced_by_env":
        monkeypatch.setattr(update_manager_bridge, "_read_install_location", lambda: Path(sys.executable).resolve().parent)
        monkeypatch.setenv("XXAR_UPDATE_FORCE_PORTABLE", "1")
    elif scenario == "managed_without_assets":
        monkeypatch.setattr(update_manager_bridge, "_is_managed_install", lambda: True)
        asset_names = []
    elif scenario == "managed_with_unknown_formats":
        monkeypatch.setattr(update_manager_bridge, "_is_managed_install", lambda: True)
        asset_names = ["XXAR-Installer-v99.0.0.msix", "XXAR-v99.0.0-portable.zip", "XXAR-Bootstrapper-v99.0.0.exe"]
    elif scenario == "linux_without_flatpak":
        monkeypatch.setattr(update_manager_bridge, "IS_WINDOWS", False)
        asset_names = ["XXAR-Installer-v99.0.0.exe", "XXAR-linux-x86_64.tar.gz"]
    release_server.serve_release(NEWER_TAG, asset_names)
    outcome = run_check()
    assert outcome.errors == []
    assert outcome.available == [(NEWER_VERSION, "", "", RELEASE_NOTES)]


def test_linux_gets_the_flatpak_bundle(release_server, monkeypatch):
    monkeypatch.setattr(update_manager_bridge, "IS_WINDOWS", False)
    release_server.serve_release(NEWER_TAG, ["XXAR-Installer-v99.0.0.exe", "XXAR-linux-x86_64.flatpak"])
    outcome = run_check()
    assert outcome.available == [(NEWER_VERSION, release_server.url("/download/XXAR-linux-x86_64.flatpak"), "XXAR-linux-x86_64.flatpak", RELEASE_NOTES)]


@pytest.mark.parametrize("release_tag", [f"v{APP_VERSION}", APP_VERSION, f"XXAR-v{APP_VERSION}", f"v{OLDER_VERSION}", f"v{APP_VERSION}-rc1"])
def test_same_or_older_release_reports_no_update(release_server, managed_install, release_tag):
    release_server.serve_release(release_tag, ["XXAR-Installer-v1.0.0.exe"])
    outcome = run_check()
    assert outcome.not_available == [()]
    assert outcome.available == []
    assert outcome.errors == []


def test_final_release_upgrades_its_own_prerelease(release_server, managed_install):
    release_server.serve_release("v2.0.0", ["XXAR-Installer-v2.0.0.exe"])
    outcome = run_check(current_version="2.0.0-beta.2")
    assert outcome.available[0][0] == "2.0.0"


def test_release_without_tag_is_an_error(release_server):
    release_server.serve_bytes("/releases/latest", json.dumps({"assets": []}).encode())
    outcome = run_check()
    assert outcome.errors == [("No tag found in latest release",)]


@pytest.mark.parametrize(
    "status, expected_message_start",
    [(404, "No releases found"), (401, "GitHub API authentication failed"), (403, "GitHub API authentication failed"), (500, "GitHub API error: 500")],
)
def test_http_errors_are_reported(release_server, status, expected_message_start):
    release_server.serve_bytes("/releases/latest", b"{}", status=status)
    outcome = run_check()
    assert len(outcome.errors) == 1
    assert outcome.errors[0][0].startswith(expected_message_start)
    assert outcome.available == []


def test_unreachable_server_is_a_network_error(monkeypatch):
    with socket.socket() as probe_socket:
        probe_socket.bind(("127.0.0.1", 0))
        closed_port = probe_socket.getsockname()[1]
    monkeypatch.setattr(update_manager_bridge, "GITHUB_API_URL", f"http://127.0.0.1:{closed_port}/releases/latest")
    outcome = run_check()
    assert len(outcome.errors) == 1
    assert outcome.errors[0][0].startswith("Network error")


def test_bridge_portable_check_notifies_and_offers_only_the_releases_page(release_server, bridge):
    release_server.serve_release(NEWER_TAG, ["XXAR-Installer-v99.0.0.exe"])
    available = record_signal(bridge.updateAvailable)
    errors = record_signal(bridge.updateError)
    bridge.checkForUpdates()
    assert wait_until(lambda: available and not bridge._workers.is_running("check"))
    assert available == [(NEWER_VERSION, RELEASE_NOTES)]
    assert errors == []
    assert not bridge.canAutoUpdate()
    bridge.downloadAndInstall()
    assert len(errors) == 1
    assert "github.com/Entity378/XXAR/releases" in errors[0][0]
    assert bridge._workers.get("download") is None


def test_bridge_reports_no_update(release_server, bridge):
    release_server.serve_release(f"v{APP_VERSION}", [])
    not_available = record_signal(bridge.updateNotAvailable)
    bridge.checkForUpdates()
    assert wait_until(lambda: not_available)


def test_bridge_ignores_a_check_while_one_is_running(release_server, bridge):
    release_server.serve_release(NEWER_TAG, [])
    release_server.response_gate = threading.Event()
    available = record_signal(bridge.updateAvailable)
    bridge.checkForUpdates()
    bridge.checkForUpdates()
    assert wait_until(lambda: len(release_server.requests) == 1)
    release_server.response_gate.set()
    assert wait_until(lambda: available and not bridge._workers.is_running("check"))
    assert len(release_server.requests) == 1
    assert len(available) == 1


def test_github_token_is_saved_and_used_by_the_next_bridge(release_server, qapp):
    write_settings({"selected_game": "hsr"})
    UpdateManagerBridge().setGithubToken("saved-token")
    assert read_settings() == {"selected_game": "hsr", "github_token": "saved-token"}
    release_server.serve_release(f"v{APP_VERSION}", [])
    next_bridge = UpdateManagerBridge()
    not_available = record_signal(next_bridge.updateNotAvailable)
    next_bridge.setCurrentVersion(APP_VERSION)
    next_bridge.checkForUpdates()
    assert wait_until(lambda: not_available and not next_bridge._workers.is_running("check"))
    assert release_server.requests[0].headers["Authorization"] == "token saved-token"


def test_bridge_downloads_and_hands_off_to_the_installer(release_server, managed_install, bridge, launched_processes):
    installer_bytes = b"MZ" + bytes(range(256)) * 200
    release_server.serve_release(NEWER_TAG, ["XXAR-Installer-v99.0.0.exe"])
    release_server.serve_bytes("/download/XXAR-Installer-v99.0.0.exe", installer_bytes)
    stale_installer = get_updates_dir() / "XXAR-Installer-v1.0.0.exe"
    stale_installer.write_bytes(b"old")
    progress = record_signal(bridge.updateProgress)
    downloaded = record_signal(bridge.updateDownloaded)
    applied = record_signal(bridge.updateApplied)
    errors = record_signal(bridge.updateError)

    bridge.checkForUpdates()
    assert wait_until(lambda: bridge.canAutoUpdate() and not bridge._workers.is_running("check"))
    bridge.downloadAndInstall()
    assert wait_until(lambda: downloaded and not bridge._workers.is_running("download"))
    installer_path = get_updates_dir() / "XXAR-Installer-v99.0.0.exe"
    assert installer_path.read_bytes() == installer_bytes
    assert not stale_installer.exists()
    assert progress[-1] == (100,)
    bridge.applyUpdate()

    assert errors == []
    assert len(applied) == 1
    [launch] = launched_processes
    assert launch.args == [str(installer_path), "/silent"]
    assert launch.kwargs["cwd"] == tempfile.gettempdir()


def prepare_downloaded_update(bridge, tmp_path, kind, file_name):
    downloaded_file = tmp_path / file_name
    downloaded_file.write_bytes(b"installer")
    bridge._downloaded_path = str(downloaded_file)
    bridge._downloaded_kind = kind
    return downloaded_file


def test_apply_exe_update_runs_the_installer_silently_outside_the_install_dir(bridge, tmp_path, launched_processes):
    installer_path = prepare_downloaded_update(bridge, tmp_path, "exe", "XXAR-Installer-v99.0.0.exe")
    applied = record_signal(bridge.updateApplied)
    bridge.applyUpdate()
    [launch] = launched_processes
    assert launch.args == [str(installer_path), "/silent"]
    assert launch.kwargs["cwd"] == tempfile.gettempdir()
    assert launch.kwargs["creationflags"] == 0x00000008
    assert len(applied) == 1


def test_apply_msi_update_uses_the_frozen_msiexec_contract(bridge, tmp_path, launched_processes):
    msi_path = prepare_downloaded_update(bridge, tmp_path, "msi", "XXAR-Installer-v99.0.0.msi")
    bridge.applyUpdate()
    [launch] = launched_processes
    assert launch.args == f'msiexec /i "{msi_path}" /norestart XXAR_SILENT=1'
    assert launch.kwargs["cwd"] == tempfile.gettempdir()


def test_apply_update_runs_only_once(bridge, tmp_path, launched_processes):
    prepare_downloaded_update(bridge, tmp_path, "exe", "XXAR-Installer-v99.0.0.exe")
    applied = record_signal(bridge.updateApplied)
    bridge.applyUpdate()
    bridge.applyUpdate()
    assert len(launched_processes) == 1
    assert len(applied) == 1


def test_failed_apply_can_be_retried(bridge, tmp_path, launched_processes):
    errors = record_signal(bridge.updateError)
    bridge._downloaded_path = str(tmp_path / "missing.exe")
    bridge._downloaded_kind = "exe"
    bridge.applyUpdate()
    assert errors == [("Downloaded update not found",)]
    prepare_downloaded_update(bridge, tmp_path, "exe", "XXAR-Installer-v99.0.0.exe")
    bridge.applyUpdate()
    assert len(launched_processes) == 1


def test_installer_launch_failure_is_reported_and_retryable(bridge, tmp_path, monkeypatch):
    prepare_downloaded_update(bridge, tmp_path, "exe", "XXAR-Installer-v99.0.0.exe")
    applied = record_signal(bridge.updateApplied)
    errors = record_signal(bridge.updateError)

    def failing_popen(*args, **kwargs):
        raise OSError("blocked by policy")

    monkeypatch.setattr(update_manager_bridge.subprocess, "Popen", failing_popen)
    bridge.applyUpdate()
    bridge.applyUpdate()
    assert [message for (message,) in errors] == ["Failed to apply update: blocked by policy"] * 2
    assert applied == []


def test_unknown_update_kind_is_an_error(bridge, tmp_path, launched_processes):
    prepare_downloaded_update(bridge, tmp_path, "appimage", "XXAR.AppImage")
    errors = record_signal(bridge.updateError)
    applied = record_signal(bridge.updateApplied)
    bridge.applyUpdate()
    assert errors == [("Unknown update kind: appimage",)]
    assert applied == []
    assert launched_processes == []


def test_flatpak_update_reinstalls_through_the_host(bridge, tmp_path, monkeypatch, launched_processes):
    monkeypatch.setattr(update_manager_bridge, "IS_FLATPAK", True)
    bundle_path = prepare_downloaded_update(bridge, tmp_path, "flatpak", "XXAR-linux-x86_64.flatpak")
    applied = record_signal(bridge.updateApplied)
    bridge.applyUpdate()
    [launch] = launched_processes
    assert launch.args[:3] == ["flatpak-spawn", "--host", "flatpak"]
    assert launch.args[-1] == str(bundle_path)
    assert "--reinstall" in launch.args
    assert len(applied) == 1


def test_flatpak_bundle_outside_the_sandbox_is_not_reported_as_applied(bridge, tmp_path, monkeypatch, launched_processes):
    monkeypatch.setattr(update_manager_bridge, "IS_FLATPAK", False)
    prepare_downloaded_update(bridge, tmp_path, "flatpak", "XXAR-linux-x86_64.flatpak")
    errors = record_signal(bridge.updateError)
    applied = record_signal(bridge.updateApplied)
    bridge.applyUpdate()
    assert len(errors) == 1
    assert launched_processes == []
    assert applied == []


def run_download(download_url, asset_name):
    worker = UpdateDownloadWorker(download_url, asset_name)
    outcome = SimpleNamespace(
        progress=record_signal(worker.downloadProgress),
        finished=record_signal(worker.downloadFinished),
        errors=record_signal(worker.errorOccurred),
    )
    worker.work()
    return outcome


@pytest.mark.parametrize("asset_name, expected_kind", [("XXAR-Installer-v99.0.0.exe", "exe"), ("XXAR-Installer-v99.0.0.msi", "msi"), ("XXAR-linux-x86_64.flatpak", "flatpak")])
def test_download_worker_saves_runnable_assets_into_the_updates_dir(release_server, asset_name, expected_kind):
    release_server.serve_bytes(f"/download/{asset_name}", b"payload" * 5000)
    outcome = run_download(release_server.url(f"/download/{asset_name}"), asset_name)
    downloaded_path = get_updates_dir() / asset_name
    assert outcome.errors == []
    assert outcome.finished == [(expected_kind, str(downloaded_path))]
    assert downloaded_path.read_bytes() == b"payload" * 5000
    assert outcome.progress[-1] == (100,)


def make_tar_gz(members):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar_file:
        for member_name, content in members.items():
            tar_info = tarfile.TarInfo(member_name)
            tar_info.size = len(content)
            tar_file.addfile(tar_info, io.BytesIO(content))
    return buffer.getvalue()


def test_download_worker_extracts_the_legacy_tarball(release_server):
    release_server.serve_bytes("/download/XXAR-linux.tar.gz", make_tar_gz({"XXAR": b"elf binary"}))
    outcome = run_download(release_server.url("/download/XXAR-linux.tar.gz"), "XXAR-linux.tar.gz")
    binary_path = get_updates_dir() / "XXAR"
    assert outcome.finished == [("flatpak", str(binary_path))]
    assert binary_path.read_bytes() == b"elf binary"
    assert not (get_updates_dir() / "XXAR-linux.tar.gz").exists()


def test_download_worker_refuses_a_traversing_tarball(release_server):
    release_server.serve_bytes("/download/XXAR-linux.tar.gz", make_tar_gz({"../../escaped": b"pwned"}))
    outcome = run_download(release_server.url("/download/XXAR-linux.tar.gz"), "XXAR-linux.tar.gz")
    assert outcome.finished == []
    assert len(outcome.errors) == 1
    assert outcome.errors[0][0].startswith("Download failed")
    assert not (get_updates_dir().parent.parent / "escaped").exists()


def test_download_worker_reports_http_errors(release_server):
    outcome = run_download(release_server.url("/download/missing.exe"), "missing.exe")
    assert outcome.finished == []
    assert outcome.errors[0][0].startswith("Download failed")
