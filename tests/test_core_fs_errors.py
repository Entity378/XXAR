import os

import pytest

from src.core import fs_errors
from src.core.fs_errors import exists_or_raise, is_file_locked_error, is_permission_error


def locked_file_error(winerror):
    error = OSError("The process cannot access the file")
    error.winerror = winerror
    return error


def chained_error(inner_error, use_cause):
    try:
        try:
            raise inner_error
        except Exception as original:
            if use_cause:
                raise RuntimeError("apply_mods failed") from original
            raise RuntimeError("apply_mods failed")
    except RuntimeError as wrapped:
        return wrapped


def test_exists_or_raise_reports_existing_and_missing_paths(tmp_path):
    existing_file = tmp_path / "file.pck"
    existing_file.write_bytes(b"x")
    assert exists_or_raise(existing_file)
    assert exists_or_raise(tmp_path)
    assert not exists_or_raise(tmp_path / "missing.pck")
    assert not exists_or_raise(existing_file / "child.pck")


def test_exists_or_raise_propagates_permission_errors(monkeypatch, tmp_path):
    def denied_stat(path):
        raise PermissionError(13, "Access is denied", str(path))

    monkeypatch.setattr(fs_errors.os, "stat", denied_stat)
    with pytest.raises(PermissionError):
        exists_or_raise(tmp_path / "Patch.pck")


@pytest.mark.parametrize("winerror", [32, 33])
def test_sharing_and_lock_violations_are_file_locked_errors(winerror):
    assert is_file_locked_error(locked_file_error(winerror))


@pytest.mark.parametrize("use_cause", [True, False])
def test_file_locked_error_is_found_through_the_exception_chain(use_cause):
    assert is_file_locked_error(chained_error(locked_file_error(32), use_cause))


@pytest.mark.parametrize("error", [PermissionError(13, "denied"), locked_file_error(5), ValueError("x"), None])
def test_other_errors_are_not_file_locked_errors(error):
    assert not is_file_locked_error(error)


def test_cyclic_exception_chain_terminates():
    first_error = RuntimeError("first")
    second_error = RuntimeError("second")
    first_error.__cause__ = second_error
    second_error.__cause__ = first_error
    assert not is_file_locked_error(first_error)
    assert not is_permission_error(first_error)


@pytest.mark.parametrize("use_cause", [True, False])
def test_permission_error_is_found_through_the_exception_chain(use_cause):
    assert is_permission_error(PermissionError(13, "denied"))
    assert is_permission_error(chained_error(PermissionError(13, "denied"), use_cause))


def test_other_errors_are_not_permission_errors():
    assert not is_permission_error(OSError("disk full"))
    assert not is_permission_error(chained_error(FileNotFoundError("gone"), use_cause=True))


def test_real_missing_file_is_not_a_permission_error(tmp_path):
    with pytest.raises(OSError) as raised:
        os.stat(tmp_path / "missing")
    assert not is_permission_error(raised.value)
    assert not is_file_locked_error(raised.value)
