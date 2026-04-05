# Dump raw hex of MusicRanSeqCntr (0x0D) objects to reverse-engineer structure.
import struct
import sys
from pathlib import Path
from collections import defaultdict

HIRC_TYPE_MUSIC_RANSEQ = 0x0D
HIRC_TYPE_MUSIC_SEGMENT = 0x0A


def find_hirc_sections(content):
    results = []
    pos = -1
    flen = len(content)
    while True:
        pos = content.find(b"HIRC", pos + 1)
        if pos == -1:
            break
        if pos + 12 > flen:
            break
        section_size = struct.unpack_from("<I", content, pos + 4)[0]
        if section_size < 4 or pos + 8 + section_size > flen:
            continue
        results.append((pos + 8, section_size))
    return results


def scan_file(filepath):
    content = filepath.read_bytes()
    objects_by_type = defaultdict(list)
    for hirc_start, hirc_size in find_hirc_sections(content):
        section_end = hirc_start + hirc_size
        num_objects = struct.unpack_from("<I", content, hirc_start)[0]
        pos = hirc_start + 4
        for _ in range(num_objects):
            if pos + 5 > section_end:
                break
            obj_type = content[pos]
            obj_size = struct.unpack_from("<I", content, pos + 1)[0]
            obj_data_start = pos + 5
            if obj_data_start + obj_size > len(content):
                break
            obj_id = struct.unpack_from("<I", content, obj_data_start)[0]
            objects_by_type[obj_type].append({
                "id": obj_id,
                "data_start": obj_data_start,
                "size": obj_size,
                "data": content[obj_data_start : obj_data_start + obj_size],
            })
            pos = obj_data_start + obj_size
    return objects_by_type


def hex_dump(data, offset=0, width=16, max_lines=None):
    lines = []
    for i in range(0, len(data), width):
        if max_lines and len(lines) >= max_lines:
            lines.append("  ...")
            break
        chunk = data[i:i+width]
        hex_part = " ".join(f"{b:02x}" for b in chunk)
        ascii_part = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append(f"  {offset+i:4d} | {hex_part:<{width*3}} | {ascii_part}")
    return "\n".join(lines)


def main():
    game = sys.argv[1] if len(sys.argv) > 1 else "zzz"
    max_dump = int(sys.argv[2]) if len(sys.argv) > 2 else 3

    paths = {
        "zzz": Path(r"C:\Program Files\HoYoPlay\games\ZenlessZoneZero Game\ZenlessZoneZero_Data\StreamingAssets\Audio\Windows\Full"),
        "gi": Path(r"C:\Program Files\HoYoPlay\games\Genshin Impact game\GenshinImpact_Data\StreamingAssets\AudioAssets"),
        "hsr": Path(r"C:\Program Files\HoYoPlay\games\Star Rail Games\StarRail_Data\StreamingAssets\Audio\AudioPackage\Windows"),
    }
    audio_root = paths.get(game)
    if not audio_root or not audio_root.exists():
        print(f"Path not found: {audio_root}")
        return

    # Also collect all segment IDs for cross-referencing
    all_segment_ids = set()

    bank_files = sorted(audio_root.rglob("*.pck"))
    all_ranseq = []

    for pck_file in bank_files:
        objects = scan_file(pck_file)
        for obj in objects.get(HIRC_TYPE_MUSIC_SEGMENT, []):
            all_segment_ids.add(obj["id"])
        for obj in objects.get(HIRC_TYPE_MUSIC_RANSEQ, []):
            all_ranseq.append((pck_file.name, obj))

    # Print size distribution
    sizes = [obj["size"] for _, obj in all_ranseq]
    if sizes:
        print(f"\n=== {game.upper()} 0x0D Object Size Distribution ===")
        print(f"Count: {len(sizes)}, Min: {min(sizes)}, Max: {max(sizes)}, Avg: {sum(sizes)//len(sizes)}")

    # Group by size for pattern analysis
    size_groups = defaultdict(int)
    for s in sizes:
        bucket = (s // 10) * 10
        size_groups[bucket] += 1
    print("Size buckets:")
    for bucket in sorted(size_groups.keys())[:20]:
        print(f"  {bucket}-{bucket+9}: {size_groups[bucket]}")

    # Dump a few smallest and a few medium-sized objects
    sorted_by_size = sorted(all_ranseq, key=lambda x: x[1]["size"])

    # Pick: smallest, a medium one, and one with many items
    samples = []
    if sorted_by_size:
        samples.append(("SMALLEST", sorted_by_size[0]))
        mid = len(sorted_by_size) // 2
        samples.append(("MEDIUM", sorted_by_size[mid]))
        # Find one with a known segment ID reference
        for fname, obj in sorted_by_size:
            data = obj["data"]
            # Look for segment ID references
            seg_refs = 0
            for sid in list(all_segment_ids)[:100]:
                if struct.pack("<I", sid) in data:
                    seg_refs += 1
            if seg_refs >= 2:
                samples.append(("MULTI-SEG-REF", (fname, obj)))
                break

    # Dump last N bytes of a few objects to see playlist structure
    print(f"\n=== Raw Dumps (last 200 bytes of each) ===")
    dumped = 0
    for label, (fname, obj) in samples:
        if dumped >= max_dump:
            break
        data = obj["data"]
        print(f"\n--- {label}: File={fname}, ObjID={obj['id']}, Size={obj['size']} ---")

        # Show first 40 bytes (obj_id + flags/params header)
        print(f"  First 40 bytes:")
        print(hex_dump(data[:40], 0))

        # Show last 200 bytes
        tail_start = max(0, len(data) - 200)
        print(f"  Last {len(data) - tail_start} bytes (from offset {tail_start}):")
        print(hex_dump(data[tail_start:], tail_start))

        # Try to find segment IDs in the data
        seg_refs_found = []
        for sid in all_segment_ids:
            sid_bytes = struct.pack("<I", sid)
            idx = data.find(sid_bytes)
            while idx != -1:
                seg_refs_found.append((idx, sid))
                idx = data.find(sid_bytes, idx + 1)

        if seg_refs_found:
            seg_refs_found.sort()
            print(f"  Segment ID references found ({len(seg_refs_found)}):")
            for idx, sid in seg_refs_found[:10]:
                # Show context around the reference
                ctx_start = max(0, idx - 4)
                ctx_end = min(len(data), idx + 30)
                ctx = data[ctx_start:ctx_end]
                print(f"    offset={idx}, segID={sid}")
                print(f"    context: {' '.join(f'{b:02x}' for b in ctx)}")

        dumped += 1


if __name__ == "__main__":
    main()
