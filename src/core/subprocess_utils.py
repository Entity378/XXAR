import os
import sys
import subprocess
from pathlib import Path

# ── Platform identification (single source of truth) ────────────────────
# Every gating check in the app should import from here, not compute its own
# `platform.system()` / `sys.platform` / `os.name` comparison. The previous
# scattered checks drifted out of sync (see `os.name == "nt"`, `sys.platform
# == "win32"`, `sys.platform.startswith("win")`, `platform.system() ==
# "Windows"` all coexisting in the codebase). Use `platform.system()` only
# for human-readable strings (logs, settings page, telemetry).
IS_WINDOWS = sys.platform == "win32"
IS_LINUX = sys.platform.startswith("linux")

# Flatpak sandbox detection. Two independent signals so neither a missing
# env var (e.g. when the wrapper is bypassed) nor a stripped /.flatpak-info
# (e.g. inside a nested subprocess) produces a false negative:
#   - XXAR_FLATPAK=1 is set by xxar-wrapper.sh in the Flatpak manifest.
#   - /.flatpak-info is injected by the Flatpak runtime into every sandbox.
IS_FLATPAK = (
    os.environ.get("XXAR_FLATPAK") == "1"
    or Path("/.flatpak-info").exists()
)


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
