import os

_LOCK_WINERRORS = (32, 33)


def exists_or_raise(path):
    # Path.exists swallows every OSError, so a permission failure would read as a missing file.
    try:
        os.stat(path)
    except (FileNotFoundError, NotADirectoryError):
        return False
    return True


def _error_chain(error):
    seen = set()
    while error is not None and id(error) not in seen:
        yield error
        seen.add(id(error))
        error = error.__cause__ or error.__context__


def is_file_locked_error(error):
    # WinError 32/33 mean another process holds the file, which admin rights do not fix.
    return any(getattr(link, "winerror", None) in _LOCK_WINERRORS for link in _error_chain(error))


def is_permission_error(error):
    # The cause chain is walked because apply_mods wraps the original error.
    return any(isinstance(link, PermissionError) for link in _error_chain(error))
