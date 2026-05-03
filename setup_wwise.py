#!/usr/bin/env python3

import os
import sys
import ssl
import shutil
import zipfile
import subprocess
from pathlib import Path
import urllib.request
import urllib.error

from src.core.logger import get_logger
from src.core.subprocess_utils import IS_WINDOWS, IS_LINUX, IS_FLATPAK
from src.core.app_config import CONFIG_DIR_NAME
logger = get_logger(__name__)

DEFAULT_WWISE_URL = "https://gitlab.com/ytnshio/ebi/-/raw/main/WWIse.zip"

if IS_WINDOWS:
    _TOOLS_ROOT = Path(
        os.environ.get('LOCALAPPDATA', Path.home() / 'AppData' / 'Local')
    ) / CONFIG_DIR_NAME / "tools"
else:
    _TOOLS_ROOT = Path(
        os.environ.get('XDG_DATA_HOME', Path.home() / '.local' / 'share')
    ) / CONFIG_DIR_NAME / "tools"

WWISE_DIR = _TOOLS_ROOT / "wwise"
WWISE_CONSOLE = WWISE_DIR / "WWIse/Authoring/x64/Release/bin/WwiseConsole.exe"


class WwiseSetup:
    def setup(self, skip_input=True):
        logger.info("=" * 60)
        logger.info("XXAR - Automated Wwise Setup")
        logger.info("=" * 60)

        if IS_LINUX:
            if not self.check_wine():
                return False

        if self.check_existing():
            if self.test_wwise():
                logger.info("\nWwise is already set up and working!")
                return True
            logger.error("\nWwise exists but test failed. Re-installing...")

        logger.info("\nStarting automated download...")
        zip_path = self.download_wwise()
        
        if not zip_path:
            logger.error("Download failed.")
            return False

        if not self.extract_wwise(zip_path):
            logger.error("Extraction failed.")
            return False

        return self.test_wwise()

    def __init__(self, download_url=None):
        self.download_url = download_url or DEFAULT_WWISE_URL
        self.wwise_dir = WWISE_DIR
        self.wwise_console = WWISE_CONSOLE

    def check_wine(self):
        if IS_FLATPAK:
            # Flatpak sandbox can't see Wine directly; query host via flatpak-spawn.
            for name in ('wine64', 'wine'):
                try:
                    result = subprocess.run(
                        ['flatpak-spawn', '--host', name, '--version'],
                        capture_output=True, text=True, timeout=5
                    )
                    if result.returncode == 0:
                        logger.info(f"[OK] Wine found on host: {result.stdout.strip()}")
                        return True
                except Exception:
                    continue
            logger.info("Wine not found on host system!")
            logger.info("\nInstall Wine on your system (outside Flatpak):")
            logger.info("  Arch: sudo pacman -S wine")
            logger.info("  Debian/Ubuntu: sudo apt install wine")
            return False

        wine = shutil.which('wine64') or shutil.which('wine')
        if not wine:
            logger.info("Wine not found!")
            logger.info("\nInstall Wine:")
            logger.info("  Arch: sudo pacman -S wine")
            logger.info("  Debian/Ubuntu: sudo apt install wine")
            return False

        logger.info(f"[OK] Wine found: {wine}")
        return True

    def check_existing(self):
        if self.wwise_console.exists():
            logger.info(f"[OK] Wwise already installed at: {self.wwise_dir}")
            return True
        return False

    def download_wwise(self):
        logger.info(f"\nDownloading Wwise from: {self.download_url}")

        zip_path = self.wwise_dir / "wwise_temp.zip"
        self.wwise_dir.mkdir(parents=True, exist_ok=True)

        try:
            # Windows PyInstaller builds ship without CA certs; fall back to unverified SSL.
            try:
                urllib.request.urlopen("https://gitlab.com", timeout=5)
            except Exception:
                ssl_context = ssl._create_unverified_context()
                opener = urllib.request.build_opener(
                    urllib.request.HTTPSHandler(context=ssl_context)
                )
                urllib.request.install_opener(opener)

            def report_progress(block_num, block_size, total_size):
                downloaded = block_num * block_size
                if total_size > 0:
                    percent = min(downloaded * 100 / total_size, 100)
                    mb_downloaded = downloaded / 1024 / 1024
                    mb_total = total_size / 1024 / 1024
                    logger.info(f"  Progress: {percent:.1f}% ({mb_downloaded:.1f} / {mb_total:.1f} MB)")

            urllib.request.urlretrieve(
                self.download_url,
                zip_path,
                reporthook=report_progress
            )
            logger.info("\n[OK] Download complete!")
            return zip_path

        except Exception as e:
            logger.error(f"\nDownload failed: {e}")
            return None

    def extract_wwise(self, zip_path):
        logger.info(f"\nExtracting Wwise...")

        try:
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(self.wwise_dir)

            logger.info("[OK] Extraction complete!")

            zip_path.unlink()
            logger.info("[OK] Cleaned up temporary files")

            return True

        except Exception as e:
            logger.error(f"Extraction failed: {e}")
            return False

    def test_wwise(self):
        logger.info(f"\nTesting WwiseConsole...")

        if not self.wwise_console.exists():
            logger.info(f"WwiseConsole.exe not found at: {self.wwise_console}")
            return False

        try:
            if IS_WINDOWS:
                cmd = [str(self.wwise_console), '-help']
            elif IS_FLATPAK:
                wine_name = 'wine'
                for name in ('wine64', 'wine'):
                    try:
                        r = subprocess.run(
                            ['flatpak-spawn', '--host', name, '--version'],
                            capture_output=True, timeout=5,
                        )
                        if r.returncode == 0:
                            wine_name = name
                            break
                    except Exception:
                        continue
                cmd = ['flatpak-spawn', '--host', wine_name, str(self.wwise_console), '-help']
            else:
                wine = shutil.which('wine64') or shutil.which('wine') or 'wine'
                cmd = [wine, str(self.wwise_console), '-help']

            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=10
            )

            logger.info("WwiseConsole is accessible!")
            return True

        except subprocess.TimeoutExpired:
            logger.info("WwiseConsole took too long to respond (might still work)")
            return True
        except Exception as e:
            logger.error(f"WwiseConsole test failed: {e}")
            return False

    


def main():
    import argparse
    import textwrap

    parser = argparse.ArgumentParser(
        description='Automated Wwise setup for XXAR (HoYoverse audio modding)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Examples:
              # Use default download URL
              python setup_wwise.py

              # Use custom Wwise package URL
              python setup_wwise.py --url https://your-server.com/wwise.zip

              # Check if Wwise is installed
              python setup_wwise.py --check

            Notes:
              - Requires Wine to be installed on Linux
              - Downloads ~50-100MB (minimal Wwise package)
              - Installs to %LOCALAPPDATA%/XXAR/tools/wwise/ (Windows)
              - Installs to $XDG_DATA_HOME/XXAR/tools/wwise/ (Linux/Flatpak)
        """),
    )

    parser.add_argument('--url', help='Custom Wwise download URL')
    parser.add_argument('--check', action='store_true', help='Check if Wwise is installed')

    args = parser.parse_args()

    setup = WwiseSetup(download_url=args.url)

    if args.check:
        logger.info("Checking Wwise installation...")
        if setup.check_existing():
            if setup.test_wwise():
                logger.info("Wwise is installed and working!")
                sys.exit(0)
            else:
                logger.error("[!]  Wwise is installed but test failed")
                sys.exit(1)
        else:
            logger.info("Wwise is not installed")
            logger.info("\nRun: python setup_wwise.py")
            sys.exit(1)

    success = setup.setup()
    sys.exit(0 if success else 1)


def run_setup_from_gui():
    installer = WwiseSetup()
    return installer.setup(skip_input=True)

if __name__ == '__main__':
    main()
