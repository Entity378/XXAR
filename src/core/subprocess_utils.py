import os
import subprocess
import sys
from pathlib import Path

# Platform identification
IS_WINDOWS = sys.platform == "win32"
IS_LINUX = sys.platform.startswith("linux")

# Two independent signals so neither a missing env var nor a stripped
# /.flatpak-info gives a false negative.
IS_FLATPAK = (
    os.environ.get("XXAR_FLATPAK") == "1"
    or Path("/.flatpak-info").exists()
)


if IS_WINDOWS:
    _si = subprocess.STARTUPINFO()
    _si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    SUBPROCESS_KWARGS = {"startupinfo": _si}
    # Drop PyInstaller's _MEIPASS from PATH — Windows scans it when resolving
    if hasattr(sys, '_MEIPASS'):
        _clean_env = os.environ.copy()
        _meipass = sys._MEIPASS
        _clean_env["PATH"] = os.pathsep.join(
            p for p in _clean_env.get("PATH", "").split(os.pathsep)
            if not p.startswith(_meipass)
        )
        SUBPROCESS_KWARGS["env"] = _clean_env
else:
    SUBPROCESS_KWARGS = {}


# Bundled resources live in different places depending on how XXAR was launched.
# Resolve through the helpers below.

def is_frozen() -> bool:
    return hasattr(sys, '_MEIPASS') or getattr(sys, 'frozen', False)


def get_bundle_root() -> Path:
    meipass = getattr(sys, '_MEIPASS', None)
    if meipass:
        return Path(meipass)
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent
    # src/core/subprocess_utils.py → project root
    return Path(__file__).resolve().parent.parent.parent


def get_bundled_resources_dir() -> Path:
    root = get_bundle_root()
    if is_frozen():
        return root / "resources"
    return root / "src" / "resources"


def get_bundled_resource(*parts: str):
    # Existing path under resources/<parts...>, or None if it wasn't shipped.
    path = get_bundled_resources_dir().joinpath(*parts)
    return path if path.exists() else None
