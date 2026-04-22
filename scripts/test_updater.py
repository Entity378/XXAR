"""End-to-end test harness for the XXAR updater.

What this exercises (in order):

1. Version parsing + comparison rules in update_manager_bridge.
2. MSI-install detection helper (smoke).
3. UpdateCheckWorker against a local mock of the GitHub /releases/latest API,
   covering both the ZIP code path and the MSI code path (asset selection).
4. UpdateDownloadWorker: real HTTP download against the mock, real ZIP
   extraction into a staging folder, resulting staging root is validated.
5. XXAR_Updater helper: real subprocess that swaps Resources/Bin with a
   pre-extracted staging folder. Includes edge cases:
     - leftover Bin.old from a prior failed run is cleaned up;
     - missing staging dir fails non-zero without touching Bin.

Run:
    python scripts/test_updater.py
    python scripts/test_updater.py --helper-exe "dist/Updater/XXAR Updater.exe"
    python scripts/test_updater.py --keep-artifacts   # keep temp dir for inspection
"""

from __future__ import annotations

import argparse
import http.server
import json
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
sys.path.insert(0, str(REPO_ROOT))


# ─────────────────────────────────────────────────────────────────────────────
# Tiny result recorder
# ─────────────────────────────────────────────────────────────────────────────

class TestResult:
    def __init__(self) -> None:
        self.passed: list[tuple[str, str]] = []
        self.failed: list[tuple[str, str]] = []

    def ok(self, name: str, detail: str = "") -> None:
        self.passed.append((name, detail))
        suffix = f" — {detail}" if detail else ""
        print(f"  [PASS] {name}{suffix}")

    def fail(self, name: str, detail: str = "") -> None:
        self.failed.append((name, detail))
        suffix = f" — {detail}" if detail else ""
        print(f"  [FAIL] {name}{suffix}")


# ─────────────────────────────────────────────────────────────────────────────
# Test: version parsing
# ─────────────────────────────────────────────────────────────────────────────

def test_version_parsing(r: TestResult) -> None:
    from src.gui.backend.update_manager_bridge import parse_version, clean_version_string

    cases = [
        ("v1.2.3", (1, 2, 3, 3, 0)),
        ("1.2.3", (1, 2, 3, 3, 0)),
        ("XXAR-v1.2.3", (1, 2, 3, 3, 0)),
        ("1.2.3-alpha", (1, 2, 3, 0, 0)),
        ("1.2.3-beta.2", (1, 2, 3, 1, 2)),
        ("1.2.3-rc1", (1, 2, 3, 2, 1)),
        ("0.7.0-alpha", (0, 7, 0, 0, 0)),
    ]
    for raw, expected in cases:
        got = parse_version(raw)
        if got == expected:
            r.ok(f"parse_version({raw!r})", f"{got}")
        else:
            r.fail(f"parse_version({raw!r})", f"expected {expected} got {got}")

    if parse_version("1.0.0") < parse_version("1.0.1"):
        r.ok("ordering: 1.0.0 < 1.0.1")
    else:
        r.fail("ordering: 1.0.0 < 1.0.1")

    if parse_version("1.0.0-alpha") < parse_version("1.0.0"):
        r.ok("ordering: 1.0.0-alpha < 1.0.0")
    else:
        r.fail("ordering: 1.0.0-alpha < 1.0.0")

    if parse_version("1.0.0-rc2") < parse_version("1.0.0-rc10"):
        r.ok("ordering: rc2 < rc10")
    else:
        r.fail("ordering: rc2 < rc10")

    if clean_version_string("XXAR-v0.7.0") == "0.7.0":
        r.ok("clean_version_string strips XXAR-v prefix")
    else:
        r.fail("clean_version_string strips XXAR-v prefix")


# ─────────────────────────────────────────────────────────────────────────────
# Test: MSI detection smoke (only verifies it returns a bool cleanly)
# ─────────────────────────────────────────────────────────────────────────────

def test_msi_detection_smoke(r: TestResult) -> None:
    if sys.platform != "win32":
        r.ok("_is_msi_install() skipped (non-Windows)")
        return
    import src.gui.backend.update_manager_bridge as umb
    try:
        result = umb._is_msi_install()
        if isinstance(result, bool):
            r.ok("_is_msi_install() returns bool", f"value={result}")
        else:
            r.fail("_is_msi_install() returns bool", f"got {type(result).__name__}")
    except Exception as e:
        r.fail("_is_msi_install() no-raise", str(e))


# ─────────────────────────────────────────────────────────────────────────────
# Fake release ZIP + mock GitHub server
# ─────────────────────────────────────────────────────────────────────────────

def build_fake_release_zip(dest_dir: Path, version: str) -> Path:
    """Build a ZIP with the shape produced by installer_ws/build_all.ps1:
    Resources/Bin/XXAR.exe + Resources/Updater/XXAR Updater.exe at the root."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    scratch = dest_dir / f"_scratch_{version}"
    bin_dir = scratch / "Resources" / "Bin"
    upd_dir = scratch / "Resources" / "Updater"
    bin_dir.mkdir(parents=True)
    upd_dir.mkdir(parents=True)

    (bin_dir / "XXAR.exe").write_bytes(f"FAKE XXAR EXE v{version}".encode())
    (bin_dir / "VERSION.txt").write_text(version, encoding="utf-8")
    (bin_dir / "_internal").mkdir()
    (bin_dir / "_internal" / "dummy.pyd").write_bytes(b"\x00" * 1024)
    (upd_dir / "XXAR Updater.exe").write_bytes(b"FAKE HELPER")

    zip_path = dest_dir / f"XXAR-windows-x64-{version}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in scratch.rglob("*"):
            if path.is_file():
                zf.write(path, path.relative_to(scratch))
    shutil.rmtree(scratch)
    return zip_path


def build_fake_msi(dest_dir: Path, version: str) -> Path:
    """A tiny stand-in MSI blob (not an actual MSI — we only test asset selection)."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    path = dest_dir / f"XXAR-Installer-v{version}.msi"
    path.write_bytes(b"FAKE MSI BYTES v" + version.encode())
    return path


def start_mock_github_server(
    workdir: Path,
    release_version: str,
    zip_path: Path,
    msi_path: Path | None = None,
) -> tuple[int, socketserver.TCPServer]:
    """Mock of GitHub REST: /releases/latest + asset download endpoints."""
    workdir.mkdir(parents=True, exist_ok=True)
    served_zip = workdir / zip_path.name
    shutil.copy2(zip_path, served_zip)
    served_msi = None
    if msi_path is not None:
        served_msi = workdir / msi_path.name
        shutil.copy2(msi_path, served_msi)

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):  # silence per-request noise
            pass

        def _send_bytes(self, data: bytes, content_type: str) -> None:
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            host = self.headers.get("Host", f"127.0.0.1:{self.server.server_address[1]}")

            if self.path.endswith("/releases/latest"):
                assets = [
                    {
                        "name": "XXAR-windows-x64.zip",
                        "url": f"http://{host}/asset/zip",
                        "browser_download_url": f"http://{host}/download/zip",
                    }
                ]
                if served_msi is not None:
                    assets.append({
                        "name": served_msi.name,
                        "url": f"http://{host}/asset/msi",
                        "browser_download_url": f"http://{host}/download/msi",
                    })
                payload = {
                    "tag_name": f"v{release_version}",
                    "body": "Test release notes\n- feature X\n- fix Y",
                    "assets": assets,
                }
                self._send_bytes(json.dumps(payload).encode(), "application/json")
                return

            if self.path in ("/asset/zip", "/download/zip"):
                self._send_bytes(served_zip.read_bytes(), "application/zip")
                return

            if served_msi is not None and self.path in ("/asset/msi", "/download/msi"):
                self._send_bytes(served_msi.read_bytes(), "application/octet-stream")
                return

            self.send_error(404)

    httpd = socketserver.TCPServer(("127.0.0.1", 0), Handler)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return port, httpd


# ─────────────────────────────────────────────────────────────────────────────
# Test: UpdateCheckWorker (ZIP path + MSI path)
# ─────────────────────────────────────────────────────────────────────────────

def _run_check_worker(current_version: str, api_url: str, is_msi: bool, timeout_ms: int = 15000) -> dict:
    from PyQt5.QtCore import QCoreApplication
    import src.gui.backend.update_manager_bridge as umb

    app = QCoreApplication.instance() or QCoreApplication(sys.argv)

    original_url = umb.GITHUB_API_URL
    original_is_msi = umb._is_msi_install
    umb.GITHUB_API_URL = api_url
    umb._is_msi_install = lambda: is_msi

    try:
        worker = umb.UpdateCheckWorker(current_version, "")
        result: dict = {}

        worker.updateAvailable.connect(
            lambda v, url, name, notes: result.update(version=v, url=url, name=name, notes=notes)
        )
        worker.noUpdateAvailable.connect(lambda: result.update(no_update=True))
        worker.errorOccurred.connect(lambda msg: result.update(error=msg))

        worker.start()
        if not worker.wait(timeout_ms):
            worker.terminate()
            worker.wait(1000)
            return {"error": f"worker thread exceeded {timeout_ms}ms"}
        # Thread has finished; flush queued signals delivered to the main thread.
        app.processEvents()
        return result
    finally:
        umb.GITHUB_API_URL = original_url
        umb._is_msi_install = original_is_msi


def test_check_worker_zip(r: TestResult, port: int) -> None:
    api = f"http://127.0.0.1:{port}/repos/Entity378/XXAR/releases/latest"
    res = _run_check_worker("0.0.1", api, is_msi=False)
    if "error" in res:
        r.fail("CheckWorker[ZIP]: detects update", res["error"])
        return
    if res.get("no_update"):
        r.fail("CheckWorker[ZIP]: detects update", "worker said up-to-date")
        return
    if res.get("version") != "0.9.99":
        r.fail("CheckWorker[ZIP]: correct version", f"got {res.get('version')}")
        return
    r.ok("CheckWorker[ZIP]: detects update", f"v{res['version']}")
    if res.get("name") == "XXAR-windows-x64.zip":
        r.ok("CheckWorker[ZIP]: picks ZIP asset")
    else:
        r.fail("CheckWorker[ZIP]: picks ZIP asset", f"got {res.get('name')}")


def test_check_worker_msi(r: TestResult, port: int) -> None:
    api = f"http://127.0.0.1:{port}/repos/Entity378/XXAR/releases/latest"
    res = _run_check_worker("0.0.1", api, is_msi=True)
    if "error" in res:
        r.fail("CheckWorker[MSI]: detects update", res["error"])
        return
    name = res.get("name", "")
    if name.startswith("XXAR-Installer-v") and name.endswith(".msi"):
        r.ok("CheckWorker[MSI]: picks versioned MSI asset", name)
    else:
        r.fail("CheckWorker[MSI]: picks versioned MSI asset", f"got {name}")


def test_check_worker_up_to_date(r: TestResult, port: int) -> None:
    api = f"http://127.0.0.1:{port}/repos/Entity378/XXAR/releases/latest"
    res = _run_check_worker("999.0.0", api, is_msi=False)
    if res.get("no_update"):
        r.ok("CheckWorker: no-update path fires when current >= latest")
    elif "error" in res:
        r.fail("CheckWorker: no-update path", f"error: {res['error']}")
    else:
        r.fail("CheckWorker: no-update path", f"unexpected result {res}")


# ─────────────────────────────────────────────────────────────────────────────
# Test: UpdateDownloadWorker (real HTTP + real ZIP extraction)
# ─────────────────────────────────────────────────────────────────────────────

def test_download_worker(r: TestResult, port: int, temp_dir: Path) -> Path | None:
    from PyQt5.QtCore import QCoreApplication
    import src.gui.backend.update_manager_bridge as umb

    app = QCoreApplication.instance() or QCoreApplication(sys.argv)

    cache_dir = temp_dir / "cache"
    cache_dir.mkdir()
    original_get_cache_dir = umb.get_cache_dir
    umb.get_cache_dir = lambda: cache_dir

    try:
        url = f"http://127.0.0.1:{port}/download/zip"
        worker = umb.UpdateDownloadWorker(url, "XXAR-windows-x64.zip", "")
        result: dict = {}
        progress: list[int] = []

        worker.downloadProgress.connect(lambda p: progress.append(p))
        worker.downloadFinished.connect(lambda kind, path: result.update(kind=kind, path=path))
        worker.errorOccurred.connect(lambda msg: result.update(error=msg))

        worker.start()
        if not worker.wait(30000):
            worker.terminate()
            worker.wait(1000)
            r.fail("DownloadWorker: downloads + extracts", "thread exceeded 30s")
            return None
        app.processEvents()

        if "error" in result:
            r.fail("DownloadWorker: downloads + extracts", result["error"])
            return None
        if result.get("kind") != "zip_staging":
            r.fail("DownloadWorker: signals zip_staging kind", f"got {result.get('kind')}")
            return None
        staging = Path(result["path"])
        if not staging.exists():
            r.fail("DownloadWorker: staging path exists")
            return None
        if not (staging / "XXAR.exe").exists():
            r.fail("DownloadWorker: staging/XXAR.exe exists")
            return None
        r.ok("DownloadWorker: downloads + extracts", f"{len(progress)} progress ticks")
        r.ok("DownloadWorker: staging root contains XXAR.exe", str(staging))

        archive = cache_dir / "updates" / "XXAR-windows-x64.zip"
        if not archive.exists():
            r.ok("DownloadWorker: archive cleaned up post-extract")
        else:
            r.fail("DownloadWorker: archive cleaned up post-extract", f"{archive} remains")

        return staging
    finally:
        umb.get_cache_dir = original_get_cache_dir


# ─────────────────────────────────────────────────────────────────────────────
# Test: helper (folder swap)
# ─────────────────────────────────────────────────────────────────────────────

def _run_helper(helper_cmd: list[str], dist_dir: Path, staging_dir: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        helper_cmd + [
            "--dist-dir", str(dist_dir),
            "--staging-dir", str(staging_dir),
            "--no-relaunch",
        ],
        capture_output=True,
        text=True,
        timeout=90,
    )


def test_helper_happy_path(r: TestResult, temp_dir: Path, helper_cmd: list[str], staging_source: Path) -> None:
    install = temp_dir / "install_happy"
    bin_dir = install / "Resources" / "Bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "XXAR.exe").write_bytes(b"OLD VERSION")
    (bin_dir / "keep_me.txt").write_text("old file")

    staging = temp_dir / "staging_happy"
    shutil.copytree(staging_source, staging)

    proc = _run_helper(helper_cmd, install, staging)
    if proc.returncode != 0:
        r.fail("Helper[happy]: exits 0", f"rc={proc.returncode} stderr={proc.stderr.strip()[:200]}")
        return
    r.ok("Helper[happy]: exits 0")

    new_exe = bin_dir / "XXAR.exe"
    if not new_exe.exists():
        r.fail("Helper[happy]: new Bin/XXAR.exe exists")
        return
    if b"FAKE XXAR EXE" in new_exe.read_bytes():
        r.ok("Helper[happy]: Bin/XXAR.exe content replaced")
    else:
        r.fail("Helper[happy]: Bin/XXAR.exe content replaced")

    if not (bin_dir / "keep_me.txt").exists() and (bin_dir / "VERSION.txt").exists():
        r.ok("Helper[happy]: full Bin directory replaced (not merged)")
    else:
        r.fail("Helper[happy]: full Bin directory replaced",
               f"keep_me={bool((bin_dir / 'keep_me.txt').exists())} "
               f"VERSION={bool((bin_dir / 'VERSION.txt').exists())}")

    if not staging.exists():
        r.ok("Helper[happy]: staging dir consumed")
    else:
        r.fail("Helper[happy]: staging dir consumed", f"still at {staging}")


def test_helper_stale_bin_old(r: TestResult, temp_dir: Path, helper_cmd: list[str], staging_source: Path) -> None:
    install = temp_dir / "install_stale"
    bin_dir = install / "Resources" / "Bin"
    bin_old = install / "Resources" / "Bin.old"
    bin_dir.mkdir(parents=True)
    bin_old.mkdir(parents=True)
    (bin_dir / "XXAR.exe").write_bytes(b"CURRENT")
    (bin_old / "stale.txt").write_text("leftover")

    staging = temp_dir / "staging_stale"
    shutil.copytree(staging_source, staging)

    proc = _run_helper(helper_cmd, install, staging)
    if proc.returncode != 0:
        r.fail("Helper[stale Bin.old]: exits 0", f"rc={proc.returncode} stderr={proc.stderr.strip()[:200]}")
        return
    r.ok("Helper[stale Bin.old]: exits 0")

    if not bin_old.exists() or not any(bin_old.iterdir()):
        r.ok("Helper[stale Bin.old]: cleaned up leftover")
    else:
        r.fail("Helper[stale Bin.old]: cleaned up leftover",
               f"still contains {[p.name for p in bin_old.iterdir()]}")


def test_helper_missing_staging(r: TestResult, temp_dir: Path, helper_cmd: list[str]) -> None:
    install = temp_dir / "install_missing"
    bin_dir = install / "Resources" / "Bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "XXAR.exe").write_bytes(b"CURRENT")

    missing = temp_dir / "definitely_not_there"

    proc = _run_helper(helper_cmd, install, missing)
    if proc.returncode == 0:
        r.fail("Helper[missing staging]: exits non-zero", "returned 0")
    else:
        r.ok("Helper[missing staging]: exits non-zero", f"rc={proc.returncode}")

    if (bin_dir / "XXAR.exe").read_bytes() == b"CURRENT":
        r.ok("Helper[missing staging]: leaves Bin untouched")
    else:
        r.fail("Helper[missing staging]: leaves Bin untouched")


def test_helper_locked_retry(r: TestResult, temp_dir: Path, helper_cmd: list[str], staging_source: Path) -> None:
    """Hold an open read handle on a file inside Bin, start the helper, release the handle
    mid-retry — verifies the rename-retry loop actually recovers. Windows-only."""
    if sys.platform != "win32":
        r.ok("Helper[lock retry]: skipped (non-Windows)")
        return

    install = temp_dir / "install_lock"
    bin_dir = install / "Resources" / "Bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "XXAR.exe").write_bytes(b"OLD")
    locked_file = bin_dir / "locked.bin"
    locked_file.write_bytes(b"locked content")

    staging = temp_dir / "staging_lock"
    shutil.copytree(staging_source, staging)

    fh = open(locked_file, "rb")  # exclusive-ish handle on Windows blocks rename
    release_after = 3.0  # seconds — well within the 30-attempt × 1s retry budget

    def release_later():
        time.sleep(release_after)
        try:
            fh.close()
        except Exception:
            pass

    threading.Thread(target=release_later, daemon=True).start()

    t0 = time.time()
    proc = _run_helper(helper_cmd, install, staging)
    elapsed = time.time() - t0

    try:
        fh.close()
    except Exception:
        pass

    if proc.returncode != 0:
        r.fail("Helper[lock retry]: eventually succeeds",
               f"rc={proc.returncode} elapsed={elapsed:.1f}s stderr={proc.stderr.strip()[:200]}")
        return
    if not (bin_dir / "XXAR.exe").exists() or b"FAKE XXAR EXE" not in (bin_dir / "XXAR.exe").read_bytes():
        r.fail("Helper[lock retry]: new Bin/XXAR.exe present")
        return
    if elapsed < release_after - 0.5:
        r.fail("Helper[lock retry]: actually waited for lock",
               f"elapsed={elapsed:.1f}s < {release_after}s expected")
        return
    r.ok("Helper[lock retry]: retries until handle released", f"elapsed={elapsed:.1f}s")


# ─────────────────────────────────────────────────────────────────────────────
# main
# ─────────────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="XXAR updater end-to-end test harness")
    parser.add_argument(
        "--helper-exe",
        type=Path,
        default=None,
        help="Path to a built XXAR Updater.exe. If omitted, runs updater/XXAR_Updater.py via python.",
    )
    parser.add_argument("--keep-artifacts", action="store_true", help="Keep temp workdir for inspection")
    args = parser.parse_args()

    if args.helper_exe is not None and not args.helper_exe.exists():
        print(f"ERROR: helper exe not found at {args.helper_exe}", file=sys.stderr)
        return 2

    helper_script = REPO_ROOT / "updater" / "XXAR_Updater.py"
    if not helper_script.exists():
        print(f"ERROR: helper script not found at {helper_script}", file=sys.stderr)
        return 2

    helper_cmd = (
        [str(args.helper_exe)] if args.helper_exe else [sys.executable, str(helper_script)]
    )
    print(f"Helper command: {' '.join(helper_cmd)}")
    if sys.platform != "win32":
        print("NOTE: helper is a Windows-only no-op on this platform; swap tests will be skipped.")

    temp_root = Path(tempfile.mkdtemp(prefix="xxar_updater_test_"))
    print(f"Temp workdir: {temp_root}\n")

    r = TestResult()
    server: socketserver.TCPServer | None = None

    try:
        print("[1/6] Version parsing")
        test_version_parsing(r)

        print("\n[2/6] MSI install detection (smoke)")
        test_msi_detection_smoke(r)

        print("\n[3/6] Build fake release artifacts")
        zip_path = build_fake_release_zip(temp_root / "releases", "0.9.99")
        msi_path = build_fake_msi(temp_root / "releases", "0.9.99")
        r.ok("Fake release ZIP", f"{zip_path.name} ({zip_path.stat().st_size} bytes)")
        r.ok("Fake release MSI", f"{msi_path.name}")

        print("\n[4/6] Start mock GitHub API server")
        port, server = start_mock_github_server(temp_root / "www", "0.9.99", zip_path, msi_path)
        r.ok("Mock server listening", f"127.0.0.1:{port}")

        print("\n[5/6] UpdateCheckWorker + UpdateDownloadWorker against mock")
        test_check_worker_zip(r, port)
        test_check_worker_msi(r, port)
        test_check_worker_up_to_date(r, port)
        staging = test_download_worker(r, port, temp_root)

        if staging is None:
            fallback = temp_root / "fallback_staging"
            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(fallback)
            dirs = [p for p in fallback.iterdir() if p.is_dir()]
            staging = dirs[0] if dirs else None

        print("\n[6/6] XXAR_Updater helper: folder swap scenarios")
        if sys.platform != "win32":
            r.ok("Helper tests skipped (non-Windows)")
        elif staging is None:
            r.fail("Helper tests skipped", "no staging dir available")
        else:
            test_helper_happy_path(r, temp_root, helper_cmd, staging)
            test_helper_stale_bin_old(r, temp_root, helper_cmd, staging)
            test_helper_missing_staging(r, temp_root, helper_cmd)
            test_helper_locked_retry(r, temp_root, helper_cmd, staging)

    finally:
        if server is not None:
            server.shutdown()
        if args.keep_artifacts:
            print(f"\nArtifacts preserved at: {temp_root}")
        else:
            try:
                shutil.rmtree(temp_root, ignore_errors=True)
            except Exception as e:
                print(f"(could not remove temp dir: {e})")

    print("\n" + "=" * 64)
    print(f"Results: {len(r.passed)} passed, {len(r.failed)} failed")
    print("=" * 64)
    if r.failed:
        print("\nFailures:")
        for name, detail in r.failed:
            suffix = f": {detail}" if detail else ""
            print(f"  - {name}{suffix}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
