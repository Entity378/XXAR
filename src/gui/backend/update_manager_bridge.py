

import sys
import os
import json
import shutil
import ssl
import tarfile
import zipfile
import subprocess
import urllib.request
import urllib.error
from pathlib import Path

from PyQt5.QtCore import QObject, pyqtSlot, pyqtSignal, QThread

from src.core.config_manager import get_cache_dir, get_settings_file
from src.core.app_config import APP_NAME

GITHUB_API_URL = f"https://api.github.com/repos/Entity378/{APP_NAME}/releases/latest"

# Registry key the MSI installer writes (see installer_ws/Setup.cs). If absent
# we assume portable/ZIP install and route updates through the helper exe.
_MSI_REGISTRY_PATH = rf"Software\{APP_NAME}"
_MSI_REGISTRY_VALUE = "InstallLocation"


def _read_msi_install_location():
    if not sys.platform.startswith("win"):
        return None
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _MSI_REGISTRY_PATH) as key:
            value, _ = winreg.QueryValueEx(key, _MSI_REGISTRY_VALUE)
            p = Path(value)
            return p if p.exists() else None
    except (OSError, ImportError):
        return None


def _is_msi_install():
    return _read_msi_install_location() is not None


def _get_ssl_context():
    # pyinstaller doesn't bundle certs, so fall back to unverified if needed
    try:
        return ssl.create_default_context()
    except Exception:
        return ssl._create_unverified_context()


def _urlopen(req, timeout=10):
    try:
        return urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.URLError as e:
        if "CERTIFICATE_VERIFY_FAILED" in str(e):
            ctx = ssl._create_unverified_context()
            return urllib.request.urlopen(req, timeout=timeout, context=ctx)
        raise


_PRERELEASE_RANK = {"alpha": 0, "beta": 1, "rc": 2}


def clean_version_string(raw):
    cleaned = raw.strip()
    prefix = f"{APP_NAME}-v"
    if cleaned.startswith(prefix):
        return cleaned[len(prefix):]
    if cleaned.startswith(("v", "V")):
        return cleaned[1:]
    return cleaned


def parse_version(version_str):
    cleaned = clean_version_string(version_str)
    base, _, pre = cleaned.partition("-")

    numbers = []
    for part in base.split("."):
        try:
            numbers.append(int(part))
        except ValueError:
            numbers.append(0)
    while len(numbers) < 3:
        numbers.append(0)
    base_tuple = tuple(numbers[:3])

    if not pre:
        return base_tuple + (3, 0)

    pre_lower = pre.lower()
    for kind, rank in _PRERELEASE_RANK.items():
        if pre_lower.startswith(kind):
            rest = pre_lower[len(kind):].lstrip(".")
            try:
                pre_num = int(rest) if rest else 0
            except ValueError:
                pre_num = 0
            return base_tuple + (rank, pre_num)
    return base_tuple + (-1, 0)


class UpdateCheckWorker(QThread):
    # version, download_url, asset_name, release_notes
    updateAvailable = pyqtSignal(str, str, str, str)
    noUpdateAvailable = pyqtSignal()
    errorOccurred = pyqtSignal(str)

    def __init__(self, current_version, github_token=""):
        super().__init__()
        self.current_version = current_version
        self.github_token = github_token

    def run(self):
        try:
            req = urllib.request.Request(GITHUB_API_URL)
            req.add_header("Accept", "application/vnd.github.v3+json")
            req.add_header("User-Agent", f"{APP_NAME}-Updater")

            if self.github_token:
                req.add_header("Authorization", f"token {self.github_token}")

            with _urlopen(req, timeout=10) as response:
                data = json.loads(response.read().decode())

            tag = data.get("tag_name", "")
            if not tag:
                self.errorOccurred.emit("No tag found in latest release")
                return

            latest_version = parse_version(tag)
            current_version = parse_version(self.current_version)

            if latest_version <= current_version:
                self.noUpdateAvailable.emit()
                return

            if sys.platform.startswith("win"):
                # Prefer MSI if we know the install came from the MSI, else
                # fall back to the portable ZIP. Track the raw tag so we can
                # probe version-tagged MSI asset names.
                version_tag = clean_version_string(tag)
                if _is_msi_install():
                    asset_candidates = [
                        f"{APP_NAME}-Installer-v{version_tag}.msi",
                        f"{APP_NAME}-Installer.msi",
                    ]
                else:
                    asset_candidates = [f"{APP_NAME}-windows-x64.zip"]
            else:
                asset_candidates = [f"{APP_NAME}-linux-x64.flatpak"]

            download_url = ""
            asset_name = ""
            assets_by_name = {a["name"]: a for a in data.get("assets", [])}
            for candidate in asset_candidates:
                asset = assets_by_name.get(candidate)
                if asset:
                    asset_name = candidate
                    # api url needs token auth, browser url works without
                    download_url = asset["url"] if self.github_token else asset["browser_download_url"]
                    break

            if not download_url:
                tried = ", ".join(asset_candidates)
                self.errorOccurred.emit(f"No matching asset found in release (tried: {tried})")
                return

            version_str = clean_version_string(tag)
            release_notes = data.get("body", "") or ""
            self.updateAvailable.emit(version_str, download_url, asset_name, release_notes)

        except urllib.error.HTTPError as e:
            if e.code == 404:
                self.errorOccurred.emit("No releases found (repo may be private - set a GitHub token in Settings)")
            elif e.code == 401 or e.code == 403:
                self.errorOccurred.emit("GitHub API authentication failed - check your token")
            else:
                self.errorOccurred.emit(f"GitHub API error: {e.code} {e.reason}")
        except urllib.error.URLError as e:
            self.errorOccurred.emit(f"Network error: {e.reason}")
        except Exception as e:
            self.errorOccurred.emit(f"Update check failed: {e}")


class UpdateDownloadWorker(QThread):
    downloadProgress = pyqtSignal(int)  # percent
    # Emits (kind, path). kind is one of: "msi", "zip_staging", "flatpak".
    downloadFinished = pyqtSignal(str, str)
    errorOccurred = pyqtSignal(str)

    def __init__(self, download_url, asset_name, github_token=""):
        super().__init__()
        self.download_url = download_url
        self.asset_name = asset_name
        self.github_token = github_token

    def run(self):
        try:
            update_dir = get_cache_dir() / "updates"
            update_dir.mkdir(parents=True, exist_ok=True)
            archive_path = update_dir / self.asset_name

            req = urllib.request.Request(self.download_url)
            req.add_header("User-Agent", f"{APP_NAME}-Updater")
            req.add_header("Accept", "application/octet-stream")
            if self.github_token:
                req.add_header("Authorization", f"token {self.github_token}")

            with _urlopen(req, timeout=300) as response:
                total_size = int(response.headers.get("Content-Length", 0))
                block_size = 8192
                downloaded = 0

                with open(archive_path, "wb") as f:
                    while True:
                        chunk = response.read(block_size)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total_size > 0:
                            percent = min(int(downloaded * 100 / total_size), 100)
                            self.downloadProgress.emit(percent)

            lower = self.asset_name.lower()
            if lower.endswith(".msi"):
                # msiexec consumes the .msi directly; no extraction.
                self.downloadFinished.emit("msi", str(archive_path))
            elif lower.endswith(".zip"):
                # Portable: pre-extract into a staging folder the helper will
                # move into Resources/Bin. Nuke any previous staging first.
                staging_parent = update_dir / "staging"
                if staging_parent.exists():
                    shutil.rmtree(str(staging_parent), ignore_errors=True)
                staging_parent.mkdir(parents=True, exist_ok=True)
                with zipfile.ZipFile(archive_path, "r") as zf:
                    zf.extractall(staging_parent)
                archive_path.unlink(missing_ok=True)
                # The zip's top-level entry is the PyInstaller COLLECT folder
                # (dist/XXAR/). Resolve it regardless of its exact name.
                entries = [p for p in staging_parent.iterdir() if p.is_dir()]
                if len(entries) != 1:
                    self.errorOccurred.emit(
                        f"Expected a single top-level folder in {self.asset_name}, "
                        f"found {len(entries)}"
                    )
                    return
                staging_root = entries[0]
                if not (staging_root / f"{APP_NAME}.exe").exists():
                    self.errorOccurred.emit(f"{APP_NAME}.exe not found inside staging")
                    return
                self.downloadFinished.emit("zip_staging", str(staging_root))
            elif lower.endswith(".flatpak"):
                self.downloadFinished.emit("flatpak", str(archive_path))
            else:
                # Legacy tar.gz path preserved for existing Linux Flatpak
                # pipeline that may still stream a .tar.gz.
                with tarfile.open(archive_path, "r:gz") as tf:
                    tf.extractall(update_dir)
                binary_path = update_dir / APP_NAME
                if not binary_path.exists():
                    self.errorOccurred.emit("Extracted binary not found")
                    return
                archive_path.unlink(missing_ok=True)
                self.downloadFinished.emit("flatpak", str(binary_path))

        except Exception as e:
            self.errorOccurred.emit(f"Download failed: {e}")


class UpdateManagerBridge(QObject):
    updateAvailable = pyqtSignal(str, str)  # latest_version, release_notes
    updateNotAvailable = pyqtSignal()
    updateDownloaded = pyqtSignal()
    updateProgress = pyqtSignal(int)      # percent
    updateError = pyqtSignal(str)         # message
    updateApplied = pyqtSignal()          # binary replaced successfully

    def __init__(self):
        super().__init__()
        self._check_worker = None
        self._download_worker = None
        self._download_url = ""
        self._asset_name = ""
        self._downloaded_path = ""
        self._downloaded_kind = ""  # "msi", "zip_staging", "flatpak"
        self._current_version = ""
        self._github_token = ""

        self._load_token()

    def _load_token(self):
        try:
            settings_file = get_settings_file()
            if settings_file.exists():
                with open(settings_file, "r") as f:
                    settings = json.load(f)
                self._github_token = settings.get("github_token", "")
        except Exception:
            pass

    def setCurrentVersion(self, version):
        self._current_version = version

    def setGithubToken(self, token):
        self._github_token = token
        try:
            settings_file = get_settings_file()
            settings = {}
            if settings_file.exists():
                with open(settings_file, "r") as f:
                    settings = json.load(f)
            settings["github_token"] = token
            settings_file.parent.mkdir(parents=True, exist_ok=True)
            with open(settings_file, "w") as f:
                json.dump(settings, f, indent=2)
        except Exception as e:
            print(f"[Updater] Failed to save token: {e}")

    @pyqtSlot()
    def checkForUpdates(self):
        if self._check_worker and self._check_worker.isRunning():
            return

        print(f"[Updater] Checking for updates (current: {self._current_version})")

        self._check_worker = UpdateCheckWorker(self._current_version, self._github_token)
        self._check_worker.updateAvailable.connect(self._on_update_available)
        self._check_worker.noUpdateAvailable.connect(self._on_no_update)
        self._check_worker.errorOccurred.connect(self._on_check_error)
        self._check_worker.start()

    def _on_update_available(self, version, download_url, asset_name, release_notes):
        print(f"[Updater] Update available: {version} ({asset_name})")
        self._download_url = download_url
        self._asset_name = asset_name
        self.updateAvailable.emit(version, release_notes)

    def _on_no_update(self):
        print("[Updater] Already up to date")
        self.updateNotAvailable.emit()

    def _on_check_error(self, message):
        print(f"[Updater] Check error: {message}")
        self.updateError.emit(message)

    @pyqtSlot()
    def downloadAndInstall(self):
        if not self._download_url:
            self.updateError.emit("No download URL available")
            return

        if self._download_worker and self._download_worker.isRunning():
            return

        print(f"[Updater] Starting download from: {self._download_url}")

        self._download_worker = UpdateDownloadWorker(
            self._download_url, self._asset_name, self._github_token
        )
        self._download_worker.downloadProgress.connect(self._on_download_progress)
        self._download_worker.downloadFinished.connect(self._on_download_finished)
        self._download_worker.errorOccurred.connect(self._on_download_error)
        self._download_worker.start()

    def _on_download_progress(self, percent):
        self.updateProgress.emit(percent)

    def _on_download_finished(self, kind, path):
        print(f"[Updater] Download complete ({kind}): {path}")
        self._downloaded_kind = kind
        self._downloaded_path = path
        self.updateDownloaded.emit()

    def _on_download_error(self, message):
        print(f"[Updater] Download error: {message}")
        self.updateError.emit(message)

    @staticmethod
    def _get_real_exe_path():
        # pyinstaller onefile: sys.executable is inside the temp _MEI dir,
        # not the actual exe on disk
        if hasattr(sys, '_MEIPASS'):
            if sys.platform.startswith("win"):
                import ctypes
                buf = ctypes.create_unicode_buffer(260)
                ctypes.windll.kernel32.GetModuleFileNameW(None, buf, 260)
                real_path = buf.value
                if real_path and Path(real_path).exists():
                    return real_path
            # linux/macOS: sys.argv[0] is the real binary path
            resolved = str(Path(sys.argv[0]).resolve())
            if Path(resolved).exists():
                return resolved
        return sys.executable

    @staticmethod
    def _get_install_root(current_exe):
        # Onefolder layout: <root>/Resources/Bin/XXAR.exe.
        # The install root is the grand-grandparent of the exe.
        exe = Path(current_exe).resolve()
        parent = exe.parent
        if parent.name.lower() == "bin" and parent.parent.name.lower() == "resources":
            return parent.parent.parent
        # Fallback: exe directly in install root (dev runs, or unexpected layout).
        return parent

    def _helper_exe_path(self, install_root):
        helper = install_root / "Resources" / "Updater" / f"{APP_NAME} Updater.exe"
        return helper if helper.exists() else None

    @pyqtSlot()
    def applyUpdate(self):
        if not self._downloaded_path or not Path(self._downloaded_path).exists():
            self.updateError.emit("Downloaded update not found")
            return

        try:
            current_exe = self._get_real_exe_path()
            print(f"[Updater] Applying update ({self._downloaded_kind})...")
            print(f"[Updater] Real exe path: {current_exe}")
            print(f"[Updater] Source: {self._downloaded_path}")

            if self._downloaded_kind == "msi":
                self._apply_msi_update(current_exe)
            elif self._downloaded_kind == "zip_staging":
                self._apply_zip_update(current_exe)
            elif self._downloaded_kind == "flatpak":
                self._apply_linux_update(current_exe)
            else:
                self.updateError.emit(f"Unknown update kind: {self._downloaded_kind}")
                return

            print(f"[Updater] Update handoff complete")
            self.updateApplied.emit()

        except Exception as e:
            print(f"[Updater] Failed to apply update: {e}")
            self.updateError.emit(f"Failed to apply update: {e}")

    def _apply_msi_update(self, current_exe):
        msi_path = Path(self._downloaded_path)
        install_root = self._get_install_root(current_exe)

        # /qr = reduced UI (progress bar only), /norestart = leave reboot to us
        args = [
            "msiexec", "/i", str(msi_path),
            "/qr", "/norestart",
            f"APPDIR={install_root}",
        ]
        print(f"[Updater] Running: {' '.join(args)}")
        subprocess.Popen(args, creationflags=0x00000008)  # DETACHED_PROCESS

    def _apply_zip_update(self, current_exe):
        staging_dir = Path(self._downloaded_path)
        install_root = self._get_install_root(current_exe)
        helper = self._helper_exe_path(install_root)
        if helper is None:
            raise RuntimeError(
                f"Updater helper not found under {install_root / 'Resources' / 'Updater'}"
            )

        DETACHED_PROCESS = 0x00000008
        CREATE_NEW_PROCESS_GROUP = 0x00000200
        args = [
            str(helper),
            "--dist-dir", str(install_root),
            "--staging-dir", str(staging_dir),
        ]
        print(f"[Updater] Spawning helper: {' '.join(args)}")
        subprocess.Popen(
            args,
            creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
            close_fds=True,
        )

    def _apply_linux_update(self, current_exe):
        new_binary = Path(self._downloaded_path)
        target = Path(current_exe)

        backup = target.with_suffix(".bak")
        if backup.exists():
            backup.unlink()

        # can't overwrite a running binary on linux (ETXTBSY), rename it first
        target.rename(backup)
        shutil.copy2(str(new_binary), str(target))
        os.chmod(str(target), 0o755)

        new_binary.unlink(missing_ok=True)

        print(f"[Updater] Binary replaced: {target}")
        print(f"[Updater] Backup at: {backup}")
