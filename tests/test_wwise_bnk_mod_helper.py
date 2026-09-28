import pytest

from helpers import build_bnk, build_pck, make_wem, write_files
from src.wwise.bnk_mod_helper import mod_soundbank_pck, prepare_bnk_structure
from src.wwise.pck_indexer import PCKIndexer

BANK_ID = 428903628
ORIGINAL_WEMS = {1: make_wem(1, 64), 2: make_wem(2, 30), 3: make_wem(3, 48)}


def test_prepare_bnk_structure_copies_wems_into_a_bank_folder(tmp_path):
    write_files(tmp_path / "wems", {"1.wem": make_wem(10), "3.wem": make_wem(30), "cover.png": b"png"})

    structure_dir = prepare_bnk_structure(tmp_path / "wems", BANK_ID, tmp_path / "structure")

    copied = {path.name: path.read_bytes() for path in (structure_dir / f"{BANK_ID}_bnk").iterdir()}
    assert copied == {"1.wem": make_wem(10), "3.wem": make_wem(30)}


def test_prepare_bnk_structure_needs_at_least_one_wem(tmp_path):
    (tmp_path / "empty").mkdir()

    with pytest.raises(FileNotFoundError):
        prepare_bnk_structure(tmp_path / "empty", BANK_ID, tmp_path / "structure")


def test_mod_soundbank_pck_embeds_same_size_wems_in_place(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    original_bank = build_bnk(BANK_ID, wems=ORIGINAL_WEMS)
    loose_sound = make_wem(77, 25)
    original_pck = tmp_path / "SoundBank_SFX_1.pck"
    original_pck.write_bytes(build_pck(banks=[(BANK_ID, 0, original_bank)], sounds=[(77, 0, loose_sound)], block_size=16))
    write_files(tmp_path / "my_wems", {"1.wem": make_wem(100, 64), "3.wem": make_wem(300, 48)})
    output_pck = tmp_path / "SoundBank_SFX_1_MODDED.pck"

    mod_soundbank_pck(original_pck, tmp_path / "my_wems", BANK_ID, output_pck)

    index = PCKIndexer(output_pck).build_index()
    output_bytes = output_pck.read_bytes()
    bank_entry, sound_entry = index["banks"][0], index["sounds"][0]
    assert len(output_bytes) == len(original_pck.read_bytes())
    assert output_bytes[bank_entry["offset"]:bank_entry["offset"] + bank_entry["size"]] == build_bnk(
        BANK_ID, wems={**ORIGINAL_WEMS, 1: make_wem(100, 64), 3: make_wem(300, 48)}
    )
    assert output_bytes[sound_entry["offset"]:sound_entry["offset"] + sound_entry["size"]] == loose_sound
    assert not (tmp_path / "temp_bnk_structure").exists()
