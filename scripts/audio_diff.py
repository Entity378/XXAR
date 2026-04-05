#!/usr/bin/env python3
# audio_diff.py — Extract WEMs from ZZZ PCK archives and diff two versions.
# Usage:
# python audio_diff.py extract <pck_dir> <out_dir>
# Extract all WEMs from SoundBank_*.pck files in <pck_dir> into <out_dir>.
# Files are named <wem_id>.wem.
# python audio_diff.py diff <new_dir> <old_dir> <diff_dir>
# Copy WEMs from <new_dir> that are absent or changed in <old_dir>
# into <diff_dir>.  Comparison is by WEM ID + SHA-256 content hash.
# python audio_diff.py auto <new_pck_dir> <old_pck_dir> <diff_dir>
# Convenience: extract both versions to temp folders, then diff.
# Temp folders are kept alongside <diff_dir> for reuse.
# Examples:
# # Extract 2.2 audio
# python audio_diff.py extract ~/Downloads/audio_zip_En/.../En audio_en_2.2
# # Extract 2.1 audio
# python audio_diff.py extract ~/Downloads/audio_zip_En_21/.../En audio_en_2.1
# # Get only the new/changed WEMs
# python audio_diff.py diff audio_en_2.2 audio_en_2.1 diff_audio_en_2.2
# # Or do it all in one shot
# python audio_diff.py auto .../En_22 .../En_21 diff_audio_en_2.2

import hashlib
import json
import shutil
import struct
import sys
from pathlib import Path


# Minimal PCK + BNK readers (standalone, no project imports needed)

def _read_u32(f):
    return struct.unpack("<I", f.read(4))[0]

def _parse_pck_table(f, section_size, use_8byte_id=False):
    entries = []
    if section_size == 0:
        return entries
    count = _read_u32(f)
    for _ in range(count):
        file_id = struct.unpack("<Q", f.read(8))[0] if use_8byte_id else _read_u32(f)
        blocksize = _read_u32(f)
        size      = _read_u32(f)
        off_block = _read_u32(f)
        _read_u32(f)  # lang_id
        offset = off_block * blocksize if blocksize else off_block
        entries.append((file_id, offset, size))
    return entries

def _index_pck_banks(pck_path):
    # Return list of (bnk_id, offset, size) for BNK entries in a PCK.
    banks = []
    with open(pck_path, "rb") as f:
        if f.read(4) != b"AKPK":
            return banks
        header_size = _read_u32(f)
        _read_u32(f)  # version
        sec1 = _read_u32(f)
        sec2 = _read_u32(f)
        sec3 = _read_u32(f)
        sec_sum = sec1 + sec2 + sec3 + 0x10
        sec4 = _read_u32(f) if sec_sum < header_size else 0

        strings_offset = f.tell()
        f.seek(strings_offset + sec1)          # skip language strings
        banks = _parse_pck_table(f, sec2)      # sec2 = BNK table
    return banks

def _extract_wems_from_bnk(bnk_bytes):
    # Parse a BNK blob and return list of (wem_id, wem_bytes).
    from io import BytesIO
    results = []
    stream = BytesIO(bnk_bytes)
    didx_entries = {}  # wem_id -> (offset, size)
    data_offset = None

    while True:
        tag = stream.read(4)
        if len(tag) < 4:
            break
        chunk_size = struct.unpack("<I", stream.read(4))[0]
        chunk_start = stream.tell()

        if tag == b"DIDX":
            for _ in range(chunk_size // 12):
                wem_id  = struct.unpack("<I", stream.read(4))[0]
                offset  = struct.unpack("<I", stream.read(4))[0]
                size    = struct.unpack("<I", stream.read(4))[0]
                didx_entries[wem_id] = (offset, size)
        elif tag == b"DATA":
            data_offset = chunk_start
            stream.seek(chunk_start + chunk_size)
        else:
            stream.seek(chunk_start + chunk_size)

        if didx_entries and data_offset is not None:
            break

    if not didx_entries or data_offset is None:
        return results

    for wem_id, (rel_offset, size) in didx_entries.items():
        abs_offset = data_offset + rel_offset
        results.append((wem_id, bnk_bytes[abs_offset:abs_offset + size]))

    return results


def extract_soundbank_pck(pck_path, out_dir):
    # Extract all WEMs from BNKs inside a SoundBank PCK. Returns (bnk_count, wem_count).
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    bank_entries = _index_pck_banks(pck_path)
    bnk_count = 0
    wem_count = 0

    with open(pck_path, "rb") as f:
        for bnk_id, offset, size in bank_entries:
            if size == 0:
                continue
            f.seek(offset)
            bnk_bytes = f.read(size)
            wems = _extract_wems_from_bnk(bnk_bytes)
            bnk_count += 1
            for wem_id, wem_bytes in wems:
                if not wem_bytes:
                    continue
                dest = out_dir / f"{wem_id}.wem"
                if dest.exists() and dest.read_bytes() == wem_bytes:
                    continue
                dest.write_bytes(wem_bytes)
                wem_count += 1

    return bnk_count, wem_count


# Main commands

def cmd_extract(pck_dir, out_dir):
    pck_dir = Path(pck_dir)
    out_dir = Path(out_dir)

    pck_files = sorted(pck_dir.glob("SoundBank_*.pck"))
    if not pck_files:
        print(f"No SoundBank_*.pck files found in {pck_dir}")
        sys.exit(1)

    print(f"Extracting WEMs from {len(pck_files)} SoundBank PCK(s) → {out_dir}/")
    total_wems = 0
    for pck in pck_files:
        bnks, wems = extract_soundbank_pck(pck, out_dir)
        print(f"  {pck.name:40s}  {bnks} BNKs  →  {wems} WEMs")
        total_wems += wems

    all_wems = list(out_dir.glob("*.wem"))
    print(f"\nDone. {len(all_wems)} total WEM files in {out_dir}/")


def _hash_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def cmd_diff(new_dir, old_dir, diff_dir):
    new_dir  = Path(new_dir)
    old_dir  = Path(old_dir)
    diff_dir = Path(diff_dir)

    new_wems = {p.stem: p for p in new_dir.glob("*.wem")}
    old_wems = {p.stem: p for p in old_dir.glob("*.wem")}

    if not new_wems:
        print(f"No WEM files found in {new_dir}")
        sys.exit(1)

    print(f"Comparing {len(new_wems)} new WEMs vs {len(old_wems)} old WEMs...")

    diff_dir.mkdir(parents=True, exist_ok=True)

    added   = []
    changed = []
    same    = 0

    for wem_id, new_path in sorted(new_wems.items(), key=lambda x: x[0]):
        if wem_id not in old_wems:
            added.append(wem_id)
            shutil.copy2(new_path, diff_dir / new_path.name)
        else:
            new_hash = _hash_file(new_path)
            old_hash = _hash_file(old_wems[wem_id])
            if new_hash != old_hash:
                changed.append(wem_id)
                shutil.copy2(new_path, diff_dir / new_path.name)
            else:
                same += 1

    removed = [wem_id for wem_id in old_wems if wem_id not in new_wems]

    # Write a summary JSON alongside the diff
    summary = {
        "new_dir": str(new_dir),
        "old_dir": str(old_dir),
        "added":   added,
        "changed": changed,
        "removed": removed,
        "unchanged": same,
    }
    (diff_dir / "diff_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )

    print(f"\n  Added:     {len(added)}")
    print(f"  Changed:   {len(changed)}")
    print(f"  Removed:   {len(removed)}  (listed in diff_summary.json, not copied)")
    print(f"  Unchanged: {same}")
    print(f"\n  Diff WEMs written to: {diff_dir}/")
    print(f"  Summary:              {diff_dir}/diff_summary.json")


def cmd_auto(new_pck_dir, old_pck_dir, diff_dir):
    diff_dir = Path(diff_dir)
    new_extracted = diff_dir.parent / (diff_dir.name.replace("diff_", "extracted_new_", 1) or "extracted_new")
    old_extracted = diff_dir.parent / (diff_dir.name.replace("diff_", "extracted_old_", 1) or "extracted_old")

    print(f"=== Step 1/3: Extract new version → {new_extracted}/")
    cmd_extract(new_pck_dir, new_extracted)

    print(f"\n=== Step 2/3: Extract old version → {old_extracted}/")
    cmd_extract(old_pck_dir, old_extracted)

    print(f"\n=== Step 3/3: Diff → {diff_dir}/")
    cmd_diff(new_extracted, old_extracted, diff_dir)


# Entry point

USAGE = __doc__

def main():
    args = sys.argv[1:]
    if not args:
        print(USAGE)
        sys.exit(0)

    cmd = args[0]

    if cmd == "extract" and len(args) == 3:
        cmd_extract(args[1], args[2])
    elif cmd == "diff" and len(args) == 4:
        cmd_diff(args[1], args[2], args[3])
    elif cmd == "auto" and len(args) == 4:
        cmd_auto(args[1], args[2], args[3])
    else:
        print(USAGE)
        sys.exit(1)


if __name__ == "__main__":
    main()
