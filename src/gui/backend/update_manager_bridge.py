import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot

from src.core.app_config import APP_NAME
from src.gui.backend.base_worker import BaseWorker, WorkerRegistry
from src.core.config_manager import get_settings_file, get_updates_dir
from src.core.logger import get_logger
from src.core.subprocess_utils import HOST_SPAWN_KWARGS, IS_FLATPAK, IS_WINDOWS, is_frozen

logger = get_logger(__name__)

_DEFAULT_GITHUB_API_URL = f"https://api.github.com/repos/Entity378/{APP_NAME}/releases/latest"
GITHUB_API_URL = os.environ.get("XXAR_UPDATE_API_URL_OVERRIDE", _DEFAULT_GITHUB_API_URL)

# Written by the installer; absent means a portable/ZIP copy, which has no auto-update.
_INSTALL_REGISTRY_PATH = rf"Software\{APP_NAME}"
_INSTALL_REGISTRY_VALUE = "InstallLocation"


def _read_install_location():
    if not IS_WINDOWS:
        return None
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _INSTALL_REGISTRY_PATH) as key:
            value, _ = winreg.QueryValueEx(key, _INSTALL_REGISTRY_VALUE)
            p = Path(value)
            return p if p.exists() else None
    except (OSError, ImportError):
        return None


def _get_real_exe_path():
    # Frozen sys.executable can point inside the onefile extraction dir; resolve the real launcher exe.
    if is_frozen():
        if IS_WINDOWS:
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


def _is_managed_install():
    # True for anything the installer put there, whichever channel wrote the marker: the installer
    # removes a leftover MSI product itself, so both are upgraded with the same .exe.
    if os.environ.get("XXAR_UPDATE_FORCE_PORTABLE") == "1":
        return False
    install_root = _read_install_location()
    if install_root is None:
        return False
    # If the running exe isn't under the registered root, notify only so we never upgrade a different copy.
    try:
        exe = Path(_get_real_exe_path()).resolve()
        root = Path(install_root).resolve()
        return os.path.normcase(str(exe)).startswith(os.path.normcase(str(root)) + os.sep)
    except OSError:
        return False


def _find_installer_asset(assets):
    # Prefix match instead of an exact name, so a renamed installer still resolves for already-shipped clients.
    for suffix in (".exe", ".msi"):
        for prefix in (f"{APP_NAME}-Installer-", f"{APP_NAME}-Setup-"):
            for asset in assets:
                name = asset.get("name", "")
                if name.startswith(prefix) and name.lower().endswith(suffix):
                    return asset
    return None


def _urlopen(req, timeout=10):
    # Fallback to an unverified SSL context
    try:
        return urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.URLError as e:
        if "CERTIFICATE_VERIFY_FAILED" in str(e):
            logger.error(f"[Updater] SSL verification failed for {getattr(req, 'full_url', '?')}; not falling back to unverified.")
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


def _safe_extract_tar(tf, dest):
    # filter='data' (Python 3.11.4+) blocks traversal/symlink escapes; older Python validates manually below.
    try:
        tf.extractall(dest, filter='data')
        return
    except TypeError:
        pass

    dest_resolved = Path(dest).resolve()
    for member in tf.getmembers():
        target = (dest_resolved / member.name).resolve()
        try:
            target.relative_to(dest_resolved)
        except ValueError:
            raise RuntimeError(f"Refusing to extract path-traversal entry: {member.name!r}")
        if member.issym() or member.islnk():
            link_target = (target.parent / member.linkname).resolve()
            try:
                link_target.relative_to(dest_resolved)
            except ValueError:
                raise RuntimeError(
                    f"Refusing to extract escaping link: {member.name!r} -> {member.linkname!r}"
                )
    tf.extractall(dest)


class UpdateCheckWorker(BaseWorker):
    # version, download_url, asset_name, release_notes
    updateAvailable = pyqtSignal(str, str, str, str)
    noUpdateAvailable = pyqtSignal()
    errorOccurred = pyqtSignal(str)

    def __init__(self, current_version, github_token=""):
        super().__init__()
        self.current_version = current_version
        self.github_token = github_token

    def work(self):
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

            version_str = clean_version_string(tag)
            release_notes = data.get("body", "") or ""
            assets = data.get("assets", [])

            if IS_WINDOWS:
                if not _is_managed_install():
                    # Portable/dev builds have no auto-update; notify only (like Flatpak) so the user grabs the ZIP.
                    self.updateAvailable.emit(version_str, "", "", release_notes)
                    return
                asset = _find_installer_asset(assets)
            else:
                asset = next((a for a in assets if a.get("name") == f"{APP_NAME}-linux-x86_64.flatpak"), None)

            if asset is None:
                # A release this build cannot install is never an error: the notification is the only message channel to frozen clients.
                logger.warning(f"[Updater] No runnable installer asset in release {tag}; notifying for manual update")
                self.updateAvailable.emit(version_str, "", "", release_notes)
                return

            # api url needs token auth, browser url works without
            download_url = asset["url"] if self.github_token else asset["browser_download_url"]
            self.updateAvailable.emit(version_str, download_url, asset["name"], release_notes)

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


def _prune_stale_update_artifacts(update_dir, keep=""):
    # Delete every prior update download except the one we are about to (re)fetch; leaves staging/ and updater.log alone.
    try:
        for entry in update_dir.iterdir():
            if not entry.is_file() or entry.name == keep:
                continue
            name = entry.name.lower()
            if name.endswith((".exe", ".msi", ".zip", ".tar.gz", ".flatpak")):
                try:
                    entry.unlink()
                    logger.info(f"[Updater] Removed stale update artifact: {entry.name}")
                except OSError as e:
                    logger.warning(f"[Updater] Could not remove stale artifact {entry.name}: {e}")
    except OSError as e:
        logger.warning(f"[Updater] Could not scan update cache for cleanup: {e}")


class UpdateDownloadWorker(BaseWorker):
    downloadProgress = pyqtSignal(int)  # percent
    # Emits (kind, path). kind is one of: "exe", "msi", "flatpak".
    downloadFinished = pyqtSignal(str, str)
    errorOccurred = pyqtSignal(str)

    def __init__(self, download_url, asset_name, github_token=""):
        super().__init__()
        self.download_url = download_url
        self.asset_name = asset_name
        self.github_token = github_token

    def work(self):
        try:
            update_dir = get_updates_dir()
            update_dir.mkdir(parents=True, exist_ok=True)
            archive_path = update_dir / self.asset_name

            # Downloaded installers are never deleted after they run, and each is well over 100 MB, so prune every prior artifact before fetching the new one.
            _prune_stale_update_artifacts(update_dir, keep=self.asset_name)

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
                        if self.is_cancelled():
                            return
                        chunk = response.read(block_size)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total_size > 0:
                            percent = min(int(downloaded * 100 / total_size), 100)
                            self.downloadProgress.emit(percent)

            lower = self.asset_name.lower()
            if lower.endswith(".exe"):
                # The installer carries its own payload; nothing to extract here.
                self.downloadFinished.emit("exe", str(archive_path))
            elif lower.endswith(".msi"):
                # msiexec consumes the .msi directly; kept runnable so a future return to MSI needs no new client.
                self.downloadFinished.emit("msi", str(archive_path))
            elif lower.endswith(".flatpak"):
                self.downloadFinished.emit("flatpak", str(archive_path))
            else:
                # Legacy tar.gz path preserved for the existing Linux Flatpak pipeline that may still stream a .tar.gz.
                with tarfile.open(archive_path, "r:gz") as tf:
                    _safe_extract_tar(tf, update_dir)
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
        self._workers = WorkerRegistry("updater")
        self._download_url = ""
        self._asset_name = ""
        self._downloaded_path = ""
        self._downloaded_kind = ""  # "exe", "msi", "flatpak"
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

    def canAutoUpdate(self):
        # False when the last check resolved no runnable asset
        return bool(self._download_url)

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
            logger.error(f"[Updater] Failed to save token: {e}")

    @pyqtSlot()
    def checkForUpdates(self):
        if self._workers.is_running("check"):
            return

        logger.info(f"[Updater] Checking for updates (current: {self._current_version})")

        worker = UpdateCheckWorker(self._current_version, self._github_token)
        worker.updateAvailable.connect(self._on_update_available)
        worker.noUpdateAvailable.connect(self._on_no_update)
        worker.errorOccurred.connect(self._on_check_error)
        self._workers.start("check", worker)

    def _on_update_available(self, version, download_url, asset_name, release_notes):
        logger.info(f"[Updater] Update available: {version} ({asset_name})")
        self._download_url = download_url
        self._asset_name = asset_name
        self.updateAvailable.emit(version, release_notes)

    def _on_no_update(self):
        logger.info("[Updater] Already up to date")
        self.updateNotAvailable.emit()

    def _on_check_error(self, message):
        logger.error(f"[Updater] Check error: {message}")
        self.updateError.emit(message)

    @pyqtSlot()
    def downloadAndInstall(self):
        if not self._download_url:
            # Portable build or a release this build cannot install; point the user at the releases page.
            self.updateError.emit(
                "This update cannot be installed automatically. "
                "Download the latest release from https://github.com/Entity378/XXAR/releases"
            )
            return

        if self._workers.is_running("download"):
            return

        logger.info(f"[Updater] Starting download from: {self._download_url}")

        worker = UpdateDownloadWorker(
            self._download_url, self._asset_name, self._github_token
        )
        worker.downloadProgress.connect(self._on_download_progress)
        worker.downloadFinished.connect(self._on_download_finished)
        worker.errorOccurred.connect(self._on_download_error)
        self._workers.start("download", worker)

    def _on_download_progress(self, percent):
        self.updateProgress.emit(percent)

    def _on_download_finished(self, kind, path):
        logger.info(f"[Updater] Download complete ({kind}): {path}")
        self._downloaded_kind = kind
        self._downloaded_path = path
        self.updateDownloaded.emit()

    def _on_download_error(self, message):
        logger.error(f"[Updater] Download error: {message}")
        self.updateError.emit(message)

    @pyqtSlot()
    def applyUpdate(self):
        # Two installers writing the same folder would fight; block re-entry from the Restart button.
        if getattr(self, "_apply_in_progress", False):
            return
        self._apply_in_progress = True
        handed_off = False
        try:
            if not self._downloaded_path or not Path(self._downloaded_path).exists():
                self.updateError.emit("Downloaded update not found")
                return

            current_exe = _get_real_exe_path()
            logger.info(f"[Updater] Applying update ({self._downloaded_kind})...")
            logger.info(f"[Updater] Real exe path: {current_exe}")
            logger.info(f"[Updater] Source: {self._downloaded_path}")

            if self._downloaded_kind == "exe":
                self._apply_exe_update(current_exe)
            elif self._downloaded_kind == "msi":
                self._apply_msi_update(current_exe)
            elif self._downloaded_kind == "flatpak":
                self._apply_linux_update(current_exe)
            else:
                self.updateError.emit(f"Unknown update kind: {self._downloaded_kind}")
                return

            logger.info("[Updater] Update handoff complete")
            handed_off = True
            self.updateApplied.emit()

        except Exception as e:
            logger.error(f"[Updater] Failed to apply update: {e}")
            self.updateError.emit(f"Failed to apply update: {e}")
        finally:
            if not handed_off:
                self._apply_in_progress = False

    def _apply_exe_update(self, current_exe):
        exe_path = Path(self._downloaded_path)

        logger.info(f"[Updater] Running: {exe_path} /silent")
        subprocess.Popen(
            [str(exe_path), "/silent"],
            cwd=tempfile.gettempdir(),
            creationflags=0x00000008,  # DETACHED_PROCESS
        )

    def _apply_msi_update(self, current_exe):
        msi_path = Path(self._downloaded_path)

        # Same command line as the old MSI, XXAR_SILENT=1 auto-advances and shows only progress.
        cmd_line = f'msiexec /i "{msi_path}" /norestart XXAR_SILENT=1'
        logger.info(f"[Updater] Running: {cmd_line}")
        subprocess.Popen(cmd_line, cwd=tempfile.gettempdir(), creationflags=0x00000008)  # DETACHED_PROCESS

    def _apply_linux_update(self, current_exe):
        bundle = Path(self._downloaded_path)

        # Linux ships only a .flatpak bundle; hand it to the host's flatpak (via the manifest's --talk-name finish-arg).
        if not IS_FLATPAK:
            self.updateError.emit(
                "Linux auto-update is only supported inside the Flatpak sandbox. "
                f"Bundle downloaded to: {bundle}\n"
                f"Install it manually with:  flatpak install --user {bundle}"
            )
            return

        # Host reinstalls in place (rewrites the OSTree ref); running app keeps the old commit until relaunch.
        args = [
            "flatpak-spawn", "--host",
            "flatpak", "install", "--user",
            "--noninteractive", "--assumeyes",
            "--reinstall",
            str(bundle),
        ]
        logger.info(f"[Updater] Running on host: {' '.join(args)}")
        subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            **HOST_SPAWN_KWARGS,
        )
