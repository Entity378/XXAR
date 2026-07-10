import struct
from dataclasses import dataclass, field

from src.core.logger import get_logger

logger = get_logger(__name__)

HIRC_TYPE_MUSIC_SEGMENT = 0x0A
HIRC_TYPE_MUSIC_TRACK = 0x0B
END_MARKER_ID = 0x5BBBD648

VOLUME_PROP_ID = 0x00

# Timings that differ by less than this slack count as equal, absorbing sub-ms rounding.
# It stays far below the hundreds-of-ms gap that marks a loop-with-tail segment.
_CONCAT_TOLERANCE_MS = 2.0

# AkTrackSrcInfo layout (44 bytes per item).
# Fields: trackID(4) + sourceID(4) + eventID(4) + fPlayAt(8) + fBeginTrimOffset(8) + fEndTrimOffset(8) + fSrcDuration(8).
_TRACK_SRC_INFO_SIZE = 44
_TRACK_SRC_PLAY_AT_OFFSET_IN_ITEM = 12   # offset of fPlayAt within a playlist item
_TRACK_SRC_DURATION_OFFSET_IN_ITEM = 36  # offset of fSrcDuration within a playlist item

# AkBankSourceData layout (14 bytes per source).
# Fields: pluginID(4) + streamType(1) + sourceID(4) + mediaSize(4) + sourceBits(1).
_SOURCE_DATA_SIZE = 14
_SOURCE_ID_OFFSET_IN_SOURCE = 5  # after pluginID(4) + streamType(1)


@dataclass
class TrackPatchInfo:
    source_id: int
    fSrcDuration_offset: int
    fPlayAt_offset: int
    clear_region_offset: int  # eventID offset; eventID and trims are cleared, fPlayAt between them is kept


@dataclass
class VolumePatchInfo:
    source_id: int
    prop_bundle_cProps_offset: int   # absolute offset of the cProps byte
    volume_value_offset: int         # absolute offset of the volume float (overwrite) or values-array insertion point
    has_existing_volume: bool        # True = overwrite in-place, False = need insert
    object_size_field_offset: int = 0  # absolute offset of the enclosing MusicTrack object's u32 size field
    cProps: int = 0                  # current property count in this AkPropBundle
    ids_start_offset: int = 0        # absolute offset where the prop-id array begins (cProps_offset + 1)


@dataclass
class SegmentPatchInfo:
    fDuration_offset: int
    end_marker_fPos_offset: int
    associated_source_ids: set = field(default_factory=set)
    member_clips: list = field(default_factory=list)  # TrackPatchInfo of the segment's clips (for timeline re-timing)


@dataclass
class BankPatchTargets:
    tracks: list = field(default_factory=list)
    segments: list = field(default_factory=list)
    volume_patches: list = field(default_factory=list)


def scan_bank_for_patch_targets(content, source_ids):
    # Find MusicTrack/MusicSegment HIRC objects referencing source_ids; return absolute duration-field offsets.
    if not source_ids:
        return BankPatchTargets()

    source_id_set = set(int(s) for s in source_ids)
    all_tracks = []
    all_segments = []
    all_volume = []

    for hirc_data_start, hirc_data_size in _find_hirc_sections(content):
        section_end = hirc_data_start + hirc_data_size
        num_objects = struct.unpack_from("<I", content, hirc_data_start)[0]
        obj_pos = hirc_data_start + 4

        section_tracks = []
        track_obj_to_sources = {}  # track_obj_id -> set of its source_ids
        track_obj_to_clips = {}    # track_obj_id -> list of its TrackPatchInfo clips
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
                    track_obj_id, patches, vol_patches = result
                    section_tracks.extend(patches)
                    all_volume.extend(vol_patches)
                    track_obj_to_sources[track_obj_id] = {
                        p.source_id for p in patches
                    }
                    track_obj_to_clips[track_obj_id] = list(patches)

            elif obj_type == HIRC_TYPE_MUSIC_SEGMENT:
                seg_info = _parse_music_segment(content, obj_data_start, obj_size)
                if seg_info is not None:
                    section_segment_candidates.append(
                        (obj_data_start, obj_size, seg_info)
                    )

            obj_pos = obj_data_start + obj_size

        if not section_tracks:
            continue

        # Link segments to tracks: check if the MusicNodeParams region (before fDuration) contains any matching track obj_id bytes.

        track_id_bytes_map = {
            struct.pack("<I", tid): tid for tid in track_obj_to_sources
        }

        for seg_data_start, seg_size, seg_info in section_segment_candidates:
            # Restrict search to MusicNodeParams (before fDuration).
            node_params_end = seg_info.fDuration_offset - seg_data_start
            seg_node_data = content[seg_data_start : seg_data_start + node_params_end]
            associated = set()
            member_clips = []
            for tid_bytes, tid in track_id_bytes_map.items():
                if tid_bytes in seg_node_data:
                    associated.update(track_obj_to_sources.get(tid, set()))
                    member_clips.extend(track_obj_to_clips.get(tid, []))
            if associated:
                seg_info.associated_source_ids = associated
                seg_info.member_clips = member_clips
                all_segments.append(seg_info)

        all_tracks.extend(section_tracks)

    return BankPatchTargets(
        tracks=all_tracks, segments=all_segments, volume_patches=all_volume,
    )


def apply_volume_patches(content, volume_patches, volume_db_by_source):
    # In-place overwrite only: tracks without an existing Volume property in their AkPropBundle are skipped to avoid shifting offsets/corrupting.
    patched = 0
    skipped = 0

    for vp in volume_patches:
        db_val = volume_db_by_source.get(vp.source_id)
        if db_val is None:
            continue
        if not vp.has_existing_volume:
            skipped += 1
            continue
        vol_bytes = struct.pack("<f", float(db_val))
        content[vp.volume_value_offset : vp.volume_value_offset + 4] = vol_bytes
        patched += 1

    if skipped:
        logger.info(f"[HIRC Patch] Volume: skipped {skipped} track(s) without existing volume property")

    return {"patched": patched, "inserted": 0, "total_shift": 0}


def apply_volume_inserts(content, volume_patches, volume_db_by_source):
    # Insert a Volume (0x00) prop into MusicTracks that lack one, growing an isolated bnk buffer.
    # 0x00 sorts to the front so the bundle stays ascending, and only the object size field is bumped.
    inserts = {}
    for vp in volume_patches:
        if vp.has_existing_volume:
            continue
        db_val = volume_db_by_source.get(vp.source_id)
        if db_val is None:
            continue
        # One insert per bundle even if several sources share the same MusicTrack.
        inserts.setdefault(vp.prop_bundle_cProps_offset, (vp, db_val))

    inserted = 0
    for cProps_offset in sorted(inserts.keys(), reverse=True):
        vp, db_val = inserts[cProps_offset]
        values_start = vp.ids_start_offset + vp.cProps
        # Insert the value then the id, both at the front of their arrays.
        # Doing the higher offset first keeps the lower insertion point valid.
        content[values_start:values_start] = struct.pack("<f", float(db_val))
        content[vp.ids_start_offset:vp.ids_start_offset] = bytes([VOLUME_PROP_ID])
        content[cProps_offset] = vp.cProps + 1
        if vp.object_size_field_offset:
            old_size = struct.unpack_from("<I", content, vp.object_size_field_offset)[0]
            struct.pack_into("<I", content, vp.object_size_field_offset, old_size + 5)
        inserted += 1

    if inserted:
        logger.info(f"[HIRC Patch] Volume: inserted {inserted} new volume property(ies)")

    return {"patched": 0, "inserted": inserted, "total_shift": inserted * 5}


def apply_duration_patches(content, targets, duration_ms_by_source):
    patched_offsets = 0
    patched_source_ids = set()

    # Snapshot each clip's original fPlayAt and fSrcDuration before pass 1 overwrites them.
    original_timings = {}  # clear_region_offset -> (old_fPlayAt, old_fSrcDuration)
    for track in targets.tracks:
        if track.source_id in duration_ms_by_source:
            original_timings[track.clear_region_offset] = (
                struct.unpack_from("<d", content, track.fPlayAt_offset)[0],
                struct.unpack_from("<d", content, track.fSrcDuration_offset)[0],
            )

    # Pass 1 clears eventID and trims and sets fSrcDuration, but preserves fPlayAt.
    # Zeroing fPlayAt collapses intro+loop clips onto t=0 and makes them overlap.
    event_id_zeros = b"\x00\x00\x00\x00"
    trim_zeros = b"\x00" * 16
    for track in targets.tracks:
        new_duration = duration_ms_by_source.get(track.source_id)
        if new_duration is None:
            continue
        clear_offset = track.clear_region_offset
        event_id = slice(clear_offset, clear_offset + 4)
        trims = slice(clear_offset + 12, clear_offset + 28)
        src_duration = slice(track.fSrcDuration_offset, track.fSrcDuration_offset + 8)
        duration_bytes = struct.pack("<d", float(new_duration))
        if (content[event_id] == event_id_zeros
                and content[trims] == trim_zeros
                and content[src_duration] == duration_bytes):
            continue
        content[event_id] = event_id_zeros
        content[trims] = trim_zeros
        content[src_duration] = duration_bytes
        patched_offsets += 1
        patched_source_ids.add(track.source_id)

    # Pass 2 re-times clips and recomputes duration only for clean concatenations.
    # Loop-with-tail segments keep their musical fDuration and every fPlayAt untouched.
    for segment in targets.segments:
        clip_timings = []  # (clip, old_fPlayAt, old_duration, new_duration)
        for clip in segment.member_clips:
            new_duration = duration_ms_by_source.get(clip.source_id)
            if new_duration is None or clip.clear_region_offset not in original_timings:
                continue
            old_play_at, old_duration = original_timings[clip.clear_region_offset]
            clip_timings.append((clip, old_play_at, old_duration, float(new_duration)))
        if not clip_timings:
            continue

        old_timeline_end = max(play_at + duration for _, play_at, duration, _ in clip_timings)
        old_segment_duration = struct.unpack_from("<d", content, segment.fDuration_offset)[0]
        if abs(old_segment_duration - old_timeline_end) > _CONCAT_TOLERANCE_MS:
            continue  # loop-with-tail: leave untouched

        segment_changed = False
        new_clip_ends = []
        for clip, old_play_at, _, new_duration in clip_timings:
            # Shift this clip by the total growth of the clips that finish before it starts.
            shift = sum(
                other_new - other_old
                for other, other_at, other_old, other_new in clip_timings
                if other is not clip and other_at + other_old <= old_play_at + _CONCAT_TOLERANCE_MS
            )
            new_play_at = old_play_at + shift
            if abs(new_play_at - old_play_at) > 1e-6:
                struct.pack_into("<d", content, clip.fPlayAt_offset, new_play_at)
                patched_offsets += 1
                segment_changed = True
            new_clip_ends.append(new_play_at + new_duration)

        new_segment_duration = max(new_clip_ends)
        old_marker_pos = struct.unpack_from("<d", content, segment.end_marker_fPos_offset)[0]
        if abs(new_segment_duration - old_segment_duration) > 1e-6 or abs(new_segment_duration - old_marker_pos) > 1e-6:
            struct.pack_into("<d", content, segment.fDuration_offset, new_segment_duration)
            struct.pack_into("<d", content, segment.end_marker_fPos_offset, new_segment_duration)
            patched_offsets += 1
            segment_changed = True

        if segment_changed:
            patched_source_ids.update(clip.source_id for clip, *_ in clip_timings)

    return {
        "patched_offsets": patched_offsets,
        "patched_source_ids": patched_source_ids,
    }


# Internal helpers


def _adjust_hirc_sizes(content, offset_inside_object, delta):
    # Walk back to the enclosing HIRC header, bump its section size and the containing object's size by `delta`.
    search_start = max(0, offset_inside_object - 0x100000)
    chunk = bytes(content[search_start : offset_inside_object])
    hirc_pos = chunk.rfind(b"HIRC")
    if hirc_pos == -1:
        return
    hirc_abs = search_start + hirc_pos

    # HIRC section: "HIRC"(4) + section_size(u32) + numObjects(u32) + objects...
    section_size_off = hirc_abs + 4
    old_section_size = struct.unpack_from("<I", content, section_size_off)[0]
    struct.pack_into("<I", content, section_size_off, old_section_size + delta)

    # Find the object containing offset_inside_object.
    obj_pos = hirc_abs + 8 + 4  # skip HIRC(4) + section_size(4) + numObjects(4)
    section_end = hirc_abs + 8 + old_section_size
    while obj_pos + 5 <= section_end:
        obj_size_off = obj_pos + 1
        obj_size = struct.unpack_from("<I", content, obj_size_off)[0]
        obj_data_start = obj_pos + 5
        obj_data_end = obj_data_start + obj_size
        if obj_data_start <= offset_inside_object < obj_data_end:
            struct.pack_into("<I", content, obj_size_off, obj_size + delta)
            return
        obj_pos = obj_data_end


def _find_hirc_sections(content):
    # Yield (data_start, data_size) for each HIRC section in raw bytes.
    # data_start points to the first byte after the 8-byte header (HIRC + u32 size), i.e. the numItems u32.
    # data_size is the section payload size.
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
    # Returns (obj_id, [TrackPatchInfo], [VolumePatchInfo]) when the track references any id in `source_ids`, else None.
    end = data_start + obj_size
    if data_start + 9 > end:
        return None

    obj_id = struct.unpack_from("<I", content, data_start)[0]
    # flags: 1 byte at d+4
    num_sources = struct.unpack_from("<I", content, data_start + 5)[0]
    if num_sources > 100:
        return None

    p = data_start + 9
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
                    fPlayAt_offset=p + _TRACK_SRC_PLAY_AT_OFFSET_IN_ITEM,
                    clear_region_offset=p + 8,  # eventID(4)+fPlayAt(8)+fBeginTrim(8)+fEndTrim(8) = 28 bytes
                )
            )
        p += _TRACK_SRC_INFO_SIZE

    if not patches:
        return None

    # parse AkPropBundle for volume
    try:
        object_size_field_offset = data_start - 4  # u32 size field precedes the object data
        volume_patches = _parse_volume_from_track(
            content, p, end, patches, object_size_field_offset
        )
    except Exception:
        # If parsing fails (unexpected layout), skip volume for this track.
        volume_patches = []
    return (obj_id, patches, volume_patches)


def _parse_volume_from_track(content, p, end, track_patches, object_size_field_offset=0):
    # Post-playlist section of a MusicTrack; walks NodeBaseParams to find the AkPropBundle Volume entry.
    # Layout reference: parse_hirc_examples.py.
    if p + 8 > end:
        return []

    # numSubTrack + numClipAutomation
    p += 4  # numSubTrack
    num_clip = struct.unpack_from("<I", content, p)[0]
    p += 4
    if num_clip > 200:
        return []

    # Skip clip automation items
    for _ in range(num_clip):
        if p + 12 > end:
            return []
        p += 8  # uClipIndex(4) + eAutoType(4)
        num_points = struct.unpack_from("<I", content, p)[0]
        p += 4
        if num_points > 10000:
            return []
        p += 12 * num_points  # AkRTPCGraphPoint: from(f32) + to(f32) + interp(u32)

    # eTrackType(4) + bIsTransitionEnabled(1)
    if p + 5 > end:
        return []
    p += 4  # eTrackType
    p += 1  # bIsTransitionEnabled

    # NodeBaseParams (Music variant)
    if p + 2 > end:
        return []
    bIsOverrideParentFX = content[p]
    p += 1
    uNumFx = content[p]
    p += 1

    if uNumFx > 0:
        if p + 1 > end:
            return []
        p += 1  # bitsMainFXBypass
        p += 6 * uNumFx  # FXChunk: fxIndex(1) + fxID(4) + bIsShareSet(1)

    # directParentID(4) + byBitVector(1)
    if p + 5 > end:
        return []
    p += 4  # directParentID
    p += 1  # byBitVector

    # AkPropBundle
    if p + 1 > end:
        return []
    cProps = content[p]
    cProps_offset = p
    p += 1

    if cProps > 50:
        return []
    if p + cProps + cProps * 4 > end:
        return []

    # Read property IDs
    ids_start_offset = p  # start of the prop-id array (= cProps_offset + 1)
    prop_ids = list(content[p : p + cProps])
    p += cProps  # now at start of values array

    # Look for Volume (property ID 0x00)
    volume_value_offset = None
    has_existing = False
    for i, pid in enumerate(prop_ids):
        if pid == VOLUME_PROP_ID:
            volume_value_offset = p + i * 4
            has_existing = True
            break

    if not has_existing:
        # Volume sorts to the front, so its value goes at the start of the values array.
        volume_value_offset = p

    # Create one VolumePatchInfo per matched source in this track
    results = []
    for tp in track_patches:
        results.append(
            VolumePatchInfo(
                source_id=tp.source_id,
                prop_bundle_cProps_offset=cProps_offset,
                volume_value_offset=volume_value_offset,
                has_existing_volume=has_existing,
                object_size_field_offset=object_size_field_offset,
                cProps=cProps,
                ids_start_offset=ids_start_offset,
            )
        )
    return results


def _parse_music_segment(content, data_start, obj_size):
    # Parse a MusicSegment (0x0A) HIRC object.
    # Uses marker-scanning heuristic to locate fDuration and the end marker's fPosition.
    # Returns SegmentPatchInfo or None.
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
