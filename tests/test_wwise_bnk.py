import struct

import pytest

from helpers import build_bnk, build_pck, hirc_object, make_wem
from src.wwise.bnk_handler import BNKFile, extract_bnk_wems
from src.wwise.bnk_indexer import BNKIndexer, count_didx_wems
from src.wwise.pck_indexer import PCKIndexer

BANK_ID = 428903628
HIRC_ONLY_BANK_ID = 111
HIRC_OBJECTS = [hirc_object(0x02, 0x1234, b"\x07" * 30), hirc_object(0x04, 0x5678, struct.pack("<II", 1, 0x99))]


def sample_wems():
    return {101: make_wem(1, 37), 202: make_wem(2, 64), 303: make_wem(3, 5)}


def read_chunks(bnk_bytes):
    chunks = {}
    position = 0
    while position < len(bnk_bytes):
        tag, size = struct.unpack_from("<4sI", bnk_bytes, position)
        chunks[tag] = (position + 8, size)
        position += 8 + size
    assert position == len(bnk_bytes)
    return chunks


def chunk_payload(bnk_bytes, tag):
    payload_start, payload_size = read_chunks(bnk_bytes)[tag]
    return bnk_bytes[payload_start:payload_start + payload_size]


def read_didx_rows(bnk_bytes):
    didx_start, didx_size = read_chunks(bnk_bytes)[b"DIDX"]
    return [struct.unpack_from("<III", bnk_bytes, didx_start + row_offset) for row_offset in range(0, didx_size, 12)]


def wems_by_didx(bnk_bytes):
    data_start, data_size = read_chunks(bnk_bytes)[b"DATA"]
    wems = {}
    previous_end = 0
    for wem_id, relative_offset, size in read_didx_rows(bnk_bytes):
        assert relative_offset >= previous_end
        wems[wem_id] = bnk_bytes[data_start + relative_offset:data_start + relative_offset + size]
        previous_end = relative_offset + size
    assert previous_end == data_size
    return wems


@pytest.mark.parametrize(
    "bnk_bytes",
    [
        build_bnk(BANK_ID, wems=sample_wems()),
        build_bnk(BANK_ID, wems=sample_wems(), hirc_objects=HIRC_OBJECTS),
        build_bnk(BANK_ID, wems={7: make_wem(7, 16)}, version=0x86, language_id=3),
        build_bnk(HIRC_ONLY_BANK_ID, hirc_objects=HIRC_OBJECTS),
        build_bnk(HIRC_ONLY_BANK_ID, hirc_objects=[]),
        build_bnk(HIRC_ONLY_BANK_ID),
    ],
    ids=["wems", "wems_and_hirc", "single_wem", "hirc_only", "empty_hirc", "header_only"],
)
def test_unmodified_bank_serializes_byte_identical(bnk_bytes):
    assert BNKFile(bnk_bytes=bnk_bytes).get_bytes() == bnk_bytes


def test_list_and_extract_wems_in_didx_order(tmp_path):
    wems = sample_wems()
    bank = BNKFile(bnk_bytes=build_bnk(BANK_ID, wems=wems, hirc_objects=HIRC_OBJECTS))

    assert bank.list_wems() == list(wems)
    assert {wem_id: bank.extract_wem(wem_id) for wem_id in wems} == wems
    assert bank.extract_wem(202, tmp_path / "202.wem") == wems[202]
    assert (tmp_path / "202.wem").read_bytes() == wems[202]
    with pytest.raises(KeyError):
        bank.extract_wem(999)


def test_bank_file_round_trips_through_disk(tmp_path):
    bnk_bytes = build_bnk(BANK_ID, wems=sample_wems(), hirc_objects=HIRC_OBJECTS)
    source_path = tmp_path / "source.bnk"
    source_path.write_bytes(bnk_bytes)

    BNKFile(source_path).save(tmp_path / "saved.bnk")

    assert (tmp_path / "saved.bnk").read_bytes() == bnk_bytes


@pytest.mark.parametrize("bnk_bytes", [build_bnk(HIRC_ONLY_BANK_ID, hirc_objects=HIRC_OBJECTS), build_bnk(HIRC_ONLY_BANK_ID)], ids=["hirc_only", "header_only"])
def test_bank_without_media_has_no_wems(bnk_bytes):
    bank = BNKFile(bnk_bytes=bnk_bytes)

    assert bank.list_wems() == []
    assert bank.remove_wem(101) is False
    with pytest.raises(ValueError):
        bank.extract_wem(101)
    with pytest.raises(ValueError):
        bank.replace_wem(101, wem_bytes=make_wem(1))


@pytest.mark.parametrize("target_id", [101, 202, 303], ids=["first", "middle", "last"])
@pytest.mark.parametrize("payload_size", [2, 90], ids=["shrink", "grow"])
def test_replace_wem_relays_data_like_wwise(target_id, payload_size):
    wems = sample_wems()
    replacement = make_wem(99, payload_size)
    bank = BNKFile(bnk_bytes=build_bnk(BANK_ID, wems=wems, hirc_objects=HIRC_OBJECTS))

    bank.replace_wem(target_id, wem_bytes=replacement)

    replaced_bnk_bytes = bank.get_bytes()
    data_start, _ = read_chunks(replaced_bnk_bytes)[b"DATA"]
    assert replaced_bnk_bytes == build_bnk(BANK_ID, wems={**wems, target_id: replacement}, hirc_objects=HIRC_OBJECTS)
    assert all((data_start + relative_offset) % 16 == 0 for _, relative_offset, _ in read_didx_rows(replaced_bnk_bytes))


def test_replace_wem_reads_the_replacement_from_a_path(tmp_path):
    wems = sample_wems()
    replacement_path = tmp_path / "202.wem"
    replacement_path.write_bytes(make_wem(42, 50))
    bank = BNKFile(bnk_bytes=build_bnk(BANK_ID, wems=wems))

    bank.replace_wem(202, wem_path=replacement_path)

    assert bank.get_bytes() == build_bnk(BANK_ID, wems={**wems, 202: make_wem(42, 50)})
    with pytest.raises(KeyError):
        bank.replace_wem(999, wem_bytes=make_wem(1))
    with pytest.raises(ValueError):
        bank.replace_wem(202)


def test_add_wem_appends_after_the_existing_wems():
    wems = sample_wems()
    added_wem = make_wem(4, 21)
    original_bnk_bytes = build_bnk(BANK_ID, wems=wems, hirc_objects=HIRC_OBJECTS)
    bank = BNKFile(bnk_bytes=original_bnk_bytes)

    bank.add_wem(404, added_wem)

    grown_bnk_bytes = bank.get_bytes()
    assert wems_by_didx(grown_bnk_bytes) == {**wems, 404: added_wem}
    assert chunk_payload(grown_bnk_bytes, b"HIRC") == chunk_payload(original_bnk_bytes, b"HIRC")
    assert BNKFile(bnk_bytes=grown_bnk_bytes).get_bytes() == grown_bnk_bytes


@pytest.mark.parametrize("removed_id", [101, 202, 303], ids=["first", "middle", "last"])
def test_remove_wem_drops_it_from_didx_and_data(removed_id):
    wems = sample_wems()
    bank = BNKFile(bnk_bytes=build_bnk(BANK_ID, wems=wems, hirc_objects=HIRC_OBJECTS))

    assert bank.remove_wem(removed_id) is True
    assert bank.remove_wem(removed_id) is False

    remaining_wems = {wem_id: wem_bytes for wem_id, wem_bytes in wems.items() if wem_id != removed_id}
    stripped_bnk_bytes = bank.get_bytes()
    assert wems_by_didx(stripped_bnk_bytes) == remaining_wems
    assert BNKFile(bnk_bytes=stripped_bnk_bytes).list_wems() == list(remaining_wems)


def test_removing_every_wem_leaves_empty_media_chunks():
    bank = BNKFile(bnk_bytes=build_bnk(BANK_ID, wems=sample_wems()))

    for wem_id in list(sample_wems()):
        bank.remove_wem(wem_id)

    emptied_bnk_bytes = bank.get_bytes()
    chunks = read_chunks(emptied_bnk_bytes)
    assert chunks[b"DIDX"][1] == 0 and chunks[b"DATA"][1] == 0
    assert BNKFile(bnk_bytes=emptied_bnk_bytes).list_wems() == []


def test_unknown_chunk_does_not_break_parsing():
    wems = sample_wems()
    bank = BNKFile(bnk_bytes=build_bnk(BANK_ID, wems=wems) + b"STID" + struct.pack("<I", 8) + b"\x01\x00\x00\x00abcd")

    assert {wem_id: bank.extract_wem(wem_id) for wem_id in bank.list_wems()} == wems


def test_unknown_chunk_survives_serialization():
    bnk_bytes = build_bnk(BANK_ID, wems=sample_wems()) + b"STID" + struct.pack("<I", 8) + b"\x01\x00\x00\x00abcd"

    assert BNKFile(bnk_bytes=bnk_bytes).get_bytes() == bnk_bytes


@pytest.mark.parametrize("bnk_bytes", [b"AKPK" + b"\x00" * 28, make_wem(1)], ids=["pck_header", "riff"])
def test_invalid_magic_is_rejected(tmp_path, bnk_bytes):
    bnk_path = tmp_path / "invalid.bnk"
    bnk_path.write_bytes(bnk_bytes)

    with pytest.raises(ValueError):
        BNKFile(bnk_bytes=bnk_bytes)
    with pytest.raises(ValueError):
        BNKFile(bnk_path)


def test_extract_bnk_wems_writes_one_file_per_wem(tmp_path):
    wems = sample_wems()
    bnk_path = tmp_path / f"{BANK_ID}.bnk"
    bnk_path.write_bytes(build_bnk(BANK_ID, wems=wems, hirc_objects=HIRC_OBJECTS))

    extract_bnk_wems(bnk_path, tmp_path / "extracted" / "nested")

    extracted = {int(path.stem): path.read_bytes() for path in (tmp_path / "extracted" / "nested").iterdir()}
    assert extracted == wems


def test_bnk_indexer_reads_didx_entries_and_payloads():
    wems = sample_wems()
    bnk_bytes = build_bnk(BANK_ID, wems=wems, hirc_objects=HIRC_OBJECTS)
    indexer = BNKIndexer(bnk_bytes)

    entries = indexer.parse_didx()

    assert [(entry["wem_id"], entry["size"]) for entry in entries] == [(wem_id, len(wem_bytes)) for wem_id, wem_bytes in wems.items()]
    assert indexer.get_wem_ids() == list(wems)
    assert indexer.get_wem_count() == 3
    assert {wem_id: indexer.extract_wem(wem_id) for wem_id in wems} == wems
    with pytest.raises(KeyError):
        indexer.extract_wem(999)


def test_bnk_indexer_only_needs_the_bank_up_to_the_data_header():
    wems = sample_wems()
    bnk_bytes = build_bnk(BANK_ID, wems=wems, hirc_objects=HIRC_OBJECTS)
    data_start, _ = read_chunks(bnk_bytes)[b"DATA"]

    assert BNKIndexer(bnk_bytes[:data_start]).parse_didx() == BNKIndexer(bnk_bytes).parse_didx()


def test_bnk_indexer_on_a_bank_without_media():
    indexer = BNKIndexer(build_bnk(HIRC_ONLY_BANK_ID, hirc_objects=HIRC_OBJECTS))

    assert indexer.parse_didx() == []
    assert indexer.get_wem_count() == 0


@pytest.mark.parametrize("block_size", [1, 16])
def test_indexers_read_a_bank_embedded_inside_a_pck(tmp_path, block_size):
    wems = sample_wems()
    media_bank = build_bnk(BANK_ID, wems=wems, hirc_objects=HIRC_OBJECTS)
    hirc_only_bank = build_bnk(HIRC_ONLY_BANK_ID, hirc_objects=HIRC_OBJECTS)
    pck_path = tmp_path / "SoundBank_SFX_1.pck"
    pck_path.write_bytes(build_pck(
        banks=[(HIRC_ONLY_BANK_ID, 0, hirc_only_bank), (BANK_ID, 0, media_bank)],
        sounds=[(55, 0, make_wem(55))],
        block_size=block_size,
    ))
    banks = {bank["id"]: bank for bank in PCKIndexer(pck_path).build_index()["banks"]}
    media_entry = banks[BANK_ID]
    pck_bytes = pck_path.read_bytes()

    with open(pck_path, "rb") as pck_file:
        assert count_didx_wems(pck_file, banks[HIRC_ONLY_BANK_ID]["offset"], banks[HIRC_ONLY_BANK_ID]["size"]) == 0
        assert count_didx_wems(pck_file, media_entry["offset"], media_entry["size"]) == 3
    embedded_indexer = BNKIndexer(pck_bytes[media_entry["offset"]:media_entry["offset"] + media_entry["size"]])
    embedded_indexer.parse_didx()
    assert {wem_id: embedded_indexer.extract_wem(wem_id) for wem_id in wems} == wems
