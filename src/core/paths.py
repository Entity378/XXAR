# Bundle/temp path helpers.

import os
import sys
from pathlib import Path

from src.core.app_config import CONFIG_DIR_NAME
from src.core.subprocess_utils import IS_FLATPAK, is_frozen

# __file__ is src/core/paths.py, so three parents up is the project root.
# This branch is only reached in source mode; frozen builds set sys._MEIPASS.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def get_base_path():
    if hasattr(sys, '_MEIPASS'):
        return Path(sys._MEIPASS)
    return _PROJECT_ROOT


def get_temp_dir():
    if IS_FLATPAK:
        base = Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local' / 'share')) / CONFIG_DIR_NAME
    elif is_frozen():
        localappdata = Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData' / 'Local'))
        base = localappdata / CONFIG_DIR_NAME
    else:
        base = _PROJECT_ROOT
    temp = base / 'temp'
    temp.mkdir(parents=True, exist_ok=True)
    return temp
