import json
import random
import struct
import time
from pathlib import Path
from types import SimpleNamespace

from src.core.config_manager import get_settings_file
from src.core.game_registry import build_audio_paths, get_audio_settings_keys, get_game


def make_wem(seed, payload_size=64):
    rng = random.Random(seed)
    payload = bytes(rng.getrandbits(8) for _ in range(payload_size))
    return b"RIFF" + struct.pack("<I", 4 + len(payload)) + b"WAVE" + payload


def align16_padding(size):
    return (16 - size % 16) % 16


def hirc_object(obj_type, obj_id, body=b""):
    return struct.pack("<BII", obj_type, 4 + len(body), obj_id) + body


def build_bnk(bank_id, wems=None, hirc_objects=None, version=0x91, language_id=0):
    # Chunk order and 16-byte DATA alignment follow what Wwise writes.
    wems = wems or {}
    bkhd_body = struct.pack("<IIIII", version, bank_id, language_id, 0, 0)
    didx_size = 12 * len(wems)
    if wems:
        data_payload_start = 8 + len(bkhd_body) + 8 + didx_size + 8
        bkhd_body += b"\x00" * align16_padding(data_payload_start)

    out = b"BKHD" + struct.pack("<I", len(bkhd_body)) + bkhd_body
    if wems:
        didx_body = b""
        data_body = b""
        wem_items = list(wems.items())
        for index, (wem_id, wem_bytes) in enumerate(wem_items):
            didx_body += struct.pack("<III", wem_id, len(data_body), len(wem_bytes))
            data_body += wem_bytes
            if index != len(wem_items) - 1:
                data_body += b"\x00" * align16_padding(len(data_body))
        out += b"DIDX" + struct.pack("<I", len(didx_body)) + didx_body
        out += b"DATA" + struct.pack("<I", len(data_body)) + data_body
    if hirc_objects is not None:
        hirc_body = struct.pack("<I", len(hirc_objects)) + b"".join(hirc_objects)
        out += b"HIRC" + struct.pack("<I", len(hirc_body)) + hirc_body
    return out


def _language_map(languages):
    lang_ids = sorted(languages)
    header = struct.pack("<I", len(lang_ids))
    strings = b""
    string_offset = 4 + 8 * len(lang_ids)
    for lang_id in lang_ids:
        encoded = languages[lang_id].encode("utf-16-le") + b"\x00\x00"
        header += struct.pack("<II", string_offset + len(strings), lang_id)
        strings += encoded
    lang_map = header + strings
    return lang_map + b"\x00" * ((4 - len(lang_map) % 4) % 4)


def build_pck(banks=(), sounds=(), externals=(), languages=None, block_size=1, with_externals_section=True):
    # Each entry is (file_id, lang_id, bytes); externals use 64-bit ids.
    languages = languages or {0: "sfx"}
    lang_map = _language_map(languages)
    banks = sorted(banks, key=lambda entry: (entry[0], entry[1]))
    sounds = sorted(sounds, key=lambda entry: (entry[0], entry[1]))
    externals = sorted(externals, key=lambda entry: (entry[0], entry[1]))
    banks_size = 4 + 20 * len(banks)
    sounds_size = 4 + 20 * len(sounds)
    externals_size = 4 + 24 * len(externals) if with_externals_section else 0
    size_fields = 16 if with_externals_section else 12
    header_size = 4 + size_fields + len(lang_map) + banks_size + sounds_size + externals_size

    data_offset = 8 + header_size
    placed = []
    payload = b""
    for table in (banks, sounds, externals):
        rows = []
        for file_id, lang_id, file_bytes in table:
            padding = (block_size - (data_offset + len(payload)) % block_size) % block_size
            payload += b"\x00" * padding
            absolute_offset = data_offset + len(payload)
            rows.append((file_id, lang_id, len(file_bytes), absolute_offset // block_size))
            payload += file_bytes
        placed.append(rows)

    out = b"AKPK" + struct.pack("<II", header_size, 1)
    out += struct.pack("<III", len(lang_map), banks_size, sounds_size)
    if with_externals_section:
        out += struct.pack("<I", externals_size)
    out += lang_map
    for table_index, rows in enumerate(placed):
        if table_index == 2 and not with_externals_section:
            continue
        out += struct.pack("<I", len(rows))
        for file_id, lang_id, size, start_block in rows:
            id_format = "<Q" if table_index == 2 else "<I"
            out += struct.pack(id_format, file_id) + struct.pack("<IIII", block_size, size, start_block, lang_id)
    assert len(out) == data_offset
    return out + payload


def write_files(root, files):
    root = Path(root)
    for rel_path, content in (files or {}).items():
        target = root / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)


def make_game_install(root, game_id, streaming_files=None, persistent_files=None):
    game = get_game(game_id)
    data_dir = Path(root) / game.install_dir_name / game.data_dir_name
    streaming_root, persistent_root = build_audio_paths(game.id, data_dir)
    streaming_root.mkdir(parents=True, exist_ok=True)
    persistent_root.mkdir(parents=True, exist_ok=True)
    write_files(streaming_root, streaming_files)
    write_files(persistent_root, persistent_files)
    return SimpleNamespace(
        game=game,
        game_root=data_dir.parent,
        data_dir=data_dir,
        streaming_root=streaming_root,
        persistent_root=persistent_root,
    )


def read_settings():
    settings_file = get_settings_file()
    if not settings_file.exists():
        return {}
    return json.loads(settings_file.read_text(encoding="utf-8"))


def write_settings(settings):
    settings_file = get_settings_file()
    settings_file.parent.mkdir(parents=True, exist_ok=True)
    settings_file.write_text(json.dumps(settings, indent=2), encoding="utf-8")


def configure_game_in_settings(install, select=True, **extra_settings):
    settings = read_settings()
    streaming_key, persistent_key = get_audio_settings_keys(install.game.id)
    settings[streaming_key] = str(install.streaming_root)
    settings[persistent_key] = str(install.persistent_root)
    if select:
        settings["selected_game"] = install.game.id
        settings["game_audio_dir"] = str(install.streaming_root)
        settings["persistent_audio_dir"] = str(install.persistent_root)
    settings.update(extra_settings)
    write_settings(settings)
    return settings


def wait_until(predicate, timeout=10.0):
    from PyQt6.QtCore import QCoreApplication

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        QCoreApplication.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    QCoreApplication.processEvents()
    return predicate()


def record_signal(signal):
    emissions = []
    signal.connect(lambda *args: emissions.append(args))
    return emissions
