import json
from pathlib import Path
from src.core.config_manager import get_settings_file

from src.core.logger import get_logger
logger = get_logger(__name__)

_SETTINGS_KEY = "last_dirs"


def _load_settings():
    settings_file = get_settings_file()
    if not settings_file.exists():
        return {}, settings_file
    try:
        with open(settings_file, "r") as f:
            return json.load(f) or {}, settings_file
    except Exception:
        return {}, settings_file


def _save_settings(settings, settings_file):
    try:
        settings_file.parent.mkdir(parents=True, exist_ok=True)
        with open(settings_file, "w") as f:
            json.dump(settings, f, indent=2)
    except Exception as e:
        logger.error(f"[PathMemory] Warning: Failed to write settings: {e}")


def get_last_dir(key, fallback=None):
    if not key:
        return fallback or str(Path.home())
    settings, _ = _load_settings()
    last_dirs = settings.get(_SETTINGS_KEY, {})
    last = last_dirs.get(key, "")
    if last and Path(last).is_dir():
        return last
    return fallback or str(Path.home())


def save_last_dir(key, path):
    if not key or not path:
        return
    try:
        p = Path(path)
        directory = str(p if p.is_dir() else p.parent)
    except Exception:
        return
    settings, settings_file = _load_settings()
    last_dirs = settings.get(_SETTINGS_KEY, {})
    if not isinstance(last_dirs, dict):
        last_dirs = {}
    last_dirs[key] = directory
    settings[_SETTINGS_KEY] = last_dirs
    _save_settings(settings, settings_file)
