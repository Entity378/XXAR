# Read-only analysis: scan MusicTrack (0x0B) AkPropBundles in real game banks.
# Answers two questions before we attempt Volume insertion:
#   1) How many MusicTracks already have a Volume (0x00) prop vs. how many lack it?
#   2) Are AkPropBundle prop-id arrays always sorted ascending? (validates "insert 0x00 at front")
import struct
import sys
from collections import Counter
from pathlib import Path

HIRC_TYPE_MUSIC_TRACK = 0x0B
VOLUME_PROP_ID = 0x00
_SOURCE_DATA_SIZE = 14
_SOURCE_ID_OFFSET_IN_SOURCE = 5
_TRACK_SRC_INFO_SIZE = 44

PN = {
    0x00: 'Volume', 0x01: 'LFE', 0x02: 'Pitch', 0x03: 'LPF', 0x04: 'HPF',
    0x05: 'BusVolume', 0x06: 'MakeUpGain', 0x07: 'Priority',
    0x08: 'PriorityDistOff', 0x0B: 'InitialDelay', 0x0D: 'TransitionTime',
    0x0E: 'Probability',
}


def find_hirc_sections(content):
    flen = len(content)
    pos = -1
    while True:
        pos = content.find(b"HIRC", pos + 1)
        if pos == -1:
            break
        if pos + 12 > flen:
            break
        section_size = struct.unpack_from("<I", content, pos + 4)[0]
        if section_size < 4 or pos + 8 + section_size > flen:
            continue
        yield pos + 8, section_size


def parse_track_propbundle(content, data_start, obj_size):
    # Mirror hirc_patcher._parse_music_track + _parse_volume_from_track.
    # Returns (prop_ids, reason). On success reason is None; on skip prop_ids is None
    # and reason tags the stage that derailed, plus the byte offset reached.
    end = data_start + obj_size
    if data_start + 9 > end:
        return None, "tiny_obj"
    num_sources = struct.unpack_from("<I", content, data_start + 5)[0]
    if num_sources > 100:
        return None, "num_sources>100"
    p = data_start + 9
    source_end = p + num_sources * _SOURCE_DATA_SIZE
    if source_end > end:
        return None, "sources_overflow"
    p = source_end
    if p + 4 > end:
        return None, "no_numPlaylist"
    num_playlist = struct.unpack_from("<I", content, p)[0]
    p += 4
    if num_playlist > 100:
        return None, "num_playlist>100@%d" % (p - data_start)
    items_end = p + num_playlist * _TRACK_SRC_INFO_SIZE
    if items_end > end:
        return None, "playlist_overflow"
    p = items_end

    if p + 8 > end:
        return None, "no_subtrack"
    p += 4  # numSubTrack
    num_clip = struct.unpack_from("<I", content, p)[0]
    p += 4
    if num_clip > 200:
        return None, "num_clip>200@%d" % (p - data_start)
    for _ in range(num_clip):
        if p + 12 > end:
            return None, "clip_overflow"
        p += 8
        num_points = struct.unpack_from("<I", content, p)[0]
        p += 4
        if num_points > 10000:
            return None, "num_points>10000"
        p += 12 * num_points

    if p + 5 > end:
        return None, "no_trackType"
    p += 4  # eTrackType
    p += 1  # bIsTransitionEnabled

    if p + 2 > end:
        return None, "no_nodeBase"
    p += 1  # bIsOverrideParentFX
    uNumFx = content[p]
    p += 1
    if uNumFx > 0:
        if p + 1 > end:
            return None, "no_fxBypass"
        p += 1
        p += 6 * uNumFx

    if p + 5 > end:
        return None, "no_directParent"
    p += 4  # directParentID
    p += 1  # byBitVector

    if p + 1 > end:
        return None, "no_cProps"
    cProps = content[p]
    p += 1
    if cProps > 50:
        return None, "cProps>50(=%d)@%d" % (cProps, p - 1 - data_start)
    if p + cProps + cProps * 4 > end:
        return None, "propbundle_overflow(cProps=%d)" % cProps
    prop_ids = list(content[p:p + cProps])
    # Sanity: after the bundle we expect RangedModifiers (1 byte count) to fit too.
    return prop_ids, None


def scan_pck(path, stats):
    content = path.read_bytes()
    for hirc_start, hirc_size in find_hirc_sections(content):
        section_end = hirc_start + hirc_size
        num_objects = struct.unpack_from("<I", content, hirc_start)[0]
        obj_pos = hirc_start + 4
        for _ in range(num_objects):
            if obj_pos + 5 > section_end:
                break
            obj_type = content[obj_pos]
            obj_size = struct.unpack_from("<I", content, obj_pos + 1)[0]
            obj_data_start = obj_pos + 5
            if obj_data_start + obj_size > len(content):
                break
            if obj_type == HIRC_TYPE_MUSIC_TRACK:
                prop_ids, reason = parse_track_propbundle(content, obj_data_start, obj_size)
                if prop_ids is not None:
                    stats['tracks'] += 1
                    if VOLUME_PROP_ID in prop_ids:
                        stats['with_volume'] += 1
                    else:
                        stats['without_volume'] += 1
                    if prop_ids != sorted(prop_ids):
                        stats['unsorted'] += 1
                        stats['unsorted_examples'].append(prop_ids)
                    stats['cprops_hist'][len(prop_ids)] += 1
                    for pid in prop_ids:
                        stats['prop_hist'][pid] += 1
                else:
                    stats['unparsed'] += 1
                    reason_key = reason.split('@')[0].split('(')[0]
                    stats['skip_reasons'][reason_key] += 1
                    ns = struct.unpack_from("<I", content, obj_data_start + 5)[0]
                    npl = struct.unpack_from("<I", content, obj_data_start + 9)[0] if ns == 0 else -1
                    if ns == 0:
                        stats['skip_no_sources'] += 1
                    if ns == 0 and npl == 0:
                        stats['skip_no_sources_no_playlist'] += 1
                    bucket = stats['skip_examples'].setdefault(reason_key, [])
                    if len(bucket) < 3:
                        raw = bytes(content[obj_data_start:obj_data_start + min(obj_size, 160)])
                        bucket.append((obj_size, reason, raw.hex()))
                    if ns > 0 and len(stats['skip_with_sources']) < 6:
                        raw = bytes(content[obj_data_start:obj_data_start + min(obj_size, 200)])
                        stats['skip_with_sources'].append((obj_size, ns, reason, raw.hex()))
            obj_pos = obj_data_start + obj_size


def main():
    args = sys.argv[1:]
    if not args:
        print("Usage: python analyze_musictrack_volume.py <pck_or_dir> [more...]")
        sys.exit(1)

    targets = []
    for a in args:
        p = Path(a)
        if p.is_dir():
            targets.extend(sorted(p.glob("Music*.pck")))
        else:
            targets.append(p)

    stats = {
        'tracks': 0, 'with_volume': 0, 'without_volume': 0,
        'unsorted': 0, 'unparsed': 0,
        'unsorted_examples': [], 'cprops_hist': Counter(), 'prop_hist': Counter(),
        'skip_reasons': Counter(), 'skip_examples': {},
        'skip_no_sources': 0, 'skip_no_sources_no_playlist': 0,
        'skip_with_sources': [],
    }

    for t in targets:
        if not t.exists():
            print(f"  skip (missing): {t}")
            continue
        print(f"scanning {t.name} ({t.stat().st_size/1e6:.0f} MB)...")
        scan_pck(t, stats)

    print("\n==== RESULTS ====")
    print(f"MusicTracks parsed:      {stats['tracks']}")
    print(f"  with Volume (0x00):    {stats['with_volume']}")
    print(f"  WITHOUT Volume:        {stats['without_volume']}")
    print(f"  unparsed (skipped):    {stats['unparsed']}")
    print(f"AkPropBundle unsorted:   {stats['unsorted']}  <-- must be 0 to trust front-insert as 'sorted'")
    if stats['unsorted_examples']:
        print("  unsorted examples (first 5):")
        for ex in stats['unsorted_examples'][:5]:
            print("    " + ", ".join(PN.get(i, hex(i)) for i in ex))
    print("cProps histogram (count -> #tracks):")
    for k in sorted(stats['cprops_hist']):
        print(f"    {k}: {stats['cprops_hist'][k]}")
    print("property frequency:")
    for pid, cnt in stats['prop_hist'].most_common():
        print(f"    {PN.get(pid, hex(pid))}: {cnt}")
    print("\n==== SKIP REASONS (the unparsed) ====")
    for reason, cnt in stats['skip_reasons'].most_common():
        print(f"  {reason}: {cnt}")
    print(f"  of which numSources==0:            {stats['skip_no_sources']}")
    print(f"  of which numSources==0 & numPlaylist==0: {stats['skip_no_sources_no_playlist']}")
    print("\n==== SKIPPED TRACKS *WITH* SOURCES (the only real concern) ====")
    if not stats['skip_with_sources']:
        print("  (none — every skipped track had zero sources)")
    for obj_size, ns, full_reason, hexdata in stats['skip_with_sources']:
        print(f"    obj_size={obj_size} numSources={ns} reason={full_reason}")
        print(f"    {hexdata}")


if __name__ == "__main__":
    main()
