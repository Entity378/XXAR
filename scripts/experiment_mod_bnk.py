# Follow-up to experiment_inject_bnk.py: replace specific WEMs inside the injected BNK 2247887612
# with Delirium.wem, then rebuild the Persistent overlay of SoundBank_SFX_8.pck. Patch.pck stays
# nulled from the inject step. Reverts the same way (delete overlay + restore Patch.pck backup).
#
#   python scripts/experiment_mod_bnk.py
import logging
import os
import sys
from io import BytesIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.wwise.bnk_handler import BNKFile
from src.wwise.pck_indexer import PCKIndexer
from src.wwise.pck_packer import PCKPacker

TARGET_BNK = 2247887612
LANG_ID = 0
REPLACE_WEM_IDS = [188952569, 193970784, 879091625]

STREAMING = Path(r"C:\Program Files\HoYoPlay\games\ZenlessZoneZero Game\ZenlessZoneZero_Data\StreamingAssets\Audio\Windows\Full")
PERSISTENT = Path(r"C:\Program Files\HoYoPlay\games\ZenlessZoneZero Game\ZenlessZoneZero_Data\Persistent\Audio\Windows\Full")

SB8_SOURCE = STREAMING / "SoundBank_SFX_8.pck"
SB8_OVERLAY = PERSISTENT / "SoundBank_SFX_8.pck"
PATCH_BACKUP = PERSISTENT / "Patch.pck.xxar_backup"
DELIRIUM = Path(os.environ["USERPROFILE"]) / "Downloads" / "Delirium.wem"


def extract_bnk_bytes(pck_path, bnk_id):
    index = PCKIndexer(str(pck_path)).build_index()
    bank = next((b for b in index["banks"] if b["id"] == bnk_id), None)
    if bank is None:
        raise SystemExit(f"BNK {bnk_id} not found in {pck_path.name}")
    raw = pck_path.read_bytes()
    return raw[bank["offset"]:bank["offset"] + bank["size"]], bank["lang_id"]


def main():
    logging.getLogger("xxar").setLevel(logging.WARNING)
    if not DELIRIUM.exists():
        raise SystemExit(f"Delirium.wem not found: {DELIRIUM}")
    if not PATCH_BACKUP.exists():
        raise SystemExit(f"Pristine source missing: {PATCH_BACKUP} (run experiment_inject_bnk.py first)")

    wem_bytes = DELIRIUM.read_bytes()
    print(f"Delirium.wem: {len(wem_bytes):,} bytes")

    print(f"Extracting pristine BNK {TARGET_BNK} from {PATCH_BACKUP.name} ...")
    bnk_bytes, lang_id = extract_bnk_bytes(PATCH_BACKUP, TARGET_BNK)
    bnk = BNKFile(bnk_bytes=bnk_bytes)
    present = set(bnk.list_wems())
    print(f"  BNK has {len(present)} WEMs; original size {len(bnk_bytes):,} bytes")

    missing = [w for w in REPLACE_WEM_IDS if w not in present]
    if missing:
        raise SystemExit(f"WEM id(s) not in BNK: {missing}")

    for wid in REPLACE_WEM_IDS:
        bnk.replace_wem(wid, wem_bytes=wem_bytes)
        print(f"  replaced WEM {wid} -> Delirium.wem")

    modified_bnk = bnk.get_bytes()
    print(f"  modified BNK size: {len(modified_bnk):,} bytes")

    print(f"Rebuilding overlay {SB8_OVERLAY} ...")
    SB8_OVERLAY.parent.mkdir(parents=True, exist_ok=True)
    if SB8_OVERLAY.exists():
        SB8_OVERLAY.chmod(0o644)
    packer = PCKPacker(str(SB8_SOURCE), str(SB8_OVERLAY))
    packer.load_original_pck()
    new_index = len(packer.file_list)
    packer.file_list.append(BytesIO(modified_bnk))
    packer.soundbank_titles.setdefault(lang_id if lang_id is not None else LANG_ID, {})[TARGET_BNK] = [
        (new_index, len(modified_bnk), 0)
    ]
    packer.pack(use_patching=False)
    packer.close()
    print(f"  overlay size: {SB8_OVERLAY.stat().st_size:,} bytes")

    # verify the modded BNK round-trips and carries Delirium-sized WEMs
    idx = PCKIndexer(str(SB8_OVERLAY)).build_index()
    b = next((x for x in idx["banks"] if x["id"] == TARGET_BNK), None)
    print(f"  TARGET in overlay: {b is not None}, size {b['size']:,}" if b else "  TARGET MISSING")
    raw = SB8_OVERLAY.read_bytes()
    rt = BNKFile(bnk_bytes=raw[b["offset"]:b["offset"] + b["size"]])
    print(f"  re-indexed BNK WEM count: {len(list(rt.list_wems()))}")

    print("\nDone. Launch the game and check whether Delirium plays for that song.")


if __name__ == "__main__":
    main()
