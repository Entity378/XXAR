# XXAR - Cross-game Audio Replacer
# Copyright (C) 2026  Entity378
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

import os
import sys
from pathlib import Path

from src.core.subprocess_utils import IS_FLATPAK, IS_LINUX, IS_WINDOWS, is_frozen

if IS_LINUX and 'QT_QPA_PLATFORM' not in os.environ:
    os.environ['QT_QPA_PLATFORM'] = 'wayland;xcb'

if IS_WINDOWS:
    os.environ.setdefault('QT_SCALE_FACTOR_ROUNDING_POLICY', 'PassThrough')

# Force the Basic Qt Quick Controls style so our custom background/contentItem overrides work — the native style refuses customization.
os.environ.setdefault('QT_QUICK_CONTROLS_STYLE', 'Basic')


def _load_ui_scale():
    import json
    from pathlib import Path
    try:
        if IS_WINDOWS:
            appdata = Path(os.environ.get('APPDATA', Path.home() / 'AppData' / 'Roaming'))
            settings_file = appdata / 'XXAR' / 'settings.json'
        else:
            xdg_config = os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')
            settings_file = Path(xdg_config) / 'XXAR' / 'settings.json'
        if settings_file.exists():
            with open(settings_file, 'r') as f:
                scale = json.load(f).get('ui_scale', 1.0)
            if scale != 1.0:
                orig_scale = os.environ.get('QT_SCALE_FACTOR', False)
                if orig_scale:
                    os.environ['QT_SCALE_FACTOR_ORIG'] = orig_scale
                os.environ['QT_SCALE_FACTOR'] = str(scale)
    except Exception:
        pass


_load_ui_scale()


def _redirect_qml_disk_cache():
    # Put Qt's QML bytecode cache under cache/qml. Qt's QStandardPaths::CacheLocation already
    # resolves to data_dir/cache (the qtpipelinecache lives there), so this keeps one cache/ root.
    from src.core.app_config import CONFIG_DIR_NAME
    if IS_FLATPAK:
        base = Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local' / 'share')) / CONFIG_DIR_NAME
    elif IS_WINDOWS:
        base = Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData' / 'Local')) / CONFIG_DIR_NAME
    else:
        base = Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local' / 'share')) / CONFIG_DIR_NAME
    os.environ.setdefault('QML_DISK_CACHE_PATH', str(base / 'cache' / 'qml'))


_redirect_qml_disk_cache()

os.environ['QT_LOGGING_RULES'] = '*.debug=false;qt.gui.icc=false;qt.text.font.db=false;qt.network.ssl=false'

from src.core.app_config import APP_VERSION

__version__ = APP_VERSION

from src.core.paths import get_base_path, get_temp_dir

base_dir = get_base_path()

src_path = base_dir / 'src'
sys.path.insert(0, str(src_path))

try:
    # Must run before anything in src/ caches a ConfigManager path.
    from src.core.migration import run_migrations
    run_migrations()

    from src.core.logger import setup_logging
    setup_logging()

    from src.gui.main_qml import Application
except ModuleNotFoundError as e:
    print(f"Error: Could not find modules in {src_path}")
    print(f"Current sys.path: {sys.path}")
    raise e


def main():
    app = Application(version=__version__)
    sys.exit(app.run())


if __name__ == '__main__':
    main()
