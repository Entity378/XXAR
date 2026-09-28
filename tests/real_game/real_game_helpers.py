import os
import shutil
import struct
from functools import lru_cache
from pathlib import Path

import pytest

from src.core.game_registry import get_game
from src.wwise.bnk_handler import BNKFile
from src.wwise.hirc_music import _collect_bnk_music_index
from src.wwise.pck_indexer import PCKIndexer

FULL_RUN = os.environ.get("XXAR_REAL_GAME_FULL") == "1"
GAME_IDS = ("zzz", "genshin", "hsr")
SECTIONS = ("banks", "sounds", "externals")
STANDARD_BNK_CHUNKS = frozenset({b"BKHD", b"DIDX", b"DATA", b"HIRC"})


def installed_game(real_game_audio_dirs, game_id):
    if game_id not in real_game_audio_dirs:
        pytest.skip(f"{game_id} is not installed or not configured in the real XXAR settings")
    return real_game_audio_dirs[game_id]


def audio_pcks(root):
    if not root or not root.is_dir():
        return []
    return sorted(root.rglob("*.pck"))


def by_size(pcks):
    return sorted(pcks, key=lambda pck: (pck.stat().st_size, str(pck)))


@lru_cache(maxsize=None)
def game_pck_index(pck_path):
    return PCKIndexer(pck_path).build_index()


def smallest_pck(pcks, predicate, description):
    for pck in by_size(pcks):
        if predicate(pck):
            return pck
    pytest.skip(f"no pck {description}")


def has_entries(section):
    return lambda pck: bool(game_pck_index(pck)[section])


def read_entries(pck_path):
    index = PCKIndexer(pck_path).build_index()
    entries = {}
    with open(pck_path, "rb") as pck_file:
        for section in SECTIONS:
            for entry in index[section]:
                pck_file.seek(entry["offset"])
                entries[(section, entry["id"], entry["lang_id"])] = pck_file.read(entry["size"])
    return entries


def iter_banks(pck_path):
    index = game_pck_index(pck_path)
    with open(pck_path, "rb") as pck_file:
        for bank in index["banks"]:
            pck_file.seek(bank["offset"])
            yield bank, pck_file.read(bank["size"])


def chunk_layout(bnk_bytes):
    chunks = []
    position = 0
    while position + 8 <= len(bnk_bytes):
        size = struct.unpack_from("<I", bnk_bytes, position + 4)[0]
        chunks.append((bytes(bnk_bytes[position : position + 4]), position + 8, size))
        position += 8 + size
    return chunks, position


def chunk_tags(bnk_bytes):
    return [tag for tag, _, _ in chunk_layout(bnk_bytes)[0]]


def has_only_standard_chunks(bnk_bytes):
    return set(chunk_tags(bnk_bytes)) <= STANDARD_BNK_CHUNKS


def music_source_ids(pck_path):
    source_ids = set()
    for _, bnk_bytes in iter_banks(pck_path):
        source_ids |= _collect_bnk_music_index(bnk_bytes)[1]
    return source_ids


def replaceable_bank(pck_path):
    # A bank the apply pipeline would rebuild: embedded WEMs, only chunks BNKFile keeps, no music tracks.
    for bank, bnk_bytes in iter_banks(pck_path):
        if b"DATA" not in chunk_tags(bnk_bytes) or not has_only_standard_chunks(bnk_bytes):
            continue
        if _collect_bnk_music_index(bnk_bytes)[0]:
            continue
        if len(BNKFile(bnk_bytes=bnk_bytes).list_wems()) >= 2:
            return bank, bnk_bytes
    return None


def bank_pck_sample(game_dirs):
    # Default: the smallest bank pck of every StreamingAssets folder, the smallest SoundBank pck and the smallest Persistent one.
    game = get_game(game_dirs.game_id)
    streaming_pcks = [pck for pck in audio_pcks(game_dirs.streaming_root) if game_pck_index(pck)["banks"]]
    persistent_pcks = [pck for pck in audio_pcks(game_dirs.persistent_root) if game_pck_index(pck)["banks"]]
    if FULL_RUN:
        return streaming_pcks + persistent_pcks
    sample = {}
    for pck in by_size(streaming_pcks):
        sample.setdefault(pck.parent, pck)
    chosen = set(sample.values())
    chosen.update(by_size(pck for pck in streaming_pcks if pck.match(game.soundbank_pck_glob))[:1])
    chosen.update(by_size(persistent_pcks)[:1])
    return sorted(chosen)


def copy_into(pck_path, target_dir):
    target = Path(target_dir) / pck_path.name
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(pck_path, target)
    return target


def label(pck_path, game_dirs):
    for root_name, root in (("streaming", game_dirs.streaming_root), ("persistent", game_dirs.persistent_root)):
        if root and pck_path.is_relative_to(root):
            return f"{game_dirs.game_id} {root_name}:{pck_path.relative_to(root).as_posix()}"
    return str(pck_path)
