import logging
import sys
from logging.handlers import RotatingFileHandler

import pytest

from src.core import logger as logger_module
from src.core.logger import get_logger, setup_logging


@pytest.fixture
def fresh_xxar_logger(monkeypatch):
    xxar_root = logging.getLogger("xxar")
    saved_handlers = list(xxar_root.handlers)
    saved_level = xxar_root.level
    saved_propagate = xxar_root.propagate
    xxar_root.handlers = []
    monkeypatch.setattr(logger_module, "_CONFIGURED", False)
    monkeypatch.delenv("XXAR_LOG_LEVEL", raising=False)
    yield xxar_root
    for handler in xxar_root.handlers:
        handler.close()
    xxar_root.handlers = saved_handlers
    xxar_root.setLevel(saved_level)
    xxar_root.propagate = saved_propagate


def handlers_of_type(xxar_root, handler_type):
    return [handler for handler in xxar_root.handlers if type(handler) is handler_type]


def test_setup_logging_attaches_rotating_file_and_stdout(fresh_xxar_logger, isolated_user_dirs):
    setup_logging()
    [file_handler] = handlers_of_type(fresh_xxar_logger, RotatingFileHandler)
    [stream_handler] = handlers_of_type(fresh_xxar_logger, logging.StreamHandler)
    assert file_handler.baseFilename == str(isolated_user_dirs.data_dir / "logs" / "xxar.log")
    assert file_handler.maxBytes == 5 * 1024 * 1024
    assert file_handler.backupCount == 5
    assert stream_handler.stream is sys.stdout
    assert fresh_xxar_logger.level == logging.INFO
    assert fresh_xxar_logger.propagate is False


def test_messages_reach_the_log_file(fresh_xxar_logger, isolated_user_dirs):
    setup_logging()
    get_logger("src.tests.probe").warning("probe message %d", 42)
    for handler in fresh_xxar_logger.handlers:
        handler.flush()
    log_text = (isolated_user_dirs.data_dir / "logs" / "xxar.log").read_text(encoding="utf-8")
    assert "[WARNING] xxar.src.tests.probe: probe message 42" in log_text


@pytest.mark.parametrize("env_level, expected_level", [("DEBUG", logging.DEBUG), ("error", logging.ERROR), ("NONSENSE", logging.INFO)])
def test_log_level_comes_from_the_environment(fresh_xxar_logger, monkeypatch, env_level, expected_level):
    monkeypatch.setenv("XXAR_LOG_LEVEL", env_level)
    setup_logging()
    assert fresh_xxar_logger.level == expected_level


def test_explicit_level_wins_over_the_environment(fresh_xxar_logger, monkeypatch):
    monkeypatch.setenv("XXAR_LOG_LEVEL", "DEBUG")
    setup_logging("WARNING")
    assert fresh_xxar_logger.level == logging.WARNING


def test_setup_logging_runs_only_once(fresh_xxar_logger):
    setup_logging()
    handler_count = len(fresh_xxar_logger.handlers)
    setup_logging("DEBUG")
    assert len(fresh_xxar_logger.handlers) == handler_count
    assert fresh_xxar_logger.level == logging.INFO


def test_unwritable_log_dir_falls_back_to_stdout_only(fresh_xxar_logger, monkeypatch, capsys):
    def unwritable_log_dir():
        raise PermissionError("log dir is read-only")

    monkeypatch.setattr(logger_module, "_resolve_log_dir", unwritable_log_dir)
    setup_logging()
    assert handlers_of_type(fresh_xxar_logger, RotatingFileHandler) == []
    assert len(handlers_of_type(fresh_xxar_logger, logging.StreamHandler)) == 1
    assert "file handler setup failed: log dir is read-only" in capsys.readouterr().err


def test_get_logger_configures_logging_lazily(fresh_xxar_logger):
    child_logger = get_logger("src.core.something")
    assert logger_module._CONFIGURED
    assert child_logger.name == "xxar.src.core.something"
    assert fresh_xxar_logger.handlers


@pytest.mark.parametrize("module_name", ["__main__", ""])
def test_get_logger_for_main_returns_the_root_xxar_logger(fresh_xxar_logger, module_name):
    assert get_logger(module_name) is fresh_xxar_logger
