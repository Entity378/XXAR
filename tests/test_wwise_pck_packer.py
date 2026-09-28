import struct
from io import BytesIO

import pytest

from helpers import build_bnk, build_pck, hirc_object, make_wem, write_files
from src.wwise.bnk_handler import BNKFile
from src.wwise.pck_indexer import PCKIndexer
from src.wwise.pck_packer import PCKPacker

LANGUAGES = {0: "SFX", 1: "English(US)", 3: "Japanese"}
HIRC_BANK_ID = 1001
MEDIA_BANK_ID = 428903628
MISSING_BANK_ID = 424242
EXTERNAL_ID = 0x1_0000_0031
ENGLISH_BANK_WEMS = {11: make_wem(11, 40), 12: make_wem(12, 64), 13: make_wem(13, 7)}
JAPANESE_BANK_WEMS = {11: make_wem(21, 40), 12: make_wem(22, 64), 13: make_wem(23, 7)}


def original_tables():
    return {
        "banks": [
            (HIRC_BANK_ID, 0, build_bnk(HIRC_BANK_ID, hirc_objects=[hirc_object(0x02, 5, b"\x00" * 20)])),
            (MEDIA_BANK_ID, 1, build_bnk(MEDIA_BANK_ID, wems=ENGLISH_BANK_WEMS, language_id=1)),
            (MEDIA_BANK_ID, 3, build_bnk(MEDIA_BANK_ID, wems=JAPANESE_BANK_WEMS, language_id=3)),
        ],
        "sounds": [(21, 0, make_wem(31, 30)), (22, 1, make_wem(32, 45)), (22, 3, make_wem(33, 45))],
        "externals": [(EXTERNAL_ID, 1, make_wem(34, 19))],
    }


def expected_entries(tables):
    return {
        section: {(file_id, lang_id): file_bytes for file_id, lang_id, file_bytes in tables.get(section, [])}
        for section in ("banks", "sounds", "externals")
    }


def read_entries(pck_path):
    index = PCKIndexer(pck_path).build_index()
    pck_bytes = pck_path.read_bytes()
    return {
        section: {(entry["id"], entry["lang_id"]): pck_bytes[entry["offset"]:entry["offset"] + entry["size"]] for entry in index[section]}
        for section in ("banks", "sounds", "externals")
    }


def read_bank_wems(bnk_bytes):
    bank = BNKFile(bnk_bytes=bnk_bytes)
    return {wem_id: bank.extract_wem(wem_id) for wem_id in bank.list_wems()}


@pytest.fixture
def original_pck(tmp_path):
    pck_path = tmp_path / "SoundBank_SFX_1.pck"
    pck_path.write_bytes(build_pck(languages=LANGUAGES, block_size=16, **original_tables()))
    return pck_path


@pytest.fixture
def make_packer():
    packers = []

    def load_packer(original_pck_path, output_pck_path):
        packer = PCKPacker(original_pck_path, output_pck_path)
        packer.load_original_pck()
        packers.append(packer)
        return packer

    yield load_packer
    for packer in packers:
        packer.close()


@pytest.fixture
def rebuilt_pck(tmp_path):
    rebuilt_dir = tmp_path / "rebuilt"
    rebuilt_dir.mkdir()
    return rebuilt_dir / "SoundBank_SFX_1.pck"


@pytest.mark.parametrize("block_size", [1, 16])
@pytest.mark.parametrize("with_externals_section", [True, False])
def test_rebuild_without_changes_keeps_every_entry(tmp_path, make_packer, rebuilt_pck, block_size, with_externals_section):
    tables = original_tables()
    if not with_externals_section:
        tables["externals"] = []
    original_path = tmp_path / "original.pck"
    original_path.write_bytes(build_pck(languages=LANGUAGES, block_size=block_size, with_externals_section=with_externals_section, **tables))

    make_packer(original_path, rebuilt_pck).pack(use_patching=False)

    assert read_entries(rebuilt_pck) == expected_entries(tables)


def test_rebuild_counts_one_row_per_language_of_a_shared_id(tmp_path, make_packer, rebuilt_pck):
    original_path = tmp_path / "vo.pck"
    shared_banks = [(MEDIA_BANK_ID, 1, build_bnk(MEDIA_BANK_ID, language_id=1)), (MEDIA_BANK_ID, 3, build_bnk(MEDIA_BANK_ID, language_id=3))]
    shared_sounds = [(22, 1, make_wem(1)), (22, 3, make_wem(2)), (23, 3, make_wem(3))]
    original_path.write_bytes(build_pck(banks=shared_banks, sounds=shared_sounds, languages=LANGUAGES))

    make_packer(original_path, rebuilt_pck).pack(use_patching=False)

    rebuilt_bytes = rebuilt_pck.read_bytes()
    language_map_size, banks_table_size, sounds_table_size = struct.unpack_from("<III", rebuilt_bytes, 12)
    banks_row_count = struct.unpack_from("<I", rebuilt_bytes, 28 + language_map_size)[0]
    assert (banks_row_count, banks_table_size, sounds_table_size) == (2, 4 + 20 * 2, 4 + 20 * 3)
    assert read_entries(rebuilt_pck) == expected_entries({"banks": shared_banks, "sounds": shared_sounds})


def test_rebuild_keeps_the_language_names(tmp_path, original_pck, make_packer, rebuilt_pck):
    make_packer(original_pck, rebuilt_pck).pack(use_patching=False)

    rebuilt_indexer = PCKIndexer(rebuilt_pck)
    rebuilt_indexer.build_index()
    assert make_packer(rebuilt_pck, tmp_path / "unused.pck").language_names == LANGUAGES
    assert {lang_id: rebuilt_indexer.lang_map[lang_id] for lang_id in LANGUAGES} == {0: "sfx", 1: "english(us)", 3: "japanese"}


def test_replace_file_swaps_an_existing_entry(tmp_path, original_pck, make_packer, rebuilt_pck):
    replacement_path = tmp_path / "22.wem"
    replacement_path.write_bytes(make_wem(99, 80))
    packer = make_packer(original_pck, rebuilt_pck)

    packer.replace_file(22, replacement_path, lang_id=3)
    packer.replace_file(EXTERNAL_ID, replacement_path, lang_id=1)
    packer.pack(use_patching=False)

    expected = expected_entries(original_tables())
    expected["sounds"][(22, 3)] = make_wem(99, 80)
    expected["externals"][(EXTERNAL_ID, 1)] = make_wem(99, 80)
    assert read_entries(rebuilt_pck) == expected


@pytest.mark.parametrize(
    "file_id, target_section, expected_section",
    [
        (777, "soundbank_files", "sounds"),
        (777, "stream_files", "externals"),
        (0x1_0000_0777, "soundbank_files", "externals"),
    ],
)
def test_replace_file_adds_a_new_id(tmp_path, original_pck, make_packer, rebuilt_pck, file_id, target_section, expected_section):
    new_wem_path = tmp_path / "new.wem"
    new_wem_path.write_bytes(make_wem(77, 25))
    packer = make_packer(original_pck, rebuilt_pck)

    packer.replace_file(file_id, new_wem_path, lang_id=1, target_section=target_section)
    packer.pack(use_patching=False)

    expected = expected_entries(original_tables())
    expected[expected_section][(file_id, 1)] = make_wem(77, 25)
    assert read_entries(rebuilt_pck) == expected


def test_replace_file_requires_an_existing_replacement(tmp_path, original_pck, make_packer, rebuilt_pck):
    with pytest.raises(FileNotFoundError):
        make_packer(original_pck, rebuilt_pck).replace_file(21, tmp_path / "missing.wem")


def test_replace_bnk_wems_rewrites_only_the_given_language(tmp_path, original_pck, make_packer, rebuilt_pck):
    replacement_dir = tmp_path / f"{MEDIA_BANK_ID}_bnk"
    write_files(replacement_dir, {"12.wem": make_wem(120, 90), "999.wem": make_wem(9), "notes.wem": b"not an id"})
    packer = make_packer(original_pck, rebuilt_pck)

    packer.replace_bnk_wems(MEDIA_BANK_ID, replacement_dir, lang_id=1)
    packer.replace_bnk_wems(MISSING_BANK_ID, replacement_dir, lang_id=1)
    packer.pack(use_patching=False)

    expected = expected_entries(original_tables())
    expected["banks"][(MEDIA_BANK_ID, 1)] = build_bnk(MEDIA_BANK_ID, wems={**ENGLISH_BANK_WEMS, 12: make_wem(120, 90)}, language_id=1)
    assert read_entries(rebuilt_pck) == expected


def test_merge_bnk_wems_prefers_mod_then_streaming_then_patch(tmp_path, original_pck, make_packer, rebuilt_pck):
    mod_wem_path = tmp_path / "14.wem"
    mod_wem_path.write_bytes(make_wem(314, 33))
    patch_bnk_wems = {11: make_wem(211), 14: make_wem(214), 15: make_wem(215)}
    mod_wem_map = {12: make_wem(312, 70), 14: mod_wem_path}
    packer = make_packer(original_pck, rebuilt_pck)

    packer.merge_bnk_wems(MEDIA_BANK_ID, mod_wem_map, patch_bnk_wems, lang_id=1)
    packer.merge_bnk_wems(MISSING_BANK_ID, mod_wem_map, patch_bnk_wems, lang_id=1)
    packer.pack(use_patching=False)

    rebuilt_entries = read_entries(rebuilt_pck)
    assert read_bank_wems(rebuilt_entries["banks"][(MEDIA_BANK_ID, 1)]) == {
        11: ENGLISH_BANK_WEMS[11],
        12: make_wem(312, 70),
        13: ENGLISH_BANK_WEMS[13],
        14: make_wem(314, 33),
        15: make_wem(215),
    }
    unchanged = expected_entries(original_tables())
    del unchanged["banks"][(MEDIA_BANK_ID, 1)]
    del rebuilt_entries["banks"][(MEDIA_BANK_ID, 1)]
    assert rebuilt_entries == unchanged


def test_replace_and_add_raw_banks(original_pck, make_packer, rebuilt_pck):
    patched_bank = build_bnk(MEDIA_BANK_ID, wems={11: make_wem(90, 120)}, language_id=3)
    orphan_bank = build_bnk(5555, hirc_objects=[hirc_object(0x0B, 7, b"\x00" * 12)])
    packer = make_packer(original_pck, rebuilt_pck)

    assert packer.replace_bnk_raw(MEDIA_BANK_ID, patched_bank, lang_id=3) is True
    assert packer.replace_bnk_raw(MISSING_BANK_ID, orphan_bank, lang_id=0) is False
    assert packer.add_bnk_raw(5555, orphan_bank, lang_id=0) is True
    assert packer.add_bnk_raw(5555, patched_bank, lang_id=0) is False
    packer.pack(use_patching=False)

    expected = expected_entries(original_tables())
    expected["banks"][(MEDIA_BANK_ID, 3)] = patched_bank
    expected["banks"][(5555, 0)] = orphan_bank
    assert read_entries(rebuilt_pck) == expected


def test_add_or_replace_bnk_raw_targets_the_language_holding_the_bank(original_pck, make_packer, rebuilt_pck):
    patched_hirc_bank = build_bnk(HIRC_BANK_ID, hirc_objects=[hirc_object(0x02, 5, b"\x01" * 24)])
    orphan_bank = build_bnk(6666, hirc_objects=[])
    packer = make_packer(original_pck, rebuilt_pck)

    assert packer.add_or_replace_bnk_raw(HIRC_BANK_ID, patched_hirc_bank, fallback_lang=1) is True
    assert packer.add_or_replace_bnk_raw(6666, orphan_bank, fallback_lang=1) is True
    packer.pack(use_patching=False)

    expected = expected_entries(original_tables())
    expected["banks"][(HIRC_BANK_ID, 0)] = patched_hirc_bank
    expected["banks"][(6666, 1)] = orphan_bank
    assert read_entries(rebuilt_pck) == expected


def test_remove_wems_from_bnk(original_pck, make_packer, rebuilt_pck):
    packer = make_packer(original_pck, rebuilt_pck)

    assert packer.remove_wems_from_bnk(MEDIA_BANK_ID, [11, 13, 999], lang_id=1) == 2
    assert packer.remove_wems_from_bnk(MEDIA_BANK_ID, [999], lang_id=3) == 0
    assert packer.remove_wems_from_bnk(MISSING_BANK_ID, [11], lang_id=1) == 0
    packer.pack(use_patching=False)

    rebuilt_entries = read_entries(rebuilt_pck)
    assert read_bank_wems(rebuilt_entries["banks"][(MEDIA_BANK_ID, 1)]) == {12: ENGLISH_BANK_WEMS[12]}
    assert rebuilt_entries["banks"][(MEDIA_BANK_ID, 3)] == expected_entries(original_tables())["banks"][(MEDIA_BANK_ID, 3)]


def test_replace_files_from_directory_handles_loose_wems_and_bank_folders(tmp_path, original_pck, make_packer, rebuilt_pck):
    replacements_dir = tmp_path / "replacements"
    write_files(replacements_dir, {
        "22.wem": make_wem(122, 10),
        "readme.wem": b"not an id",
        f"{MEDIA_BANK_ID}_bnk/13.wem": make_wem(113, 50),
        "junk_bnk/13.wem": make_wem(1),
    })
    packer = make_packer(original_pck, rebuilt_pck)

    packer.replace_files_from_directory(replacements_dir, lang_id=1)
    packer.pack(use_patching=False)

    expected = expected_entries(original_tables())
    expected["sounds"][(22, 1)] = make_wem(122, 10)
    expected["banks"][(MEDIA_BANK_ID, 1)] = build_bnk(MEDIA_BANK_ID, wems={**ENGLISH_BANK_WEMS, 13: make_wem(113, 50)}, language_id=1)
    assert read_entries(rebuilt_pck) == expected
    with pytest.raises(FileNotFoundError):
        packer.replace_files_from_directory(tmp_path / "missing")


@pytest.mark.parametrize("payload_size", [30, 10, 60], ids=["same_size", "smaller", "larger"])
def test_patching_mode_overwrites_the_entry_in_place(tmp_path, original_pck, make_packer, rebuilt_pck, payload_size):
    replacement = make_wem(99, payload_size)
    replacement_path = tmp_path / "21.wem"
    replacement_path.write_bytes(replacement)
    sound_entry = next(entry for entry in PCKIndexer(original_pck).build_index()["sounds"] if entry["id"] == 21)
    packer = make_packer(original_pck, rebuilt_pck)

    packer.replace_file(21, replacement_path, lang_id=0)
    packer.pack(use_patching=True)

    original_bytes = original_pck.read_bytes()
    start, size = sound_entry["offset"], sound_entry["size"]
    patched_region = (replacement + b"\x00" * size)[:size]
    assert rebuilt_pck.read_bytes() == original_bytes[:start] + patched_region + original_bytes[start + size:]


def test_patching_mode_without_replacements_copies_the_original(original_pck, make_packer, rebuilt_pck):
    make_packer(original_pck, rebuilt_pck).pack()

    assert rebuilt_pck.read_bytes() == original_pck.read_bytes()


def test_load_rejects_an_invalid_magic(tmp_path, rebuilt_pck):
    broken_pck = tmp_path / "broken.pck"
    broken_pck.write_bytes(b"BKHD" + build_pck(sounds=[(1, 0, make_wem(1))])[4:])

    with pytest.raises(ValueError):
        PCKPacker(broken_pck, rebuilt_pck).load_original_pck()


class OffsetSink:

    def __init__(self, base_offset):
        self.base_offset = base_offset
        self.content = bytearray()

    def write(self, chunk):
        self.content += chunk

    def read_at(self, offset, size):
        start = offset - self.base_offset
        return bytes(self.content[start:start + size])


@pytest.mark.xfail(strict=True, reason="bug: past 4 GiB the alignment fill is written after each file instead of before it")
def test_rebuild_rows_past_4_gib_point_at_their_data(tmp_path):
    # Writing 4 GiB is not an option, so the table and data writers are driven at a 4 GiB offset directly.
    first_wem, second_wem = make_wem(1, 63), make_wem(2, 64)
    packer = PCKPacker(tmp_path / "unused.pck", tmp_path / "unused_output.pck")
    packer.file_list = [BytesIO(first_wem), BytesIO(second_wem)]
    table_rows = [(501, {0: (0, len(first_wem), 0)}), (502, {0: (1, len(second_wem), 0)})]
    data_start = 2**32 + 1
    table_sink = BytesIO()
    data_sink = OffsetSink(data_start)

    placements = packer._build_file_table(table_sink, table_rows, data_start)
    packer._write_audio_data(data_sink, placements)

    table_bytes = table_sink.getvalue()
    for row_index, wem_bytes in enumerate([first_wem, second_wem]):
        _, block_size, size, start_block, _ = struct.unpack_from("<5I", table_bytes, 4 + 20 * row_index)
        assert data_sink.read_at(block_size * start_block, size) == wem_bytes
