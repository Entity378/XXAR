#File + stdout logging. Rotates at 5 MB × 5 files (~25 MB max on disk).

from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

_LOG_FORMAT = "%(asctime)s.%(msecs)03d [%(levelname)s] %(name)s: %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_CONFIGURED = False


def _resolve_log_dir() -> Path:
    # Lazy import: ConfigManager must not cache paths before run_migrations() finishes.
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
        # Fall back to stderr-only if the log dir is unwritable.
        sys.stderr.write(f"[xxar.logger] file handler setup failed: {e}\n")

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    root.addHandler(stream_handler)

    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    if not _CONFIGURED:
        setup_logging()
    if name == "__main__" or not name:
        return logging.getLogger("xxar")
    return logging.getLogger(f"xxar.{name}")
