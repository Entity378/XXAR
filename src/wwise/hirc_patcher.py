import struct
from dataclasses import dataclass, field
from typing import Optional

from src.core.logger import get_logger

logger = get_logger(__name__)

HIRC_TYPE_MUSIC_SEGMENT = 0x0A
HIRC_TYPE_MUSIC_TRACK = 0x0B
ENTRY_MARKER_ID = 0x0298DF12
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
    entry_marker_fPos_offset: Optional[int] = None  # None when the segment has no entry cue
    associated_source_ids: set = field(default_factory=set)
    member_clips: list = field(default_factory=list)  # TrackPatchInfo of the segment's clips (for timeline re-timing)
    has_alternative_subtracks: bool = False


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
        track_obj_to_all_clips = {}
        track_obj_to_subtracks = {}
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
                parsed_track = _parse_track_clips(content, obj_data_start, obj_size)
                if parsed_track is not None:
                    track_obj_to_all_clips[parsed_track[0]] = parsed_track[2]
                    if parsed_track[3] + 4 <= obj_data_start + obj_size:
                        track_obj_to_subtracks[parsed_track[0]] = struct.unpack_from("<I", content, parsed_track[3])[0]
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
            for tid_bytes, tid in track_id_bytes_map.items():
                if tid_bytes in seg_node_data:
                    associated.update(track_obj_to_sources.get(tid, set()))
            if associated:
                seg_info.associated_source_ids = associated
                # Untouched clips are members too, so a chain re-timing sees the whole timeline (e.g. a loop after a replaced intro).
                linked_track_ids = [tid for tid in track_obj_to_all_clips if struct.pack("<I", tid) in seg_node_data]
                seg_info.member_clips = [clip for tid in linked_track_ids for clip in track_obj_to_all_clips[tid]]
                seg_info.has_alternative_subtracks = any(track_obj_to_subtracks.get(tid, 1) > 1 for tid in linked_track_ids)
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
        vol_bytes = struct.pack("<f", db_val)
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
        content[values_start:values_start] = struct.pack("<f", db_val)
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

    # Snapshot each clip's original fPlayAt, fSrcDuration and trims before pass 1 overwrites them.
    original_timings = {}  # clear_region_offset -> (old_fPlayAt, old_fSrcDuration)
    original_trims = {}
    for track in targets.tracks:
        if track.source_id in duration_ms_by_source:
            original_timings[track.clear_region_offset] = (
                struct.unpack_from("<d", content, track.fPlayAt_offset)[0],
                struct.unpack_from("<d", content, track.fSrcDuration_offset)[0],
            )
            original_trims[track.clear_region_offset] = _clip_trims(content, track)
    # The entry cue follows the clips that play at it, so each segment clip keeps its audible span from before any write.
    spans_before_patch = {}  # clear_region_offset -> (audible start, audible end)
    for segment in targets.segments:
        for clip in segment.member_clips:
            spans_before_patch.setdefault(clip.clear_region_offset, _audible_span(content, clip))

    # Pass 1 starts each replaced clip where its old audio became audible, clears eventID and trims and sets fSrcDuration.
    # Keeping fPlayAt under a cleared begin trim would put the start of the new audio before the segment and cut it.
    event_id_zeros = b"\x00\x00\x00\x00"
    trim_zeros = b"\x00" * 16
    for track in targets.tracks:
        new_duration = duration_ms_by_source.get(track.source_id)
        if new_duration is None:
            continue
        clear_offset = track.clear_region_offset
        old_play_at = original_timings[clear_offset][0]
        old_begin_trim = original_trims[clear_offset][0]
        event_id = slice(clear_offset, clear_offset + 4)
        play_at = slice(track.fPlayAt_offset, track.fPlayAt_offset + 8)
        trims = slice(clear_offset + 12, clear_offset + 28)
        src_duration = slice(track.fSrcDuration_offset, track.fSrcDuration_offset + 8)
        play_at_bytes = struct.pack("<d", old_play_at + old_begin_trim)
        duration_bytes = struct.pack("<d", float(new_duration))
        if (content[event_id] == event_id_zeros
                and content[play_at] == play_at_bytes
                and content[trims] == trim_zeros
                and content[src_duration] == duration_bytes):
            continue
        content[event_id] = event_id_zeros
        content[play_at] = play_at_bytes
        content[trims] = trim_zeros
        content[src_duration] = duration_bytes
        patched_offsets += 1
        patched_source_ids.add(track.source_id)

    # Pass 2 re-times clips and recomputes duration only for clean concatenations.
    # Loop-with-tail segments keep their musical fDuration and are not re-timed.
    for segment in targets.segments:
        chain = _sequential_chain(content, segment, original_timings, original_trims)
        if chain is not None:
            segment_offsets, segment_source_ids = _retime_chain(content, segment, chain, original_timings, duration_ms_by_source)
        else:
            segment_offsets, segment_source_ids = _retime_replaced_clips(content, segment, spans_before_patch, original_timings, duration_ms_by_source)
        patched_offsets += segment_offsets + _follow_entry_cue(content, segment, spans_before_patch, original_timings)
        patched_source_ids.update(segment_source_ids)

    return {
        "patched_offsets": patched_offsets,
        "patched_source_ids": patched_source_ids,
    }


def _clip_trims(content, clip):
    # (fBeginTrimOffset, fEndTrimOffset) of a playlist clip, which sit after its fPlayAt.
    return (
        struct.unpack_from("<d", content, clip.clear_region_offset + 12)[0],
        struct.unpack_from("<d", content, clip.clear_region_offset + 20)[0],
    )


def _audible_span(content, clip):
    # (start, end) of the part of a clip that plays on its segment timeline, trims included.
    play_at = struct.unpack_from("<d", content, clip.fPlayAt_offset)[0]
    src_duration = struct.unpack_from("<d", content, clip.fSrcDuration_offset)[0]
    begin_trim, end_trim = _clip_trims(content, clip)
    return play_at + begin_trim, play_at + src_duration + end_trim


def _retime_replaced_clips(content, segment, spans_before_patch, original_timings, duration_ms_by_source):
    # Outside a sequential chain only the replaced clips move, each by how much the replaced clips before it grew.
    # Spans include the trims, so an end trim landing on fDuration reads as a concatenation; returns (patched offsets, source ids).
    replaced_spans = []  # (clip, old audible start, old audible end, new duration)
    for clip in segment.member_clips:
        new_duration = duration_ms_by_source.get(clip.source_id)
        if new_duration is None or clip.clear_region_offset not in original_timings:
            continue
        old_start, old_end = spans_before_patch[clip.clear_region_offset]
        replaced_spans.append((clip, old_start, old_end, float(new_duration)))
    if not replaced_spans:
        return 0, set()

    old_timeline_end = max(old_end for _, _, old_end, _ in replaced_spans)
    old_segment_duration = struct.unpack_from("<d", content, segment.fDuration_offset)[0]
    if abs(old_segment_duration - old_timeline_end) > _CONCAT_TOLERANCE_MS:
        return 0, set()  # loop-with-tail: leave untouched

    patched_offsets = 0
    new_clip_ends = []
    for clip, old_start, _, new_duration in replaced_spans:
        # Pass 1 left the clip at old_start, so only the growth of the clips that finish before it moves it again.
        shift = sum(
            other_new_duration - (other_end - other_start)
            for other, other_start, other_end, other_new_duration in replaced_spans
            if other is not clip and other_end <= old_start + _CONCAT_TOLERANCE_MS
        )
        if abs(shift) > 1e-6:
            struct.pack_into("<d", content, clip.fPlayAt_offset, old_start + shift)
            patched_offsets += 1
        new_clip_ends.append(old_start + shift + new_duration)

    new_segment_duration = max(new_clip_ends)
    old_marker_pos = struct.unpack_from("<d", content, segment.end_marker_fPos_offset)[0]
    if abs(new_segment_duration - old_segment_duration) > 1e-6 or abs(new_segment_duration - old_marker_pos) > 1e-6:
        struct.pack_into("<d", content, segment.fDuration_offset, new_segment_duration)
        struct.pack_into("<d", content, segment.end_marker_fPos_offset, new_segment_duration)
        patched_offsets += 1
    if not patched_offsets:
        return 0, set()
    return patched_offsets, {clip.source_id for clip, *_ in replaced_spans}


def _follow_entry_cue(content, segment, spans_before_patch, original_timings):
    # The entry cue stays on the clip that plays at it, and moves to the start of a replaced one so none of it is skipped as pre-entry.
    # Untouched layers playing at the cue keep it on their downbeat instead; returns the number of patched offsets.
    if segment.entry_marker_fPos_offset is None:
        return 0
    entry = struct.unpack_from("<d", content, segment.entry_marker_fPos_offset)[0]
    clips_at_entry = []
    for clip in segment.member_clips:
        start, end = spans_before_patch[clip.clear_region_offset]
        if clip.source_id and start < end and start - _CONCAT_TOLERANCE_MS <= entry < end:
            clips_at_entry.append(clip)
    if not clips_at_entry:
        return 0
    # On the boundary between two clips the cue belongs to the one that starts there.
    latest_start = max(spans_before_patch[clip.clear_region_offset][0] for clip in clips_at_entry)
    clips_at_entry = [clip for clip in clips_at_entry if spans_before_patch[clip.clear_region_offset][0] >= latest_start - _CONCAT_TOLERANCE_MS]
    untouched_clips = [clip for clip in clips_at_entry if clip.clear_region_offset not in original_timings]
    if untouched_clips:
        clip = untouched_clips[0]
        new_entry = entry + _audible_span(content, clip)[0] - spans_before_patch[clip.clear_region_offset][0]
    else:
        new_entry = min(_audible_span(content, clip)[0] for clip in clips_at_entry)
    if abs(new_entry - entry) <= 1e-6:
        return 0
    struct.pack_into("<d", content, segment.entry_marker_fPos_offset, new_entry)
    return 1


def _sequential_chain(content, segment, original_timings, original_trims):
    # Audible (start, end, clip) sorted by start when distinct sources play one after another, like an intro then its loop.
    # Parallel layers, splices of one source and switch/random alternatives return None and keep the replaced-clips-only re-timing.
    if segment.has_alternative_subtracks:
        return None
    chain = []
    for clip in segment.member_clips:
        if clip.clear_region_offset in original_timings:
            play_at, src_duration = original_timings[clip.clear_region_offset]
            begin_trim, end_trim = original_trims[clip.clear_region_offset]
        else:
            play_at = struct.unpack_from("<d", content, clip.fPlayAt_offset)[0]
            src_duration = struct.unpack_from("<d", content, clip.fSrcDuration_offset)[0]
            begin_trim, end_trim = _clip_trims(content, clip)
        if clip.source_id == 0 or src_duration <= 0:
            continue
        chain.append((play_at + begin_trim, play_at + src_duration + end_trim, clip))
    if len(chain) < 2 or len({clip.source_id for _, _, clip in chain}) != len(chain):
        return None
    if not any(clip.clear_region_offset in original_timings for _, _, clip in chain):
        return None
    chain.sort(key=lambda entry: entry[0])
    for index, (start, end, _) in enumerate(chain):
        for later_start, later_end, _ in chain[index + 1:]:
            overlap = min(end, later_end) - later_start
            if later_start <= start + _CONCAT_TOLERANCE_MS or overlap > 0.5 * min(end - start, later_end - later_start):
                return None
    return chain


def _retime_chain(content, segment, chain, original_timings, duration_ms_by_source):
    # Each clip moves by how much the clips before it grew, so an untouched loop starts where a replaced intro now ends.
    # A loop-with-tail chain keeps its musical fDuration and every fPlayAt; returns (patched offsets, replaced or moved source ids).
    old_chain_end = max(end for _, end, _ in chain)
    old_segment_duration = struct.unpack_from("<d", content, segment.fDuration_offset)[0]
    if abs(old_segment_duration - old_chain_end) > _CONCAT_TOLERANCE_MS:
        return 0, set()

    patched_offsets = 0
    changed_source_ids = set()
    shift = 0.0
    new_clip_ends = []
    for old_start, old_end, clip in chain:
        if clip.clear_region_offset in original_timings:
            # Pass 1 already moved a replaced clip to old_start, where its old audio became audible.
            play_at = old_start
            new_end = old_start + float(duration_ms_by_source[clip.source_id])
            changed_source_ids.add(clip.source_id)
        else:
            play_at = struct.unpack_from("<d", content, clip.fPlayAt_offset)[0]
            new_end = old_end
        if abs(shift) > 1e-6:
            struct.pack_into("<d", content, clip.fPlayAt_offset, play_at + shift)
            patched_offsets += 1
            changed_source_ids.add(clip.source_id)
        new_clip_ends.append(new_end + shift)
        shift = new_end + shift - old_end

    new_segment_duration = max(new_clip_ends)
    old_marker_pos = struct.unpack_from("<d", content, segment.end_marker_fPos_offset)[0]
    if abs(new_segment_duration - old_segment_duration) > 1e-6 or abs(new_segment_duration - old_marker_pos) > 1e-6:
        struct.pack_into("<d", content, segment.fDuration_offset, new_segment_duration)
        struct.pack_into("<d", content, segment.end_marker_fPos_offset, new_segment_duration)
        patched_offsets += 1
    if not patched_offsets:
        return 0, set()
    return patched_offsets, changed_source_ids


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


def _parse_track_clips(content, data_start, obj_size):
    # Returns (obj_id, track_source_ids, every playlist clip as TrackPatchInfo, playlist end offset), or None on an unexpected layout.
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

    if p + 4 > end:
        return None
    num_playlist = struct.unpack_from("<I", content, p)[0]
    p += 4
    if num_playlist > 100:
        return None

    items_end = p + num_playlist * _TRACK_SRC_INFO_SIZE
    if items_end > end:
        return None

    clips = []
    for _ in range(num_playlist):
        clips.append(
            TrackPatchInfo(
                source_id=struct.unpack_from("<I", content, p + 4)[0],
                fSrcDuration_offset=p + _TRACK_SRC_DURATION_OFFSET_IN_ITEM,
                fPlayAt_offset=p + _TRACK_SRC_PLAY_AT_OFFSET_IN_ITEM,
                clear_region_offset=p + 8,  # eventID(4)+fPlayAt(8)+fBeginTrim(8)+fEndTrim(8) = 28 bytes
            )
        )
        p += _TRACK_SRC_INFO_SIZE
    return obj_id, track_source_ids, clips, p


def _parse_music_track(content, data_start, obj_size, source_ids):
    # Returns (obj_id, [TrackPatchInfo], [VolumePatchInfo]) when the track references any id in `source_ids`, else None.
    end = data_start + obj_size
    parsed_track = _parse_track_clips(content, data_start, obj_size)
    if parsed_track is None:
        return None
    obj_id, track_source_ids, clips, p = parsed_track

    if not (track_source_ids & source_ids):
        return None

    patches = [clip for clip in clips if clip.source_id in source_ids]
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
    # Uses marker-scanning heuristic to locate fDuration and the fPosition of the entry and end markers.
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
        entry_fpos_data_offset = None

        for _ in range(nm):
            if p + 16 > obj_size:
                parsed_ok = False
                break
            marker_id = struct.unpack_from("<I", data, p)[0]
            nlen = struct.unpack_from("<I", data, p + 12)[0]
            if nlen > 500:
                parsed_ok = False
                break
            if marker_id == ENTRY_MARKER_ID:
                entry_fpos_data_offset = p + 4
            last_id = marker_id
            last_fpos_data_offset = p + 4  # fPosition is 4 bytes after marker start
            p += 16 + nlen

        if not parsed_ok or p != obj_size or last_id != END_MARKER_ID:
            continue

        return SegmentPatchInfo(
            fDuration_offset=data_start + try_off - 8,
            end_marker_fPos_offset=data_start + last_fpos_data_offset,
            entry_marker_fPos_offset=None if entry_fpos_data_offset is None else data_start + entry_fpos_data_offset,
        )

    return None
