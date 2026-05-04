# Scan PCK/BNK files for MusicRanSeqCntr (0x0D) intro+loop patterns.
import struct
import sys
from pathlib import Path
from collections import defaultdict

HIRC_TYPE_MUSIC_SEGMENT = 0x0A
HIRC_TYPE_MUSIC_TRACK = 0x0B
HIRC_TYPE_MUSIC_RANSEQ = 0x0D

# PlaylistItem: 30 bytes each.
# Layout: segmentID(4) + playlistItemID(4) + numChildren(4) + eRSType(4) + Loop(2) + LoopMin(2) + LoopMax(2) + weight(4) + wAvoidRepeatCount(2) + isUsingWeight(1) + isShuffle(1).
PLAYLIST_ITEM_SIZE = 30


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


def parse_playlist(data, all_segment_ids):
    # Parse the playlist tree at the end of a 0x0D object.
    # Try different item counts and validate tree structure.
    size = len(data)

    for num_items in range(2, 60):
        block_size = 4 + num_items * PLAYLIST_ITEM_SIZE
        if block_size > size - 4:
            break
        offset = size - num_items * PLAYLIST_ITEM_SIZE - 4

        check_num = struct.unpack_from("<I", data, offset)[0]
        if check_num != num_items:
            continue

        p = offset + 4
        items = []
        valid = True
        for _ in range(num_items):
            seg_id = struct.unpack_from("<I", data, p)[0]
            item_id = struct.unpack_from("<I", data, p + 4)[0]
            num_children = struct.unpack_from("<I", data, p + 8)[0]
            rs_type = struct.unpack_from("<I", data, p + 12)[0]
            loop = struct.unpack_from("<h", data, p + 16)[0]  # signed
            loop_min = struct.unpack_from("<h", data, p + 18)[0]
            loop_max = struct.unpack_from("<h", data, p + 20)[0]
            weight = struct.unpack_from("<I", data, p + 22)[0]

            if num_children > 50:
                valid = False
                break

            items.append({
                "seg_id": seg_id,
                "item_id": item_id,
                "children": num_children,
                "rs_type": rs_type,
                "loop": loop,
                "loop_min": loop_min,
                "loop_max": loop_max,
                "weight": weight,
            })
            p += PLAYLIST_ITEM_SIZE

        if not valid:
            continue

        # Validate tree: sum of children + 1 (root) == num_items
        total_children = sum(it["children"] for it in items)
        if total_children + 1 != num_items:
            continue

        # DFS walk validation
        stack = [items[0]["children"]]
        tree_valid = True
        for it in items[1:]:
            if not stack:
                tree_valid = False
                break
            stack[-1] -= 1
            if stack[-1] == 0:
                stack.pop()
            if it["children"] > 0:
                stack.append(it["children"])

        if tree_valid and not stack:
            # Extra validation: leaf segment IDs should exist
            leaves = [it for it in items if it["children"] == 0]
            if all_segment_ids:
                matching = sum(1 for l in leaves if l["seg_id"] in all_segment_ids)
                if matching == 0 and len(leaves) > 0:
                    continue
            return {"offset": offset, "items": items}

    return None


def classify_playlist(items):
    # Classify the playlist pattern based on loop values.
    # Returns a tuple of (pattern_name, intro_segments, loop_segments).
    leaves = [it for it in items if it["children"] == 0]
    root = items[0]

    play_once = [l for l in leaves if l["loop"] == 1]
    infinite = [l for l in leaves if l["loop"] == 0]

    if len(leaves) == 1:
        if leaves[0]["loop"] == 0:
            return ("single-loop", [], [leaves[0]])
        else:
            return ("single-play", [leaves[0]], [])

    if play_once and infinite:
        # Check if intro comes before loop in tree order
        first_inf_idx = next(
            i for i, l in enumerate(leaves) if l["loop"] == 0
        )
        intros = leaves[:first_inf_idx]
        loops = leaves[first_inf_idx:]
        if intros and all(l["loop"] == 1 for l in intros):
            return ("intro+loop", intros, loops)
        return ("mixed", play_once, infinite)

    if infinite and not play_once:
        return ("all-infinite", [], infinite)

    if play_once and not infinite:
        if root["loop"] == 0:
            return ("sequence-looping", play_once, [])
        return ("sequence-finite", play_once, [])

    return ("other", play_once, infinite)


def main():
    game = sys.argv[1] if len(sys.argv) > 1 else "zzz"

    paths = {
        "zzz": Path(r"C:\Program Files\HoYoPlay\games\ZenlessZoneZero Game\ZenlessZoneZero_Data\StreamingAssets\Audio\Windows\Full"),
        "gi": Path(r"C:\Program Files\HoYoPlay\games\Genshin Impact game\GenshinImpact_Data\StreamingAssets\AudioAssets"),
        "hsr": Path(r"C:\Program Files\HoYoPlay\games\Star Rail Games\StarRail_Data\StreamingAssets\Audio\AudioPackage\Windows"),
    }
    audio_root = paths.get(game)
    if not audio_root or not audio_root.exists():
        print(f"Path not found: {audio_root}")
        return

    # Collect all segment IDs
    all_segment_ids = set()
    bank_files = sorted(audio_root.rglob("*.pck"))
    all_ranseq = []

    for pck_file in bank_files:
        objects = scan_file(pck_file)
        for obj in objects.get(HIRC_TYPE_MUSIC_SEGMENT, []):
            all_segment_ids.add(obj["id"])
        for obj in objects.get(HIRC_TYPE_MUSIC_RANSEQ, []):
            all_ranseq.append((pck_file.name, obj))

    total = len(all_ranseq)
    parsed = 0
    pattern_counts = defaultdict(int)
    examples = defaultdict(list)

    for fname, obj in all_ranseq:
        result = parse_playlist(obj["data"], all_segment_ids)
        if result is None:
            continue

        parsed += 1
        items = result["items"]
        pattern, intros, loops = classify_playlist(items)
        pattern_counts[pattern] += 1

        if len(examples[pattern]) < 5:
            leaves = [it for it in items if it["children"] == 0]
            detail = []
            for it in items:
                role = "LEAF" if it["children"] == 0 else "NODE"
                seg = f"seg={it['seg_id']}" if it["seg_id"] != 0 else "seg=0(root)"
                lp = "INF" if it["loop"] == 0 else str(it["loop"])
                detail.append(
                    f"  [{role}] {seg}, loop={lp}, ch={it['children']}, rsType={it['rs_type']}"
                )
            examples[pattern].append({
                "file": fname,
                "obj_id": obj["id"],
                "num_items": len(items),
                "num_leaves": len(leaves),
                "intros": [i["seg_id"] for i in intros],
                "loops": [l["seg_id"] for l in loops],
                "detail": "\n".join(detail),
            })

    print(f"\n=== {game.upper()} MusicPlaylistContainer (0x0D) Analysis ===")
    print(f"Total 0x0D objects: {total}")
    print(f"Successfully parsed: {parsed}")
    print(f"Parse failures: {total - parsed}")
    print(f"\nPattern breakdown:")
    for pattern, count in sorted(pattern_counts.items(), key=lambda x: -x[1]):
        print(f"  {pattern}: {count}")

    for pattern in ["intro+loop", "mixed", "sequence-looping", "all-infinite", "other"]:
        if pattern in examples:
            print(f"\n--- {pattern} examples ---")
            for ex in examples[pattern]:
                print(f"\nFile: {ex['file']}, ObjID: {ex['obj_id']}, Items: {ex['num_items']} ({ex['num_leaves']} leaves)")
                if ex["intros"]:
                    print(f"  Intro segments: {ex['intros']}")
                if ex["loops"]:
                    print(f"  Loop segments: {ex['loops']}")
                print(ex["detail"])


if __name__ == "__main__":
    main()
