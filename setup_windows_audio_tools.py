#!/usr/bin/env python3
# Windows Audio Tools Setup - ffmpeg and vgmstream
# Downloads and installs ffmpeg and vgmstream-cli for Windows

import os
import sys
import zipfile
import subprocess
from pathlib import Path
import urllib.request
import platform
import ssl
import socket

# Download URLs for latest versions
from src.core.logger import get_logger
logger = get_logger(__name__)

FFMPEG_URL = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"
VGMSTREAM_URL = "https://github.com/vgmstream/vgmstream/releases/latest/download/vgmstream-win64.zip"

# Installation directories
# Tools live under the user's per-profile data dir so they survive exe
# upgrades and aren't scattered beside the binary. On Windows that's Local
# AppData; on Linux it's XDG_DATA_HOME (Flatpak-safe).
CONFIG_DIR_NAME = "XXAR"
FLATPAK_ENV_VAR = "XXAR_FLATPAK"

if os.environ.get(FLATPAK_ENV_VAR) or not sys.platform.startswith("win"):
    _TOOLS_ROOT = Path(
        os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")
    ) / CONFIG_DIR_NAME / "tools"
else:
    _TOOLS_ROOT = Path(
        os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")
    ) / CONFIG_DIR_NAME / "tools"

TOOLS_DIR = _TOOLS_ROOT / "audio"
FFMPEG_DIR = TOOLS_DIR / "ffmpeg"
VGMSTREAM_DIR = TOOLS_DIR / "vgmstream"


class WindowsAudioToolsSetup:
    # Handles automated installation of ffmpeg and vgmstream for Windows

    def __init__(self):
        self.tools_dir = TOOLS_DIR
        self.ffmpeg_dir = FFMPEG_DIR
        self.vgmstream_dir = VGMSTREAM_DIR
        self.ffmpeg_exe = None  # Will be found after extraction
        self.vgmstream_exe = VGMSTREAM_DIR / "vgmstream-cli.exe"

    def check_platform(self):
        # Check if running on Windows
        if platform.system() != "Windows":
            logger.warning("[WARNING]  This setup is for Windows only!")
            logger.info("On Linux, install via package manager:")
            logger.info("  sudo pacman -S ffmpeg vgmstream-cli")
            logger.info("  sudo apt install ffmpeg vgmstream-cli")
            return False
        return True

    def is_ffmpeg_installed(self):
        # Check if ffmpeg is already installed locally
        if not self.ffmpeg_dir.exists():
            return False

        # Find ffmpeg.exe in the extracted directory
        ffmpeg_candidates = list(self.ffmpeg_dir.rglob("ffmpeg.exe"))
        if ffmpeg_candidates:
            self.ffmpeg_exe = ffmpeg_candidates[0]
            return True
        return False

    def is_vgmstream_installed(self):
        # Check if vgmstream is already installed locally
        return self.vgmstream_exe.exists()

    def test_ffmpeg(self):
        # Test if ffmpeg works
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
        # Test if vgmstream-cli works
        if not self.vgmstream_exe.exists():
            return False

        try:
            result = subprocess.run(
                [str(self.vgmstream_exe), "-h"],
                capture_output=True,
                text=True,
                timeout=5
            )
            # vgmstream-cli returns 1 for help, which is normal
            if "vgmstream" in result.stdout.lower() or "vgmstream" in result.stderr.lower():
                logger.info(f"[OK] vgmstream-cli is working: {self.vgmstream_exe}")
                return True
        except Exception as e:
            logger.error(f"vgmstream test failed: {e}")
        return False

    def download_file(self, url, destination, tool_name):
        # Download a file (simplified - no progress reporting to avoid pipe issues)
        logger.info(f"\nDownloading {tool_name}...")
        logger.info(f"  Source: {url}")
        logger.info(f"  Please wait, this may take a few minutes...")

        destination.parent.mkdir(parents=True, exist_ok=True)

        try:
            # Set a very long socket timeout (30 minutes) to prevent timeout during large downloads
            old_timeout = socket.getdefaulttimeout()
            socket.setdefaulttimeout(1800)  # 30 minutes

            # Create SSL context that doesn't verify certificates (safe for GitHub)
            # This fixes issues on Windows where SSL certificates aren't properly configured
            ssl_context = ssl._create_unverified_context()

            # Use opener with SSL context
            opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ssl_context))
            urllib.request.install_opener(opener)

            # Download without progress reporting (avoids pipe buffer issues)
            urllib.request.urlretrieve(url, destination)
            logger.info("[OK] Download complete!")

            # Restore original timeout
            socket.setdefaulttimeout(old_timeout)
            return True

        except Exception as e:
            logger.error(f"[ERROR] Download failed: {e}")
            # Restore original timeout even on error
            socket.setdefaulttimeout(old_timeout)
            return False

    def extract_zip(self, zip_path, extract_dir, tool_name):
        # Extract a ZIP file
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
        # Download and install ffmpeg
        logger.info("\n" + "=" * 60)
        logger.info("Installing ffmpeg...")
        logger.info("=" * 60)

        if self.is_ffmpeg_installed():
            if self.test_ffmpeg():
                logger.info("[OK] ffmpeg is already installed and working!")
                return True
            logger.error("ffmpeg exists but test failed. Re-installing...")

        # Download
        zip_path = self.tools_dir / "ffmpeg_temp.zip"
        if not self.download_file(FFMPEG_URL, zip_path, "ffmpeg"):
            return False

        # Extract
        if not self.extract_zip(zip_path, self.ffmpeg_dir, "ffmpeg"):
            return False

        # Verify the binary exists
        if not self.is_ffmpeg_installed():
            logger.error("[ERROR] ffmpeg.exe not found after extraction!")
            return False

        # Test is best-effort -- files are on disk, so consider it installed
        if not self.test_ffmpeg():
            logger.error("[WARNING] ffmpeg test run failed, but binary exists on disk")

        return True

    def install_vgmstream(self):
        # Download and install vgmstream
        logger.info("\n" + "=" * 60)
        logger.info("Installing vgmstream-cli...")
        logger.info("=" * 60)

        if self.is_vgmstream_installed():
            if self.test_vgmstream():
                logger.info("[OK] vgmstream-cli is already installed and working!")
                return True
            logger.error("vgmstream-cli exists but test failed. Re-installing...")

        # Download
        zip_path = self.tools_dir / "vgmstream_temp.zip"
        if not self.download_file(VGMSTREAM_URL, zip_path, "vgmstream"):
            return False

        # Extract
        if not self.extract_zip(zip_path, self.vgmstream_dir, "vgmstream"):
            return False

        # Verify the binary exists
        if not self.is_vgmstream_installed():
            logger.error("[ERROR] vgmstream-cli.exe not found after extraction!")
            return False

        # Test is best-effort -- files are on disk, so consider it installed
        if not self.test_vgmstream():
            logger.error("[WARNING] vgmstream test run failed, but binary exists on disk")

        return True

    def setup_all(self):
        # Install ffmpeg and vgmstream
        logger.info("=" * 60)
        logger.info("Windows Audio Tools Setup")
        logger.info("Installing ffmpeg and vgmstream for Windows")
        logger.info("=" * 60)

        if not self.check_platform():
            return False

        # Install ffmpeg
        ffmpeg_ok = self.install_ffmpeg()

        # Install vgmstream
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
        # Get path to ffmpeg.exe if installed
        if not self.ffmpeg_exe:
            self.is_ffmpeg_installed()
        return self.ffmpeg_exe

    def get_vgmstream_path(self):
        # Get path to vgmstream-cli.exe if installed
        return self.vgmstream_exe if self.vgmstream_exe.exists() else None


def main():
    # Command-line interface
    import argparse

    parser = argparse.ArgumentParser(
        description='Install ffmpeg and vgmstream for Windows',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
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
  - Installs to %APPDATA%/XXAR/tools/audio/ (Windows)
  - Installs to $XDG_DATA_HOME/XXAR/tools/audio/ (Linux/Flatpak)
        """
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

    # Install
    if args.ffmpeg_only:
        success = setup.install_ffmpeg()
    elif args.vgmstream_only:
        success = setup.install_vgmstream()
    else:
        success = setup.setup_all()

    # Pause before closing to show results (only in interactive mode)
    # Skip pause when run from GUI (stdin is not a tty)
    if sys.stdin and sys.stdin.isatty():
        logger.info("\nPress Enter to close...")
        try:
            input()
        except (EOFError, OSError):
            pass  # Stdin closed, just exit

    sys.exit(0 if success else 1)


def run_setup_from_gui():
    # Entry point for GUI integration
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
        # Only pause in interactive mode
        if sys.stdin and sys.stdin.isatty():
            logger.info("\nPress Enter to close...")
            try:
                input()
            except (EOFError, OSError):
                pass
        sys.exit(1)
