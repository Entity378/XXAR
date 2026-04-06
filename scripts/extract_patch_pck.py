# Extracts all WEM files from Patch.pck (including WEMs embedded inside BNKs)
# Usage: python scripts/extract_patch_pck.py <path_to_Patch.pck> [output_dir]

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.wwise.pck_indexer import PCKIndexer
from src.wwise.bnk_handler import BNKFile


def extract_patch_pck(pck_path, output_dir):
    pck_path = Path(pck_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Indexing {pck_path.name}...")
    indexer = PCKIndexer(str(pck_path))
    index = indexer.build_index()

    banks = index["banks"]
    sounds = index["sounds"]
    externals = index["externals"]

    print(f"  {len(banks)} BNK(s), {len(sounds)} standalone WEM(s), {len(externals)} external(s)")

    with open(pck_path, "rb") as f:
        # Extract standalone WEMs
        standalone_dir = output_dir / "standalone"
        if sounds or externals:
            standalone_dir.mkdir(parents=True, exist_ok=True)

        for entry in sounds + externals:
            f.seek(entry["offset"])
            data = f.read(entry["size"])
            out_file = standalone_dir / f"{entry['id']}.wem"
            out_file.write_bytes(data)

        standalone_count = len(sounds) + len(externals)
        if standalone_count:
            print(f"  Extracted {standalone_count} standalone WEM(s) -> {standalone_dir}")

        # Extract WEMs from BNKs
        bnk_wem_count = 0
        for bank in banks:
            f.seek(bank["offset"])
            bnk_bytes = f.read(bank["size"])

            try:
                bnk = BNKFile(bnk_bytes=bnk_bytes)
            except Exception as e:
                print(f"  Warning: failed to parse BNK {bank['id']}: {e}")
                continue

            wem_ids = bnk.list_wems()
            if not wem_ids:
                continue

            bnk_dir = output_dir / f"bnk_{bank['id']}"
            bnk_dir.mkdir(parents=True, exist_ok=True)

            for wem_id in wem_ids:
                wem_data = bnk.extract_wem(wem_id)
                out_file = bnk_dir / f"{wem_id}.wem"
                out_file.write_bytes(wem_data)
                bnk_wem_count += 1

            print(f"  BNK {bank['id']}: {len(wem_ids)} WEM(s) -> {bnk_dir}")

    total = standalone_count + bnk_wem_count
    print(f"\nDone: {total} WEM(s) extracted to {output_dir}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/extract_patch_pck.py <Patch.pck> [output_dir]")
        sys.exit(1)

    pck = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else f"{Path(pck).stem}_extracted"
    extract_patch_pck(pck, out)
