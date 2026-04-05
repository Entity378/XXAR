import os
import sys
import platform
import subprocess
from pathlib import Path

from src.core.app_config import FLATPAK_ENV_VAR, CONFIG_DIR_NAME

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

if os.environ.get(FLATPAK_ENV_VAR):
    BASE_DIR = Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local' / 'share')) / CONFIG_DIR_NAME
elif hasattr(sys, '_MEIPASS'):
    BASE_DIR = Path(sys.executable).parent.resolve()
else:
    BASE_DIR = Path(__file__).resolve().parent.parent
