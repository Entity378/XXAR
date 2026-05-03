# Live end-to-end test of the XXAR updater flow using a real built exe.

# This exercises the one thing the unit harness in scripts/test_updater.py
# cannot: the full behavior of a frozen PyInstaller XXAR.exe releasing its
# lock on Resources/Bin and handing off to the helper for the swap + relaunch.

# Requires (produced by: pwsh installer_ws\\build_all.ps1 -Version <v> -SkipMsi):
#   - dist/XXAR/XXAR.exe
#   - dist/Updater/XXAR Updater.exe
#   - dist/XXAR-windows-x64.zip

# Flow:
#   1. Extract dist/XXAR-windows-x64.zip into <temp>/install/        (stages the "installed" portable app)
#   2. Write LIVE_TEST_MARKER.txt = "OLD" inside <temp>/install/Resources/Bin/
#   3. Build a "new release" ZIP = same contents + LIVE_TEST_MARKER.txt = "NEW"
#   4. Start a mock GitHub /releases/latest HTTP server on 127.0.0.1:<port>
#   5. Launch <temp>/install/Resources/Bin/XXAR.exe with env:
#        XXAR_UPDATE_API_URL_OVERRIDE=http://127.0.0.1:<port>/repos/.../releases/latest
#        XXAR_UPDATE_FORCE_PORTABLE=1
#   6. YOU click "Download" in the update dialog that appears at startup.
#   7. The script watches for:
#        a) original XXAR.exe process exit
#        b) LIVE_TEST_MARKER.txt flips from OLD to NEW
#        c) a new XXAR.exe alive (helper relaunched it)
#        d) Bin.old cleaned up
#   8. Reports PASS/FAIL, kills the relaunched exe, cleans up temp dir.

# Run:
#     python scripts/test_updater_live.py
#     python scripts/test_updater_live.py --keep-artifacts
#     python scripts/test_updater_live.py --timeout 600

# Note: XXAR_UPDATE_API_URL_OVERRIDE and XXAR_UPDATE_FORCE_PORTABLE are
# read by src/gui/backend/update_manager_bridge.py. They have no effect on
# normal (non-test) runs because they're unset.


from __future__ import annotations

import argparse
import http.server
import json
import os
import shutil
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

DIST_APP_DIR = REPO_ROOT / "dist" / "XXAR"
DIST_UPDATER_DIR = REPO_ROOT / "dist" / "Updater"
DIST_ZIP = REPO_ROOT / "dist" / "XXAR-windows-x64.zip"

APP_EXE_NAME = "XXAR.exe"
HELPER_EXE_NAME = "XXAR Updater.exe"
MARKER_NAME = "LIVE_TEST_MARKER.txt"


# ─────────────────────────────────────────────────────────────────────────────
# Mock GitHub release server
# ─────────────────────────────────────────────────────────────────────────────

def build_new_release_zip(src_zip: Path, dest_zip: Path, marker_value: str) -> None:
    # Copy `src_zip` to `dest_zip` with LIVE_TEST_MARKER.txt inside Resources/Bin/
    # set to `marker_value`. Everything else is byte-identical.
    with zipfile.ZipFile(src_zip, "r") as src:
        names = src.namelist()
        marker_paths = [n for n in names if n.endswith(MARKER_NAME)]
        resources_prefix = next(
            (n[: n.index("Resources/")] for n in names if "Resources/" in n),
            "",
        )
        marker_arcname = f"{resources_prefix}Resources/Bin/{MARKER_NAME}"

        with zipfile.ZipFile(dest_zip, "w", zipfile.ZIP_DEFLATED) as dst:
            for n in names:
                if n == marker_arcname or n in marker_paths:
                    continue
                dst.writestr(src.getinfo(n), src.read(n))
            dst.writestr(marker_arcname, marker_value)


class MockServer(socketserver.TCPServer):
    # TCPServer subclass that counts hits to the release endpoints.
    allow_reuse_address = True

    def __init__(self, *a, served_zip: Path, version: str, **kw):
        super().__init__(*a, **kw)
        self.served_zip = served_zip
        self.version = version
        self.api_hits = 0
        self.download_hits = 0


def start_mock_server(workdir: Path, zip_to_serve: Path, version: str) -> tuple[int, MockServer]:
    workdir.mkdir(parents=True, exist_ok=True)
    served = workdir / zip_to_serve.name
    shutil.copy2(zip_to_serve, served)

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass

        def _send(self, data: bytes, ctype: str) -> None:
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            srv: MockServer = self.server  # type: ignore[assignment]
            host = self.headers.get("Host", f"127.0.0.1:{srv.server_address[1]}")
            if self.path.endswith("/releases/latest"):
                srv.api_hits += 1
                payload = {
                    "tag_name": f"v{srv.version}",
                    "body": "Live test release notes - DO NOT USE IN PRODUCTION.",
                    "assets": [
                        {
                            "name": "XXAR-windows-x64.zip",
                            "url": f"http://{host}/asset/zip",
                            "browser_download_url": f"http://{host}/download/zip",
                        },
                    ],
                }
                self._send(json.dumps(payload).encode(), "application/json")
                return
            if self.path in ("/asset/zip", "/download/zip"):
                srv.download_hits += 1
                self._send(srv.served_zip.read_bytes(), "application/zip")
                return
            self.send_error(404)

    httpd = MockServer(("127.0.0.1", 0), Handler, served_zip=served, version=version)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return port, httpd


# ─────────────────────────────────────────────────────────────────────────────
# Process helpers
# ─────────────────────────────────────────────────────────────────────────────

def list_xxar_processes_under(path: Path) -> list[int]:
    # Return PIDs of running XXAR.exe whose image path is inside `path`.

    # Uses PowerShell's CIM WMI. Returns [] if anything goes wrong (best effort).
    if sys.platform != "win32":
        return []
    ps = (
        "Get-CimInstance Win32_Process -Filter \"Name='XXAR.exe'\" "
        f"| Where-Object {{ $_.ExecutablePath -like '{path}*' }} "
        "| ForEach-Object { $_.ProcessId }"
    )
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True, text=True, timeout=10,
        )
        return [int(line.strip()) for line in out.stdout.splitlines() if line.strip().isdigit()]
    except Exception:
        return []


def kill_pids(pids: list[int]) -> None:
    for pid in pids:
        try:
            subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True, timeout=10)
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# Main flow
# ─────────────────────────────────────────────────────────────────────────────

class Phase:
    def __init__(self, name: str):
        self.name = name
        self.ok = False
        self.detail = ""
        self.started = time.time()

    def done(self, ok: bool, detail: str = "") -> None:
        self.ok = ok
        self.detail = detail
        self.elapsed = time.time() - self.started

    def __str__(self) -> str:
        tag = "PASS" if self.ok else "FAIL"
        return f"  [{tag}] {self.name} ({self.elapsed:.1f}s){(' - ' + self.detail) if self.detail else ''}"


def preflight() -> None:
    missing = []
    if not (DIST_APP_DIR / APP_EXE_NAME).exists():
        missing.append(str(DIST_APP_DIR / APP_EXE_NAME))
    if not (DIST_UPDATER_DIR / HELPER_EXE_NAME).exists():
        missing.append(str(DIST_UPDATER_DIR / HELPER_EXE_NAME))
    if not DIST_ZIP.exists():
        missing.append(str(DIST_ZIP))
    if missing:
        print("ERROR: required build artifacts are missing:", file=sys.stderr)
        for m in missing:
            print(f"  - {m}", file=sys.stderr)
        print("\nRun first: pwsh installer_ws/build_all.ps1 -Version <v> -SkipMsi",
              file=sys.stderr)
        sys.exit(2)
    if sys.platform != "win32":
        print("ERROR: live test is Windows-only (the helper is a Windows exe).",
              file=sys.stderr)
        sys.exit(2)

    # Heuristic: if update_manager_bridge.py is newer than the built exe, the
    # env-var overrides this test relies on aren't baked in. Warn loudly.
    bridge_src = REPO_ROOT / "src" / "gui" / "backend" / "update_manager_bridge.py"
    exe = DIST_APP_DIR / APP_EXE_NAME
    if bridge_src.exists() and exe.exists():
        if bridge_src.stat().st_mtime > exe.stat().st_mtime:
            print("⚠  WARNING: update_manager_bridge.py is newer than dist/XXAR/XXAR.exe.")
            print("   This test requires env-var overrides added recently to that file.")
            print("   If the mock server never gets hit, rebuild first with:")
            print("     pwsh installer_ws/build_all.ps1 -Version <v> -SkipMsi")
            print()


def stage_install(install_root: Path) -> None:
    # Extract the portable ZIP to form an 'installed' layout.
    install_root.mkdir(parents=True, exist_ok=True)
    print(f"  Extracting {DIST_ZIP.name} into {install_root}...")
    with zipfile.ZipFile(DIST_ZIP, "r") as zf:
        zf.extractall(install_root)

    bin_dir = install_root / "Resources" / "Bin"
    upd_dir = install_root / "Resources" / "Updater"
    if not (bin_dir / APP_EXE_NAME).exists():
        raise RuntimeError(f"After extraction, {bin_dir / APP_EXE_NAME} is missing")
    if not (upd_dir / HELPER_EXE_NAME).exists():
        # Zip may only contain Bin/ and not Updater/ - copy helper manually.
        upd_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(DIST_UPDATER_DIR / HELPER_EXE_NAME, upd_dir / HELPER_EXE_NAME)

    (bin_dir / MARKER_NAME).write_text("OLD", encoding="utf-8")


def wait_for(predicate, timeout_s: float, poll_s: float = 1.0) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(poll_s)
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="XXAR updater LIVE end-to-end test")
    parser.add_argument("--keep-artifacts", action="store_true",
                        help="Don't delete the temp install dir after the run")
    parser.add_argument("--timeout", type=int, default=300,
                        help="Seconds to wait for the full update flow (default 300)")
    args = parser.parse_args()

    preflight()

    temp_root = Path(tempfile.mkdtemp(prefix="xxar_live_test_"))
    install_root = temp_root / "install"
    bin_dir = install_root / "Resources" / "Bin"
    bin_old = install_root / "Resources" / "Bin.old"
    marker = bin_dir / MARKER_NAME
    app_exe = bin_dir / APP_EXE_NAME
    new_zip = temp_root / "new_release.zip"

    print(f"Temp workdir: {temp_root}")
    print()

    phases: list[Phase] = []
    server: MockServer | None = None
    popen: subprocess.Popen | None = None
    launched_pid = -1

    try:
        # ── Stage install ────────────────────────────────────────────
        p = Phase("Stage installed app (extract portable ZIP)")
        try:
            stage_install(install_root)
            p.done(True, f"{sum(1 for _ in bin_dir.rglob('*'))} files in Bin/")
        except Exception as e:
            p.done(False, repr(e))
            phases.append(p)
            return _finish(phases, temp_root, args.keep_artifacts, server, popen, launched_pid, install_root)
        phases.append(p)
        print(phases[-1])

        # ── Build new-release ZIP ────────────────────────────────────
        p = Phase("Build 'new release' ZIP with NEW marker")
        try:
            build_new_release_zip(DIST_ZIP, new_zip, "NEW")
            p.done(True, f"{new_zip.stat().st_size // (1024*1024)} MiB")
        except Exception as e:
            p.done(False, repr(e))
            phases.append(p)
            return _finish(phases, temp_root, args.keep_artifacts, server, popen, launched_pid, install_root)
        phases.append(p)
        print(phases[-1])

        # ── Mock server ──────────────────────────────────────────────
        p = Phase("Start mock GitHub API server")
        try:
            port, server = start_mock_server(temp_root / "www", new_zip, "999.0.0")
            p.done(True, f"127.0.0.1:{port}")
        except Exception as e:
            p.done(False, repr(e))
            phases.append(p)
            return _finish(phases, temp_root, args.keep_artifacts, server, popen, launched_pid, install_root)
        phases.append(p)
        print(phases[-1])

        # ── Launch XXAR.exe ──────────────────────────────────────────
        p = Phase("Launch XXAR.exe from staged install")
        try:
            env = os.environ.copy()
            env["XXAR_UPDATE_API_URL_OVERRIDE"] = f"http://127.0.0.1:{port}/repos/Entity378/XXAR/releases/latest"
            env["XXAR_UPDATE_FORCE_PORTABLE"] = "1"
            popen = subprocess.Popen([str(app_exe)], cwd=str(bin_dir), env=env)
            launched_pid = popen.pid
            p.done(True, f"pid={launched_pid}")
        except Exception as e:
            p.done(False, repr(e))
            phases.append(p)
            return _finish(phases, temp_root, args.keep_artifacts, server, popen, launched_pid, install_root)
        phases.append(p)
        print(phases[-1])

        print()
        print("DO NOT click anything yet. Waiting to confirm the exe is talking")
        print("to the mock server (not the real GitHub) before you proceed...")
        print()

        # ── Verify env-var override took effect ──────────────────────
        # If the built exe doesn't read XXAR_UPDATE_API_URL_OVERRIDE, it'll
        # silently hit api.github.com instead - catch that before the user
        # can interact with what would become a real (dangerous) update.
        p = Phase("Built exe reaches the mock server (env-var override active)")
        hit = wait_for(lambda: server.api_hits > 0, timeout_s=60)
        if hit:
            p.done(True, f"api_hits={server.api_hits}")
        else:
            p.done(False, "no /releases/latest hit in 60s - rebuild dist/XXAR/ after adding env-var overrides to update_manager_bridge.py")
        phases.append(p)
        print(phases[-1])
        if not hit:
            return _finish(phases, temp_root, args.keep_artifacts, server, popen, launched_pid, install_root)

        print()
        print("=" * 72)
        print("ACTION REQUIRED NOW:")
        print("  Mock confirmed. When the update dialog appears in the app, click")
        print("  'Download'. Do NOT close the app manually - let the flow run.")
        print(f"  Watching for the full flow up to {args.timeout}s...")
        print("=" * 72)
        print()

        # ── Wait for original exe exit ───────────────────────────────
        p = Phase("Original XXAR.exe process exits (triggered by applyUpdate)")
        exited = wait_for(lambda: popen.poll() is not None, args.timeout)
        if exited:
            p.done(True, f"rc={popen.returncode}")
        else:
            p.done(False, f"still running after {args.timeout}s")
        phases.append(p)
        print(phases[-1])
        if not exited:
            return _finish(phases, temp_root, args.keep_artifacts, server, popen, launched_pid, install_root)

        # ── Wait for swap (marker flip) ──────────────────────────────
        p = Phase("Resources/Bin swapped (marker flips OLD -> NEW)")
        swapped = wait_for(
            lambda: marker.exists() and marker.read_text(encoding="utf-8").strip() == "NEW",
            timeout_s=240,
        )
        if swapped:
            p.done(True, f"marker={marker.read_text(encoding='utf-8').strip()!r}")
        else:
            got = marker.read_text(encoding="utf-8").strip() if marker.exists() else "<missing>"
            p.done(False, f"marker={got!r}")
        phases.append(p)
        print(phases[-1])

        # ── Relaunch check ───────────────────────────────────────────
        p = Phase("Helper relaunched a fresh XXAR.exe")
        relaunched = wait_for(
            lambda: [pid for pid in list_xxar_processes_under(install_root) if pid != launched_pid],
            timeout_s=30,
        )
        live_pids = [pid for pid in list_xxar_processes_under(install_root) if pid != launched_pid]
        if relaunched and live_pids:
            p.done(True, f"new pids={live_pids}")
        else:
            p.done(False, "no new XXAR.exe detected")
        phases.append(p)
        print(phases[-1])

        # ── Bin.old cleanup ──────────────────────────────────────────
        p = Phase("Bin.old cleaned up post-swap")
        try:
            if not bin_old.exists():
                p.done(True, "absent")
            elif not any(bin_old.iterdir()):
                p.done(True, "empty")
            else:
                leftover = [x.name for x in bin_old.iterdir()][:5]
                p.done(False, f"still has {leftover}")
        except Exception as e:
            p.done(False, repr(e))
        phases.append(p)
        print(phases[-1])

        return _finish(phases, temp_root, args.keep_artifacts, server, popen, launched_pid, install_root)

    except KeyboardInterrupt:
        print("\nAborted by user.")
        return _finish(phases, temp_root, args.keep_artifacts, server, popen, launched_pid, install_root, aborted=True)


def _finish(
    phases: list[Phase],
    temp_root: Path,
    keep: bool,
    server: MockServer | None,
    popen: subprocess.Popen | None,
    launched_pid: int,
    install_root: Path,
    aborted: bool = False,
) -> int:
    if server is not None:
        try:
            server.shutdown()
        except Exception:
            pass

    # Clean up any XXAR.exe instances still running under our test dir.
    leftover_pids = list_xxar_processes_under(install_root)
    if popen is not None and popen.poll() is None:
        try:
            popen.terminate()
            popen.wait(timeout=5)
        except Exception:
            pass
    if leftover_pids:
        print(f"\nKilling leftover XXAR.exe pids: {leftover_pids}")
        kill_pids(leftover_pids)
        time.sleep(1)

    print()
    print("=" * 72)
    passed = sum(1 for p in phases if p.ok)
    failed = sum(1 for p in phases if not p.ok)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 72)
    if failed:
        print("\nFailures:")
        for p in phases:
            if not p.ok:
                print(f"  - {p.name}: {p.detail}")

    if keep:
        print(f"\nArtifacts preserved at: {temp_root}")
    else:
        # Best effort - temp may still have locked files briefly after kill.
        for _ in range(5):
            try:
                shutil.rmtree(temp_root)
                break
            except Exception:
                time.sleep(1)
        else:
            print(f"\n(could not fully remove temp dir: {temp_root})")

    return 0 if (not failed and not aborted) else 1


if __name__ == "__main__":
    sys.exit(main())
