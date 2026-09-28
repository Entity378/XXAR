import struct

import pytest

from real_game.real_game_helpers import (
    GAME_IDS,
    SECTIONS,
    audio_pcks,
    bank_pck_sample,
    chunk_layout,
    has_only_standard_chunks,
    installed_game,
    iter_banks,
    label,
)
from src.core.game_registry import get_game
from src.wwise.bnk_handler import BNKFile
from src.wwise.bnk_indexer import BNKIndexer, count_didx_wems
from src.wwise.pck_indexer import PCKIndexer

pytestmark = pytest.mark.real_game


def pck_layout_problems(pck_path, game):
    index = PCKIndexer(pck_path).build_index()
    with open(pck_path, "rb") as pck_file:
        header = pck_file.read(8)
    data_start = 8 + struct.unpack_from("<I", header, 4)[0]
    file_size = pck_path.stat().st_size
    entries = [(section, entry) for section in SECTIONS for entry in index[section]]
    keys = [(section, entry["id"], entry["lang_id"]) for section, entry in entries]
    problems = []
    if not entries and not game.is_protected_pck(pck_path.name):
        problems.append("no entries")
    if len(keys) != len(set(keys)):
        problems.append("duplicate (section, id, lang) rows")
    regions = sorted((entry["offset"], entry["offset"] + entry["size"]) for _, entry in entries)
    for start, end in regions:
        if end <= start or start < data_start or end > file_size:
            problems.append(f"entry [{start}, {end}) outside the data area [{data_start}, {file_size})")
    for (_, previous_end), (next_start, _) in zip(regions, regions[1:]):
        if next_start < previous_end:
            problems.append(f"entries overlap at {next_start}")
    return problems


@pytest.mark.parametrize("game_id", GAME_IDS)
def test_real_every_pck_indexes_inside_its_own_data_area(real_game_audio_dirs, game_id):
    game_dirs = installed_game(real_game_audio_dirs, game_id)
    game = get_game(game_id)
    pcks = audio_pcks(game_dirs.streaming_root) + audio_pcks(game_dirs.persistent_root)
    problems = []
    for pck in pcks:
        try:
            problems += [f"{label(pck, game_dirs)}: {problem}" for problem in pck_layout_problems(pck, game)]
        except Exception as error:
            problems.append(f"{label(pck, game_dirs)}: {error!r}")
    assert pcks
    assert not problems, "\n".join(problems[:20])


@pytest.mark.parametrize("game_id", GAME_IDS)
def test_real_embedded_bnks_parse_and_split_into_their_wems(real_game_audio_dirs, game_id):
    game_dirs = installed_game(real_game_audio_dirs, game_id)
    problems = []
    checked_banks = 0
    for pck in bank_pck_sample(game_dirs):
        with open(pck, "rb") as pck_file:
            for bank, bnk_bytes in iter_banks(pck):
                bank_label = f"{label(pck, game_dirs)} bank {bank['id']} lang {bank['lang_id']}"
                chunks, chunk_walk_end = chunk_layout(bnk_bytes)
                if bnk_bytes[:4] != b"BKHD" or chunk_walk_end != len(bnk_bytes):
                    problems.append(f"{bank_label}: chunk walk ends at {chunk_walk_end} of {len(bnk_bytes)}")
                    continue
                didx_count = sum(size // 12 for tag, _, size in chunks if tag == b"DIDX")
                bnk = BNKFile(bnk_bytes=bnk_bytes)
                indexer = BNKIndexer(bnk_bytes)
                indexer.parse_didx()
                counts = (len(bnk.list_wems()), indexer.get_wem_count(), count_didx_wems(pck_file, bank["offset"], bank["size"]))
                if counts != (didx_count,) * 3:
                    problems.append(f"{bank_label}: WEM counts {counts} != DIDX {didx_count}")
                for wem_id in bnk.list_wems():
                    wem_bytes = bnk.extract_wem(wem_id)
                    if wem_bytes != indexer.extract_wem(wem_id):
                        problems.append(f"{bank_label}: the two parsers extract different bytes for WEM {wem_id}")
                    if wem_bytes and wem_bytes[:4] != b"RIFF":
                        problems.append(f"{bank_label}: WEM {wem_id} is not a RIFF blob")
                if bnk.get_bytes() != bnk_bytes:
                    problems.append(f"{bank_label}: unmodified re-serialization differs")
                checked_banks += 1
    assert checked_banks
    assert not problems, "\n".join(problems[:20])


@pytest.mark.parametrize("game_id", GAME_IDS)
def test_real_bnks_with_other_chunks_survive_an_unmodified_round_trip(real_game_audio_dirs, game_id):
    game_dirs = installed_game(real_game_audio_dirs, game_id)
    banks_with_other_chunks = [
        (f"{label(pck, game_dirs)} bank {bank['id']}", bnk_bytes)
        for pck in bank_pck_sample(game_dirs)
        for bank, bnk_bytes in iter_banks(pck)
        if not has_only_standard_chunks(bnk_bytes)
    ]
    if not banks_with_other_chunks:
        pytest.skip("the sampled banks only carry BKHD/DIDX/DATA/HIRC")
    changed = [bank_label for bank_label, bnk_bytes in banks_with_other_chunks if BNKFile(bnk_bytes=bnk_bytes).get_bytes() != bnk_bytes]
    assert not changed, f"{len(changed)} of {len(banks_with_other_chunks)} banks changed, e.g. {changed[:3]}"
