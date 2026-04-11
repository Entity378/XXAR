import struct
from dataclasses import dataclass, field

HIRC_TYPE_MUSIC_SEGMENT = 0x0A
HIRC_TYPE_MUSIC_TRACK = 0x0B
END_MARKER_ID = 0x5BBBD648

VOLUME_PROP_ID = 0x00

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
    clear_region_offset: int  # start of eventID+fPlayAt+fBeginTrim+fEndTrim (28 bytes to zero)


@dataclass
class VolumePatchInfo:
    source_id: int
    prop_bundle_cProps_offset: int   # absolute offset of the cProps byte
    volume_value_offset: int         # absolute offset of the volume float (or insertion point)
    has_existing_volume: bool        # True = overwrite in-place, False = need insert


@dataclass
class SegmentPatchInfo:
    fDuration_offset: int
    end_marker_fPos_offset: int
    associated_source_ids: set = field(default_factory=set)


@dataclass
class BankPatchTargets:
    tracks: list = field(default_factory=list)
    segments: list = field(default_factory=list)
    volume_patches: list = field(default_factory=list)


def scan_bank_for_patch_targets(content, source_ids):
    # Scan a PCK/BNK file for MusicTrack and MusicSegment HIRC objects
    # referencing the given WEM source IDs.
    # Returns a BankPatchTargets with precise absolute file offsets for all
    # duration fields that need patching.
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

    return BankPatchTargets(
        tracks=all_tracks, segments=all_segments, volume_patches=all_volume,
    )


def apply_volume_patches(content, volume_patches, volume_db_by_source):
    """Apply volume patches to a mutable bytearray.

    Only patches tracks that already have a Volume property in their
    AkPropBundle (in-place overwrite, no size change).  Tracks without
    an existing property are skipped to avoid corrupting the file.

    Returns {"patched": int, "skipped": int}.
    """
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
        print(f"[HIRC Patch] Volume: skipped {skipped} track(s) without existing volume property")

    return {"patched": patched, "inserted": 0, "total_shift": 0}


def apply_duration_patches(content, targets, duration_ms_by_source):
    """Write new duration values to the bank content bytearray.

    duration_ms_by_source: dict mapping source_id (int) -> duration in ms (float).
    Returns {"patched_offsets": int, "patched_source_ids": set}.
    """
    patched_offsets = 0
    patched_source_ids = set()

    _zero_28 = b"\x00" * 28
    for track in targets.tracks:
        dur = duration_ms_by_source.get(track.source_id)
        if dur is None:
            continue
        dur_bytes = struct.pack("<d", float(dur))

        existing = bytes(content[track.clear_region_offset : track.clear_region_offset + 36])
        if existing[:28] == _zero_28 and existing[28:] == dur_bytes:
            continue

        content[track.clear_region_offset : track.clear_region_offset + 28] = _zero_28
        content[track.clear_region_offset + 28 : track.clear_region_offset + 36] = dur_bytes
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

        existing_dur = bytes(content[seg.fDuration_offset : seg.fDuration_offset + 8])
        existing_marker = bytes(content[seg.end_marker_fPos_offset : seg.end_marker_fPos_offset + 8])

        if existing_dur == dur_bytes and existing_marker == dur_bytes:
            continue

        content[seg.fDuration_offset : seg.fDuration_offset + 8] = dur_bytes
        content[seg.end_marker_fPos_offset : seg.end_marker_fPos_offset + 8] = dur_bytes
        patched_offsets += 1
        patched_source_ids.update(seg.associated_source_ids)

    return {
        "patched_offsets": patched_offsets,
        "patched_source_ids": patched_source_ids,
    }


# Internal helpers


def _adjust_hirc_sizes(content, offset_inside_object, delta):
    """Walk backwards from an offset inside an HIRC object to find and update
    the object size field and the HIRC section size field."""
    # Find the nearest HIRC header before this offset.
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
    # data_start points to the first byte after the 8-byte header (HIRC + u32 size),
    # i.e. the numItems u32.  data_size is the section payload size.
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

    Returns (obj_id, [TrackPatchInfo, ...], [VolumePatchInfo, ...])
    if the track references any source in *source_ids*, otherwise None.
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
                    clear_region_offset=p + 8,  # eventID(4)+fPlayAt(8)+fBeginTrim(8)+fEndTrim(8) = 28 bytes
                )
            )
        p += _TRACK_SRC_INFO_SIZE

    if not patches:
        return None

    # --- Continue parsing to find AkPropBundle for volume ---
    volume_patches = _parse_volume_from_track(content, p, end, patches)

    return (obj_id, patches, volume_patches)


def _parse_volume_from_track(content, p, end, track_patches):
    """Parse the post-playlist section of a MusicTrack to find the volume
    property in the AkPropBundle.  *p* is the cursor right after the playlist.

    Layout (confirmed by parse_hirc_examples.py):
      numSubTrack(u32) + numClipAutomation(u32) +
        [AkClipAutomation: clipIndex(4) + autoType(4) + numPoints(4) + points(12*n)] +
      eTrackType(u32) + bIsTransitionEnabled(u8) +
      NodeBaseParams (Music variant):
        bIsOverrideParentFX(u8) + uNumFx(u8) + [FX data] +
        directParentID(u32) + byBitVector(u8) +
        AkPropBundle: cProps(u8) + pID[cProps] + pValue[cProps*4]
    """
    try:
        return _parse_volume_from_track_inner(content, p, end, track_patches)
    except Exception:
        # If parsing fails (unexpected layout), skip volume for this track.
        return []


def _parse_volume_from_track_inner(content, p, end, track_patches):
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
        # Insertion point: end of values array
        volume_value_offset = p + cProps * 4

    # Create one VolumePatchInfo per matched source in this track
    results = []
    for tp in track_patches:
        results.append(
            VolumePatchInfo(
                source_id=tp.source_id,
                prop_bundle_cProps_offset=cProps_offset,
                volume_value_offset=volume_value_offset,
                has_existing_volume=has_existing,
            )
        )
    return results


def _parse_music_segment(content, data_start, obj_size):
    # Parse a MusicSegment (0x0A) HIRC object.
    # Uses marker-scanning heuristic to locate fDuration and the end marker's
    # fPosition.  Returns SegmentPatchInfo or None.
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
