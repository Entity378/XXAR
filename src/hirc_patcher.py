import struct
from dataclasses import dataclass, field

HIRC_TYPE_MUSIC_SEGMENT = 0x0A
HIRC_TYPE_MUSIC_TRACK = 0x0B
END_MARKER_ID = 0x5BBBD648

# AkTrackSrcInfo layout (44 bytes per item):
#   trackID(4) + sourceID(4) + eventID(4) + fPlayAt(8) + fBeginTrimOffset(8) + fEndTrimOffset(8) + fSrcDuration(8)
_TRACK_SRC_INFO_SIZE = 44
_TRACK_SRC_DURATION_OFFSET_IN_ITEM = 36  # offset of fSrcDuration within a playlist item

# AkBankSourceData layout (14 bytes per source):
#   pluginID(4) + streamType(1) + sourceID(4) + mediaSize(4) + sourceBits(1)
_SOURCE_DATA_SIZE = 14
_SOURCE_ID_OFFSET_IN_SOURCE = 5  # after pluginID(4) + streamType(1)


@dataclass
class TrackPatchInfo:
    source_id: int
    fSrcDuration_offset: int


@dataclass
class SegmentPatchInfo:
    fDuration_offset: int
    end_marker_fPos_offset: int
    associated_source_ids: set = field(default_factory=set)


@dataclass
class BankPatchTargets:
    tracks: list = field(default_factory=list)
    segments: list = field(default_factory=list)


def scan_bank_for_patch_targets(content, source_ids):
    """Scan a PCK/BNK file for MusicTrack and MusicSegment HIRC objects
    referencing the given WEM source IDs.

    Returns a BankPatchTargets with precise absolute file offsets for all
    duration fields that need patching.
    """
    if not source_ids:
        return BankPatchTargets()

    source_id_set = set(int(s) for s in source_ids)
    all_tracks = []
    all_segments = []

    for hirc_data_start, hirc_data_size in _find_hirc_sections(content):
        section_end = hirc_data_start + hirc_data_size
        num_objects = struct.unpack_from("<I", content, hirc_data_start)[0]
        obj_pos = hirc_data_start + 4

        section_tracks = []
        track_obj_to_sources = {}  # track_obj_id -> set of its source_ids
        section_segment_candidates = []

        for _ in range(num_objects):
            if obj_pos + 5 > section_end:
                break
            obj_type = content[obj_pos]
            obj_size = struct.unpack_from("<I", content, obj_pos + 1)[0]
            obj_data_start = obj_pos + 5
            if obj_data_start + obj_size > len(content):
                break

            if obj_type == HIRC_TYPE_MUSIC_TRACK:
                result = _parse_music_track(
                    content, obj_data_start, obj_size, source_id_set
                )
                if result is not None:
                    track_obj_id, patches = result
                    section_tracks.extend(patches)
                    track_obj_to_sources[track_obj_id] = {
                        p.source_id for p in patches
                    }

            elif obj_type == HIRC_TYPE_MUSIC_SEGMENT:
                seg_info = _parse_music_segment(content, obj_data_start, obj_size)
                if seg_info is not None:
                    section_segment_candidates.append(
                        (obj_data_start, obj_size, seg_info)
                    )

            obj_pos = obj_data_start + obj_size

        if not section_tracks:
            continue

        # Link segments to tracks: check if the MusicNodeParams region
        # (before fDuration) contains any matching track obj_id bytes.

        track_id_bytes_map = {
            struct.pack("<I", tid): tid for tid in track_obj_to_sources
        }

        for seg_data_start, seg_size, seg_info in section_segment_candidates:
            # Restrict search to MusicNodeParams (before fDuration).
            node_params_end = seg_info.fDuration_offset - seg_data_start
            seg_node_data = content[seg_data_start : seg_data_start + node_params_end]
            associated = set()
            for tid_bytes, tid in track_id_bytes_map.items():
                if tid_bytes in seg_node_data:
                    associated.update(track_obj_to_sources.get(tid, set()))
            if associated:
                seg_info.associated_source_ids = associated
                all_segments.append(seg_info)

        all_tracks.extend(section_tracks)

    return BankPatchTargets(tracks=all_tracks, segments=all_segments)


def apply_duration_patches(file_path, targets, duration_ms_by_source):
    """Write new duration values to the bank file at the offsets found by
    scan_bank_for_patch_targets.

    duration_ms_by_source: dict mapping source_id (int) -> duration in ms (float).

    Returns {"patched_offsets": int, "patched_source_ids": set}.
    """
    patched_offsets = 0
    patched_source_ids = set()

    with open(file_path, "r+b") as f:
        for track in targets.tracks:
            dur = duration_ms_by_source.get(track.source_id)
            if dur is None:
                continue
            dur_bytes = struct.pack("<d", float(dur))

            f.seek(track.fSrcDuration_offset)
            if f.read(8) == dur_bytes:
                continue

            f.seek(track.fSrcDuration_offset)
            f.write(dur_bytes)
            patched_offsets += 1
            patched_source_ids.add(track.source_id)

        for seg in targets.segments:
            seg_dur = max(
                (
                    duration_ms_by_source[sid]
                    for sid in seg.associated_source_ids
                    if sid in duration_ms_by_source
                ),
                default=0,
            )
            if seg_dur <= 0:
                continue
            dur_bytes = struct.pack("<d", float(seg_dur))

            f.seek(seg.fDuration_offset)
            existing_dur = f.read(8)
            f.seek(seg.end_marker_fPos_offset)
            existing_marker = f.read(8)

            if existing_dur == dur_bytes and existing_marker == dur_bytes:
                continue

            f.seek(seg.fDuration_offset)
            f.write(dur_bytes)
            f.seek(seg.end_marker_fPos_offset)
            f.write(dur_bytes)
            patched_offsets += 1
            patched_source_ids.update(seg.associated_source_ids)

    return {
        "patched_offsets": patched_offsets,
        "patched_source_ids": patched_source_ids,
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _find_hirc_sections(content):
    """Yield (data_start, data_size) for each HIRC section in raw bytes.

    data_start points to the first byte after the 8-byte header (HIRC + u32 size),
    i.e. the numItems u32.  data_size is the section payload size.
    """
    results = []
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
        results.append((pos + 8, section_size))
    return results


def _parse_music_track(content, data_start, obj_size, source_ids):
    """Parse a MusicTrack (0x0B) HIRC object.

    Returns (obj_id, [TrackPatchInfo, ...]) if the track references any source
    in *source_ids*, otherwise None.
    """
    d = data_start
    end = d + obj_size
    if d + 9 > end:
        return None

    obj_id = struct.unpack_from("<I", content, d)[0]
    # flags: 1 byte at d+4
    num_sources = struct.unpack_from("<I", content, d + 5)[0]
    if num_sources > 100:
        return None

    p = d + 9
    source_end = p + num_sources * _SOURCE_DATA_SIZE
    if source_end > end:
        return None

    track_source_ids = set()
    for _ in range(num_sources):
        sid = struct.unpack_from("<I", content, p + _SOURCE_ID_OFFSET_IN_SOURCE)[0]
        track_source_ids.add(sid)
        p += _SOURCE_DATA_SIZE

    if not (track_source_ids & source_ids):
        return None

    if p + 4 > end:
        return None
    num_playlist = struct.unpack_from("<I", content, p)[0]
    p += 4
    if num_playlist > 100:
        return None

    items_end = p + num_playlist * _TRACK_SRC_INFO_SIZE
    if items_end > end:
        return None

    patches = []
    for _ in range(num_playlist):
        pl_source_id = struct.unpack_from("<I", content, p + 4)[0]
        if pl_source_id in source_ids:
            patches.append(
                TrackPatchInfo(
                    source_id=pl_source_id,
                    fSrcDuration_offset=p + _TRACK_SRC_DURATION_OFFSET_IN_ITEM,
                )
            )
        p += _TRACK_SRC_INFO_SIZE

    if not patches:
        return None
    return (obj_id, patches)


def _parse_music_segment(content, data_start, obj_size):
    """Parse a MusicSegment (0x0A) HIRC object.

    Uses marker-scanning heuristic to locate fDuration and the end marker's
    fPosition.  Returns SegmentPatchInfo or None.
    """
    data = content[data_start : data_start + obj_size]

    for try_off in range(40, obj_size - 15):
        nm = struct.unpack_from("<I", data, try_off)[0]
        if nm < 1 or nm > 500:
            continue

        p = try_off + 4
        parsed_ok = True
        last_id = None
        last_fpos_data_offset = None

        for _ in range(nm):
            if p + 16 > obj_size:
                parsed_ok = False
                break
            marker_id = struct.unpack_from("<I", data, p)[0]
            nlen = struct.unpack_from("<I", data, p + 12)[0]
            if nlen > 500:
                parsed_ok = False
                break
            last_id = marker_id
            last_fpos_data_offset = p + 4  # fPosition is 4 bytes after marker start
            p += 16 + nlen

        if not parsed_ok or p != obj_size or last_id != END_MARKER_ID:
            continue

        return SegmentPatchInfo(
            fDuration_offset=data_start + try_off - 8,
            end_marker_fPos_offset=data_start + last_fpos_data_offset,
        )

    return None
