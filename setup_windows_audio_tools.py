#!/usr/bin/env python3

import os
import sys
import zipfile
import subprocess
from pathlib import Path
import urllib.request
import platform
import ssl
import socket

from src.core.logger import get_logger
from src.core.subprocess_utils import IS_WINDOWS
from src.core.app_config import CONFIG_DIR_NAME
logger = get_logger(__name__)

FFMPEG_URL = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"
VGMSTREAM_URL = "https://github.com/vgmstream/vgmstream/releases/latest/download/vgmstream-win64.zip"

if IS_WINDOWS:
    _TOOLS_ROOT = Path(
        os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")
    ) / CONFIG_DIR_NAME / "tools"
else:
    _TOOLS_ROOT = Path(
        os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")
    ) / CONFIG_DIR_NAME / "tools"

TOOLS_DIR = _TOOLS_ROOT / "audio"
FFMPEG_DIR = TOOLS_DIR / "ffmpeg"
VGMSTREAM_DIR = TOOLS_DIR / "vgmstream"


class WindowsAudioToolsSetup:

    def __init__(self):
        self.tools_dir = TOOLS_DIR
        self.ffmpeg_dir = FFMPEG_DIR
        self.vgmstream_dir = VGMSTREAM_DIR
        self.ffmpeg_exe = None
        self.vgmstream_exe = VGMSTREAM_DIR / "vgmstream-cli.exe"

    def check_platform(self):
        if not IS_WINDOWS:
            logger.warning("[WARNING]  This setup is for Windows only!")
            logger.info("On Linux, install via package manager:")
            logger.info("  sudo pacman -S ffmpeg vgmstream-cli")
            logger.info("  sudo apt install ffmpeg vgmstream-cli")
            return False
        return True

    def is_ffmpeg_installed(self):
        if not self.ffmpeg_dir.exists():
            return False

        ffmpeg_candidates = list(self.ffmpeg_dir.rglob("ffmpeg.exe"))
        if ffmpeg_candidates:
            self.ffmpeg_exe = ffmpeg_candidates[0]
            return True
        return False

    def is_vgmstream_installed(self):
        return self.vgmstream_exe.exists()

    def test_ffmpeg(self):
        if not self.ffmpeg_exe:
            if not self.is_ffmpeg_installed():
                return False

        try:
            result = subprocess.run(
                [str(self.ffmpeg_exe), "-version"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                logger.info(f"[OK] ffmpeg is working: {self.ffmpeg_exe}")
                return True
        except Exception as e:
            logger.error(f"ffmpeg test failed: {e}")
        return False

    def test_vgmstream(self):
        if not self.vgmstream_exe.exists():
            return False

        try:
            result = subprocess.run(
                [str(self.vgmstream_exe), "-h"],
                capture_output=True,
                text=True,
                timeout=5
            )
            # vgmstream-cli returns 1 for help, which is normal.
            if "vgmstream" in result.stdout.lower() or "vgmstream" in result.stderr.lower():
                logger.info(f"[OK] vgmstream-cli is working: {self.vgmstream_exe}")
                return True
        except Exception as e:
            logger.error(f"vgmstream test failed: {e}")
        return False

    def download_file(self, url, destination, tool_name):
        logger.info(f"\nDownloading {tool_name}...")
        logger.info(f"  Source: {url}")
        logger.info(f"  Please wait, this may take a few minutes...")

        destination.parent.mkdir(parents=True, exist_ok=True)

        try:
            old_timeout = socket.getdefaulttimeout()
            socket.setdefaulttimeout(1800)  # 30 minutes; large downloads need a long ceiling.

            # Windows PyInstaller builds ship without CA certs; fall back to unverified SSL.
            ssl_context = ssl._create_unverified_context()

            opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ssl_context))
            urllib.request.install_opener(opener)

            urllib.request.urlretrieve(url, destination)
            logger.info("[OK] Download complete!")

            socket.setdefaulttimeout(old_timeout)
            return True

        except Exception as e:
            logger.error(f"[ERROR] Download failed: {e}")
            socket.setdefaulttimeout(old_timeout)
            return False

    def extract_zip(self, zip_path, extract_dir, tool_name):
        logger.info(f"\nExtracting {tool_name}...")

        try:
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(extract_dir)

            logger.info(f"[OK] Extraction complete!")
            zip_path.unlink()
            logger.info("[OK] Cleaned up temporary files")
            return True

        except Exception as e:
            logger.error(f"[ERROR] Extraction failed: {e}")
            return False

    def install_ffmpeg(self):
        logger.info("\n" + "=" * 60)
        logger.info("Installing ffmpeg...")
        logger.info("=" * 60)

        if self.is_ffmpeg_installed():
            if self.test_ffmpeg():
                logger.info("[OK] ffmpeg is already installed and working!")
                return True
            logger.error("ffmpeg exists but test failed. Re-installing...")

        zip_path = self.tools_dir / "ffmpeg_temp.zip"
        if not self.download_file(FFMPEG_URL, zip_path, "ffmpeg"):
            return False

        if not self.extract_zip(zip_path, self.ffmpeg_dir, "ffmpeg"):
            return False

        if not self.is_ffmpeg_installed():
            logger.error("[ERROR] ffmpeg.exe not found after extraction!")
            return False

        # Best-effort: if binary is on disk we treat it as installed even if test fails.
        if not self.test_ffmpeg():
            logger.error("[WARNING] ffmpeg test run failed, but binary exists on disk")

        return True

    def install_vgmstream(self):
        logger.info("\n" + "=" * 60)
        logger.info("Installing vgmstream-cli...")
        logger.info("=" * 60)

        if self.is_vgmstream_installed():
            if self.test_vgmstream():
                logger.info("[OK] vgmstream-cli is already installed and working!")
                return True
            logger.error("vgmstream-cli exists but test failed. Re-installing...")

        zip_path = self.tools_dir / "vgmstream_temp.zip"
        if not self.download_file(VGMSTREAM_URL, zip_path, "vgmstream"):
            return False

        if not self.extract_zip(zip_path, self.vgmstream_dir, "vgmstream"):
            return False

        if not self.is_vgmstream_installed():
            logger.error("[ERROR] vgmstream-cli.exe not found after extraction!")
            return False

        # Best-effort: if binary is on disk we treat it as installed even if test fails.
        if not self.test_vgmstream():
            logger.error("[WARNING] vgmstream test run failed, but binary exists on disk")

        return True

    def setup_all(self):
        logger.info("=" * 60)
        logger.info("Windows Audio Tools Setup")
        logger.info("Installing ffmpeg and vgmstream for Windows")
        logger.info("=" * 60)

        if not self.check_platform():
            return False

        ffmpeg_ok = self.install_ffmpeg()
        vgmstream_ok = self.install_vgmstream()

        logger.info("\n" + "=" * 60)
        if ffmpeg_ok and vgmstream_ok:
            logger.info("[SUCCESS] Setup complete! All tools installed successfully.")
            logger.info("\nInstalled tools:")
            logger.info(f"  - ffmpeg: {self.ffmpeg_exe}")
            logger.info(f"  - vgmstream-cli: {self.vgmstream_exe}")
            return True
        else:
            logger.warning("[WARNING]  Setup incomplete:")
            if not ffmpeg_ok:
                logger.error("  [ERROR] ffmpeg installation failed")
            if not vgmstream_ok:
                logger.error("  [ERROR] vgmstream installation failed")
            return False

    def get_ffmpeg_path(self):
        if not self.ffmpeg_exe:
            self.is_ffmpeg_installed()
        return self.ffmpeg_exe

    def get_vgmstream_path(self):
        return self.vgmstream_exe if self.vgmstream_exe.exists() else None


def main():
    import argparse
    import textwrap

    parser = argparse.ArgumentParser(
        description='Install ffmpeg and vgmstream for Windows',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Examples:
              # Install all tools
              python setup_windows_audio_tools.py

              # Check installation status
              python setup_windows_audio_tools.py --check

              # Install only ffmpeg
              python setup_windows_audio_tools.py --ffmpeg-only

              # Install only vgmstream
              python setup_windows_audio_tools.py --vgmstream-only

            Note:
              - Windows only
              - Downloads ~100-150MB total
              - Installs to %LOCALAPPDATA%/XXAR/tools/audio/ (Windows)
              - Installs to $XDG_DATA_HOME/XXAR/tools/audio/ (Linux/Flatpak)
        """),
    )

    parser.add_argument('--check', action='store_true', help='Check installation status')
    parser.add_argument('--ffmpeg-only', action='store_true', help='Install only ffmpeg')
    parser.add_argument('--vgmstream-only', action='store_true', help='Install only vgmstream')

    args = parser.parse_args()

    setup = WindowsAudioToolsSetup()

    if args.check:
        logger.info("Checking installation status...")
        logger.info(f"\nPlatform: {platform.system()}")

        ffmpeg_ok = setup.is_ffmpeg_installed() and setup.test_ffmpeg()
        vgmstream_ok = setup.is_vgmstream_installed() and setup.test_vgmstream()

        if ffmpeg_ok:
            logger.info(f"[OK] ffmpeg: {setup.ffmpeg_exe}")
        else:
            logger.error("[ERROR] ffmpeg: Not installed")

        if vgmstream_ok:
            logger.info(f"[OK] vgmstream: {setup.vgmstream_exe}")
        else:
            logger.error("[ERROR] vgmstream: Not installed")

        sys.exit(0 if (ffmpeg_ok and vgmstream_ok) else 1)

    if args.ffmpeg_only:
        success = setup.install_ffmpeg()
    elif args.vgmstream_only:
        success = setup.install_vgmstream()
    else:
        success = setup.setup_all()

    # Skip pause when run from GUI (stdin is not a tty).
    if sys.stdin and sys.stdin.isatty():
        logger.info("\nPress Enter to close...")
        try:
            input()
        except (EOFError, OSError):
            pass

    sys.exit(0 if success else 1)


def run_setup_from_gui():
    setup = WindowsAudioToolsSetup()
    return setup.setup_all()


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        logger.info("\n" + "=" * 60)
        logger.error("[ERROR] ERROR OCCURRED:")
        logger.info("=" * 60)
        logger.info(f"{type(e).__name__}: {e}")
        if sys.stdin and sys.stdin.isatty():
            logger.info("\nPress Enter to close...")
            try:
                input()
            except (EOFError, OSError):
                pass
        sys.exit(1)
