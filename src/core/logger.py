"""Centralized file + stdout logging for XXAR.

`setup_logging()` is called once from `XXAR.py` right after `run_migrations()`.
All modules use `get_logger(__name__)` to obtain a logger that writes both to
the existing terminal/stdout (so launching from source still prints) and to
a rotating file at `get_data_dir() / "logs" / "xxar.log"`.

File rotation: 5 MB per file × 5 files = ~25 MB max on disk.
"""

from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_CONFIGURED = False


def _resolve_log_dir() -> Path:
    # Importing config_manager lazily so that migration.run_migrations() has
    # a chance to move things before ConfigManager caches any path.
    from src.core.config_manager import get_data_dir
    log_dir = get_data_dir() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def setup_logging(level: str | int | None = None) -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return

    if level is None:
        level = os.environ.get("XXAR_LOG_LEVEL", "INFO").upper()
    if isinstance(level, str):
        level = getattr(logging, level, logging.INFO)

    root = logging.getLogger("xxar")
    root.setLevel(level)
    root.propagate = False

    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

    try:
        log_file = _resolve_log_dir() / "xxar.log"
        file_handler = RotatingFileHandler(
            str(log_file), maxBytes=5 * 1024 * 1024, backupCount=5,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
    except Exception as e:
        # Fall back to stderr-only if the log dir can't be created (read-only
        # volume, corrupted perms); we still want stdout/stderr logging.
        sys.stderr.write(f"[xxar.logger] file handler setup failed: {e}\n")

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    root.addHandler(stream_handler)

    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    # Module-level callers pass __name__; map src.core.foo -> xxar.src.core.foo
    # so everything sits under the configured "xxar" root.
    if not _CONFIGURED:
        setup_logging()
    if name == "__main__" or not name:
        return logging.getLogger("xxar")
    return logging.getLogger(f"xxar.{name}")
