import pytest

from real_game.real_game_helpers import (
    GAME_IDS,
    SECTIONS,
    audio_pcks,
    chunk_layout,
    copy_into,
    game_pck_index,
    has_entries,
    installed_game,
    read_entries,
    replaceable_bank,
    smallest_pck,
)
from src.core.game_registry import get_game
from src.wwise.bnk_handler import BNKFile
from src.wwise.pck_indexer import PCKIndexer
from src.wwise.pck_packer import PCKPacker

pytestmark = pytest.mark.real_game


def rebuild(original_pck, output_pck, prepare=lambda packer: None):
    packer = PCKPacker(original_pck, output_pck)
    try:
        packer.load_original_pck()
        prepare(packer)
        packer.pack(use_patching=False)
    finally:
        packer.close()
    return output_pck


def unprotected_streaming_pcks(game_dirs):
    game = get_game(game_dirs.game_id)
    return [pck for pck in audio_pcks(game_dirs.streaming_root) if not game.is_protected_pck(pck.name)]


def loose_wem_keys(entries):
    return [key for key in entries if key[0] != "banks"]


def data_payload_start(bnk_bytes):
    return next(payload_start for tag, payload_start, _ in chunk_layout(bnk_bytes)[0] if tag == b"DATA")


def wem_starts_are_16_aligned(bnk_bytes):
    bnk = BNKFile(bnk_bytes=bnk_bytes)
    start = data_payload_start(bnk_bytes)
    return all((start + offset) % 16 == 0 for offset in bnk.data["DIDX"].wem_offsets.values())


@pytest.mark.parametrize("section", SECTIONS)
@pytest.mark.parametrize("game_id", GAME_IDS)
def test_real_rebuild_keeps_every_entry_byte_identical(real_game_audio_dirs, game_id, section, tmp_path):
    game_dirs = installed_game(real_game_audio_dirs, game_id)
    source = smallest_pck(unprotected_streaming_pcks(game_dirs), has_entries(section), f"with {section} in {game_id}")
    original = copy_into(source, tmp_path / "original")

    rebuilt = rebuild(original, tmp_path / "rebuilt.pck")

    original_entries = read_entries(original)
    assert read_entries(rebuilt) == original_entries
    used_lang_ids = {lang_id for _, _, lang_id in original_entries}
    original_indexer, rebuilt_indexer = PCKIndexer(original), PCKIndexer(rebuilt)
    original_indexer.build_index()
    rebuilt_indexer.build_index()
    assert {lang_id: rebuilt_indexer.lang_map[lang_id] for lang_id in used_lang_ids} == {lang_id: original_indexer.lang_map[lang_id] for lang_id in used_lang_ids}


@pytest.mark.parametrize("game_id", GAME_IDS)
def test_real_replacing_a_loose_wem_changes_only_that_entry(real_game_audio_dirs, game_id, tmp_path):
    game_dirs = installed_game(real_game_audio_dirs, game_id)
    source = smallest_pck(
        unprotected_streaming_pcks(game_dirs),
        lambda pck: len(game_pck_index(pck)["sounds"]) + len(game_pck_index(pck)["externals"]) >= 2,
        f"with two loose WEMs in {game_id}",
    )
    original = copy_into(source, tmp_path / "original")
    original_entries = read_entries(original)
    target_key, *other_loose_keys = loose_wem_keys(original_entries)
    donor_key = max(other_loose_keys, key=lambda key: abs(len(original_entries[key]) - len(original_entries[target_key])))
    replacement = tmp_path / "replacement.wem"
    replacement.write_bytes(original_entries[donor_key])
    _, file_id, lang_id = target_key

    rebuilt = rebuild(original, tmp_path / "rebuilt.pck", lambda packer: packer.replace_file(file_id, replacement, lang_id=lang_id))

    rebuilt_entries = read_entries(rebuilt)
    assert rebuilt_entries.keys() == original_entries.keys()
    assert rebuilt_entries[target_key] == original_entries[donor_key] != original_entries[target_key]
    assert all(rebuilt_entries[key] == original_entries[key] for key in original_entries if key != target_key)


@pytest.mark.parametrize("game_id", GAME_IDS)
def test_real_merging_a_wem_into_a_bank_changes_only_that_wem(real_game_audio_dirs, game_id, tmp_path):
    game_dirs = installed_game(real_game_audio_dirs, game_id)
    source = smallest_pck(unprotected_streaming_pcks(game_dirs), lambda pck: replaceable_bank(pck) is not None, f"with a replaceable bank in {game_id}")
    bank, bnk_bytes = replaceable_bank(source)
    original_bnk = BNKFile(bnk_bytes=bnk_bytes)
    target_wem_id, *other_wem_ids = original_bnk.list_wems()
    target_size = len(original_bnk.extract_wem(target_wem_id))
    donor_wem_id = max(other_wem_ids, key=lambda wem_id: abs(len(original_bnk.extract_wem(wem_id)) - target_size))
    replacement_bytes = original_bnk.extract_wem(donor_wem_id)
    original = copy_into(source, tmp_path / "original")

    rebuilt = rebuild(
        original, tmp_path / "rebuilt.pck",
        lambda packer: packer.merge_bnk_wems(bank["id"], {target_wem_id: replacement_bytes}, lang_id=bank["lang_id"]),
    )

    original_entries, rebuilt_entries = read_entries(original), read_entries(rebuilt)
    bank_key = ("banks", bank["id"], bank["lang_id"])
    assert rebuilt_entries.keys() == original_entries.keys()
    assert all(rebuilt_entries[key] == original_entries[key] for key in original_entries if key != bank_key)
    merged_bytes = rebuilt_entries[bank_key]
    merged_bnk = BNKFile(bnk_bytes=merged_bytes)
    assert merged_bnk.list_wems() == original_bnk.list_wems()
    assert merged_bnk.extract_wem(target_wem_id) == replacement_bytes
    assert all(merged_bnk.extract_wem(wem_id) == original_bnk.extract_wem(wem_id) for wem_id in other_wem_ids)
    for chunk_name in ("BKHD", "HIRC"):
        if chunk_name in original_bnk.data:
            assert merged_bnk.data[chunk_name].getdata() == original_bnk.data[chunk_name].getdata()
    assert merged_bnk.get_bytes() == merged_bytes
    assert wem_starts_are_16_aligned(bnk_bytes)
    assert wem_starts_are_16_aligned(merged_bytes)
