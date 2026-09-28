import json
import struct
import threading
import zipfile
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

from helpers import build_bnk, build_pck, hirc_object, make_game_install, make_wem, wait_until

SFX_BANK_ID = 100
EMBEDDED_WEM_IDS = (11, 12)
STREAMED_WEM_ID = 21
SOUNDBANK_PCK = "Full/SoundBank_SFX_1.pck"
STREAMED_PCK = "Full/Streamed_SFX_1.pck"


def zzz_streaming_files():
    sfx_bank = build_bnk(SFX_BANK_ID, {wem_id: make_wem(wem_id) for wem_id in EMBEDDED_WEM_IDS})
    return {
        SOUNDBANK_PCK: build_pck(banks=[(SFX_BANK_ID, 0, sfx_bank)]),
        STREAMED_PCK: build_pck(sounds=[(STREAMED_WEM_ID, 0, make_wem(STREAMED_WEM_ID, 256))]),
    }


def make_zzz_install(root, persistent_files=None, extra_streaming_files=None):
    streaming_files = zzz_streaming_files()
    streaming_files.update(extra_streaming_files or {})
    return make_game_install(root, "zzz", streaming_files, persistent_files)


def music_track(track_id, source_id):
    source = struct.pack("<IBIIB", 0x00040001, 2, source_id, 0, 0)
    return hirc_object(0x0B, track_id, struct.pack("<BI", 0, 1) + source + struct.pack("<I", 0))


def make_genshin_install(root):
    music_bank = build_bnk(300, {31: make_wem(31)}, hirc_objects=[music_track(9300, 31)])
    streaming_files = {
        "Banks0.pck": build_pck(banks=[(300, 0, music_bank)]),
        "Streamed0.pck": build_pck(sounds=[(32, 0, make_wem(32, 128))]),
        "English(US)/Banks_VO0.pck": build_pck(banks=[(301, 0, build_bnk(301, {33: make_wem(33)}))]),
    }
    return make_game_install(root, "genshin", streaming_files)


def make_hsr_install(root):
    streaming_files = {
        "Banks0.pck": build_pck(banks=[(400, 0, build_bnk(400, {41: make_wem(41)}))]),
        "Streamed0.pck": build_pck(sounds=[(42, 0, make_wem(42, 128))]),
    }
    return make_game_install(root, "hsr", streaming_files)


def write_mod_package(path, name, replacements, version="1.0.0", author="Tester"):
    # Replacements are {pck_name: {wem_id: wem_bytes}}, packed as direct (non-bnk) entries.
    metadata = {
        "format_version": "3.0",
        "name": name,
        "author": author,
        "version": version,
        "description": f"{name} description",
        "replacements": {},
    }
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        for pck_name, wems in replacements.items():
            entries = metadata["replacements"].setdefault(pck_name, {}).setdefault("direct", {})
            for wem_id, wem_bytes in wems.items():
                wem_file = f"wem_files/direct/{wem_id}.wem"
                archive.writestr(wem_file, wem_bytes)
                entries[str(wem_id)] = {"wem_file": wem_file, "sound_name": "", "lang_id": 0, "file_type": "wem"}
        archive.writestr("metadata.json", json.dumps(metadata))
    return path


def read_pck_wem(pck_path, wem_id, file_type="wem", lang_id=0):
    from src.wwise.pck_indexer import PCKIndexer

    indexer = PCKIndexer(str(pck_path))
    indexer.build_index()
    return indexer.extract_single_file(wem_id, file_type, lang_id)


def game_lock_free():
    from src.gui.backend.base_worker import game_lock_holder, game_write_state

    return game_lock_holder(skip_current_thread=False) is None and not game_write_state().busy


@contextmanager
def holding_game_lock():
    # Another registry holds the game lock, the way a write started elsewhere in the app would.
    from src.gui.backend.base_worker import FunctionWorker, WorkerRegistry, game_write_state

    release = threading.Event()
    registry = WorkerRegistry("test_game_lock")
    assert registry.start("test_writer", FunctionWorker(lambda: release.wait(30)), holds_game_lock=True)
    assert game_write_state().busy
    try:
        yield registry
    finally:
        release.set()
        assert wait_until(lambda: not registry.is_running("test_writer") and game_lock_free())


def sandbox_app_environment(monkeypatch):
    # Every native dialog a slot could open answers from dialog_answers instead of showing a window.
    import src.core.paths as paths
    from src.gui.utils.native_dialogs import NativeDialogs

    answers = {"open_file": "", "open_files": [], "save_file": "", "directory": ""}
    monkeypatch.setattr(NativeDialogs, "get_open_file", staticmethod(lambda *args, **kwargs: answers["open_file"]))
    monkeypatch.setattr(NativeDialogs, "get_open_files", staticmethod(lambda *args, **kwargs: answers["open_files"]))
    monkeypatch.setattr(NativeDialogs, "get_save_file", staticmethod(lambda *args, **kwargs: answers["save_file"]))
    monkeypatch.setattr(NativeDialogs, "get_directory", staticmethod(lambda *args, **kwargs: answers["directory"]))
    return SimpleNamespace(temp_dir=paths.get_temp_dir(), dialog_answers=answers)
