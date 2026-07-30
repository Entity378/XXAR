# One-off experiment (ZZZ): a Patch.pck BNK with no SoundBank counterpart loses its audio when the
# override entry is nulled, because there is nothing to fall back to. This injects the whole BNK
# (here 2247887612, a 713-WEM data bank) into a COPY of SoundBank_SFX_8.pck written as a Persistent
# overlay, then nulls the BNK in the live Patch.pck (after a .xxar_backup) the same way the app does.
#
# Touches game files: writes Persistent/.../SoundBank_SFX_8.pck and edits Persistent/.../Patch.pck.
# The StreamingAssets SoundBank_SFX_8.pck (manifest-valid) is never modified. Fully reversible:
# delete the overlay and restore Patch.pck from Patch.pck.xxar_backup (or let the game re-download).
#
#   python scripts/experiment_inject_bnk.py
import logging
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.wwise.override_pck_patcher import BACKUP_SUFFIX, _null_bnk_ids_in_file_table
from src.wwise.pck_indexer import PCKIndexer
from src.wwise.pck_packer import PCKPacker

TARGET_BNK = 2247887612
LANG_ID = 0

STREAMING = Path(r"C:\Program Files\HoYoPlay\games\ZenlessZoneZero Game\ZenlessZoneZero_Data\StreamingAssets\Audio\Windows\Full")
PERSISTENT = Path(r"C:\Program Files\HoYoPlay\games\ZenlessZoneZero Game\ZenlessZoneZero_Data\Persistent\Audio\Windows\Full")

SB8_SOURCE = STREAMING / "SoundBank_SFX_8.pck"
SB8_OVERLAY = PERSISTENT / "SoundBank_SFX_8.pck"
PATCH = PERSISTENT / "Patch.pck"


def extract_bnk_bytes(pck_path, bnk_id):
    index = PCKIndexer(str(pck_path)).build_index()
    bank = next((b for b in index["banks"] if b["id"] == bnk_id), None)
    if bank is None:
        raise SystemExit(f"BNK {bnk_id} not found in {pck_path.name}")
    raw = pck_path.read_bytes()
    return raw[bank["offset"]:bank["offset"] + bank["size"]], bank["lang_id"]


def build_overlay_with_added_bnk(bnk_bytes, lang_id):
    from io import BytesIO

    SB8_OVERLAY.parent.mkdir(parents=True, exist_ok=True)
    packer = PCKPacker(str(SB8_SOURCE), str(SB8_OVERLAY))
    packer.load_original_pck()
    if any(TARGET_BNK in banks for banks in packer.soundbank_titles.values()):
        raise SystemExit(f"BNK {TARGET_BNK} already present in {SB8_SOURCE.name}; nothing to test")
    new_index = len(packer.file_list)
    packer.file_list.append(BytesIO(bnk_bytes))
    packer.soundbank_titles.setdefault(lang_id, {})[TARGET_BNK] = [(new_index, len(bnk_bytes), 0)]
    packer.pack(use_patching=False)
    packer.close()


def verify_overlay():
    index = PCKIndexer(str(SB8_OVERLAY)).build_index()
    ids = {b["id"] for b in index["banks"]}
    src_ids = {b["id"] for b in PCKIndexer(str(SB8_SOURCE)).build_index()["banks"]}
    print(f"  overlay banks: {len(ids)} (source {len(src_ids)}, expected +1)")
    print(f"  TARGET present in overlay: {TARGET_BNK in ids}")
    print(f"  id set == source + TARGET: {ids == src_ids | {TARGET_BNK}}")


def backup_and_null_patch():
    backup = PATCH.with_name(PATCH.name + BACKUP_SUFFIX)
    if not backup.exists():
        shutil.copy2(PATCH, backup)
        print(f"  backed up Patch.pck -> {backup.name}")
    else:
        print(f"  backup already exists: {backup.name} (left as-is)")
    nulled = _null_bnk_ids_in_file_table(PATCH, {TARGET_BNK})
    print(f"  nulled in Patch.pck: {sorted(nulled)}")
    still = {b["id"] for b in PCKIndexer(str(PATCH)).build_index()["banks"]}
    print(f"  TARGET still indexed in Patch.pck: {TARGET_BNK in still} (expected False)")


def main():
    logging.getLogger("xxar").setLevel(logging.WARNING)
    print(f"Extracting BNK {TARGET_BNK} from Patch.pck ...")
    bnk_bytes, lang_id = extract_bnk_bytes(PATCH, TARGET_BNK)
    print(f"  {len(bnk_bytes):,} bytes, lang_id={lang_id}")

    print(f"Building overlay {SB8_OVERLAY} with BNK added ...")
    build_overlay_with_added_bnk(bnk_bytes, lang_id if lang_id is not None else LANG_ID)
    print(f"  overlay size: {SB8_OVERLAY.stat().st_size:,} bytes")
    verify_overlay()

    print("Nulling BNK in live Patch.pck ...")
    backup_and_null_patch()

    print("\nDone. Launch the game and check whether the song plays.")
    print("Revert: delete the overlay and restore Patch.pck:")
    print(f'  del "{SB8_OVERLAY}"')
    print(f'  copy /Y "{PATCH}{BACKUP_SUFFIX}" "{PATCH}"')


if __name__ == "__main__":
    main()
