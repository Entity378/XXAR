import os
import sys
import platform
import subprocess
from pathlib import Path

IS_WINDOWS = platform.system() == "Windows"

if IS_WINDOWS:
    _si = subprocess.STARTUPINFO()
    _si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    SUBPROCESS_KWARGS = {"startupinfo": _si}
    # Strip PyInstaller's _MEIPASS temp dir from PATH so Windows doesn't
    # scan it when resolving child executables (causes ~5 s delay).
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


# ── Bundled (read-only) asset path resolution ───────────────────
# The `resources/` directory lives in different places depending on how XXAR
# was invoked:
#   - Source:              <project_root>/src/resources/
#   - PyInstaller onefile: <sys._MEIPASS>/resources/
#   - PyInstaller onedir:  <exe_dir>/resources/
# Any code that needs to read a bundled asset should go through the helpers
# below instead of computing paths from `__file__` / `sys.executable`.

def is_frozen() -> bool:
    return hasattr(sys, '_MEIPASS') or getattr(sys, 'frozen', False)


def get_bundle_root() -> Path:
    # Top-level directory containing bundled assets (NOT user-writable state).
    meipass = getattr(sys, '_MEIPASS', None)
    if meipass:
        return Path(meipass)
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent
    # Source tree: src/core/subprocess_utils.py → project root
    return Path(__file__).resolve().parent.parent.parent


def get_bundled_resources_dir() -> Path:
    # Path to the bundled `resources/` dir. May not exist if the caller is
    # running in an environment where the dir wasn't shipped.
    root = get_bundle_root()
    if is_frozen():
        return root / "resources"
    return root / "src" / "resources"


def get_bundled_resource(*parts: str):
    # Return the existing path under `resources/<parts...>` or None. Prefer
    # this over manual joins when the caller needs to handle missing assets.
    path = get_bundled_resources_dir().joinpath(*parts)
    return path if path.exists() else None
