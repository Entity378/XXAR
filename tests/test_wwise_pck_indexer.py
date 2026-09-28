import pytest

from helpers import build_bnk, build_pck, make_wem
from src.wwise.pck_indexer import PCKIndexer

LANGUAGES = {0: "SFX", 1: "English(US)", 3: "Japanese"}
EXTERNAL_ID = 0x1234_5678_9ABC_DEF0


def sample_tables():
    return {
        "banks": [(1001, 0, build_bnk(1001)), (1002, 1, build_bnk(1002, wems={7: make_wem(7)}))],
        "sounds": [(2001, 0, make_wem(1, 33)), (2002, 3, make_wem(2, 50))],
        "externals": [(EXTERNAL_ID, 1, make_wem(3, 17))],
    }


def write_pck(tmp_path, name="SoundBank_SFX_1.pck", **pck_options):
    pck_path = tmp_path / name
    pck_path.write_bytes(build_pck(**pck_options))
    return pck_path


def entries_by_key(index, pck_bytes, section):
    return {
        (entry["id"], entry["lang_id"]): pck_bytes[entry["offset"]:entry["offset"] + entry["size"]]
        for entry in index[section]
    }


@pytest.mark.parametrize("block_size", [1, 16])
def test_build_index_locates_every_table_entry(tmp_path, block_size):
    tables = sample_tables()
    pck_path = write_pck(tmp_path, languages=LANGUAGES, block_size=block_size, **tables)

    index = PCKIndexer(pck_path).build_index()

    pck_bytes = pck_path.read_bytes()
    for section, entries in tables.items():
        assert entries_by_key(index, pck_bytes, section) == {(file_id, lang_id): file_bytes for file_id, lang_id, file_bytes in entries}
    assert all(entry["offset"] % block_size == 0 for entry in index["banks"] + index["sounds"] + index["externals"])


def test_language_names_come_from_the_pck_and_are_lowercased(tmp_path):
    languages = {0: "SFX", 1: "English(US)", 3: "Japanese", 9: "Klingon"}
    sounds = [(1, 0, make_wem(1)), (2, 1, make_wem(2)), (3, 3, make_wem(3)), (4, 9, make_wem(4)), (5, 2, make_wem(5)), (6, 12, make_wem(6))]
    pck_path = write_pck(tmp_path, languages=languages, sounds=sounds)

    index = PCKIndexer(pck_path).build_index()

    lang_names = {entry["id"]: entry["lang_name"] for entry in index["sounds"]}
    assert lang_names == {1: "sfx", 2: "english(us)", 3: "japanese", 4: "klingon", 5: "chinese", 6: "lang_12"}


def test_same_id_in_several_languages_is_looked_up_per_language(tmp_path):
    english_wem, japanese_wem = make_wem(10, 40), make_wem(11, 60)
    english_bank, japanese_bank = build_bnk(900, language_id=1), build_bnk(900, language_id=3)
    pck_path = write_pck(
        tmp_path,
        languages=LANGUAGES,
        banks=[(900, 3, japanese_bank), (900, 1, english_bank)],
        sounds=[(500, 3, japanese_wem), (500, 1, english_wem)],
    )
    indexer = PCKIndexer(pck_path)
    indexer.build_index()

    assert indexer.extract_single_file(500, lang_id=1) == english_wem
    assert indexer.extract_single_file(500, lang_id=3) == japanese_wem
    assert indexer.extract_single_file(500) == english_wem
    assert indexer.extract_single_file(900, "bnk", lang_id=3) == japanese_bank
    assert indexer.extract_single_file(900, "bnk") == english_bank
    with pytest.raises(KeyError):
        indexer.extract_single_file(500, lang_id=0)
    with pytest.raises(KeyError):
        indexer.extract_single_file(900, "wem")


def test_extract_single_file_reuses_an_open_handle(tmp_path):
    tables = sample_tables()
    pck_path = write_pck(tmp_path, **tables)
    indexer = PCKIndexer(pck_path)
    indexer.build_index()

    with open(pck_path, "rb") as pck_file:
        extracted = [indexer.extract_single_file(file_id, lang_id=lang_id, file_handle=pck_file) for file_id, lang_id, _ in tables["sounds"] + tables["externals"]]

    assert extracted == [file_bytes for _, _, file_bytes in tables["sounds"] + tables["externals"]]


def test_header_without_externals_section(tmp_path):
    tables = sample_tables()
    pck_path = write_pck(tmp_path, banks=tables["banks"], sounds=tables["sounds"], with_externals_section=False)

    index = PCKIndexer(pck_path).build_index()

    pck_bytes = pck_path.read_bytes()
    assert index["externals"] == []
    assert entries_by_key(index, pck_bytes, "banks") == {(file_id, lang_id): file_bytes for file_id, lang_id, file_bytes in tables["banks"]}
    assert entries_by_key(index, pck_bytes, "sounds") == {(file_id, lang_id): file_bytes for file_id, lang_id, file_bytes in tables["sounds"]}


def test_invalid_magic_is_rejected(tmp_path):
    pck_path = tmp_path / "broken.pck"
    pck_path.write_bytes(b"BKHD" + build_pck(sounds=[(1, 0, make_wem(1))])[4:])

    with pytest.raises(ValueError):
        PCKIndexer(pck_path).build_index()


def test_get_file_list_filters_by_table(tmp_path):
    indexer = PCKIndexer(write_pck(tmp_path, **sample_tables()))
    index = indexer.build_index()

    assert indexer.get_file_list("banks") == index["banks"]
    assert indexer.get_file_list("sounds") == index["sounds"]
    assert indexer.get_file_list("externals") == index["externals"]
    assert indexer.get_file_list() == index["banks"] + index["sounds"] + index["externals"]
    with pytest.raises(ValueError):
        indexer.get_file_list("streams")


@pytest.mark.parametrize("extract_bnk", [False, True])
def test_extract_all_writes_files_per_language_folder(tmp_path, extract_bnk):
    tables = sample_tables()
    pck_path = write_pck(tmp_path, languages=LANGUAGES, **tables)
    output_dir = tmp_path / "extracted"

    PCKIndexer(pck_path).extract_all(output_dir, extract_bnk=extract_bnk)

    extracted = {path.relative_to(output_dir).as_posix(): path.read_bytes() for path in output_dir.rglob("*") if path.is_file()}
    expected = {
        "sfx/2001.wem": tables["sounds"][0][2],
        "japanese/2002.wem": tables["sounds"][1][2],
        f"english(us)/{EXTERNAL_ID}.wem": tables["externals"][0][2],
    }
    if extract_bnk:
        expected.update({"sfx/1001.bnk": tables["banks"][0][2], "english(us)/1002.bnk": tables["banks"][1][2]})
    assert extracted == expected
