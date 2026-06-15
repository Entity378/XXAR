# Pure HIRC music-object parsing and logical track-patch application.
# These helpers operate on raw bnk bytes only, with no Qt, config, or file I/O.
# They are shared between the live HIRC Editor and the mod-apply pipeline.

import struct
from io import BytesIO
from typing import List, Optional

from src.core.logger import get_logger
from src.wwise.bnk_handler import BNKFile
from src.wwise.hirc_patcher import (
    apply_duration_patches,
    apply_volume_inserts,
    scan_bank_for_patch_targets,
)

logger = get_logger(__name__)


HIRC_TYPE_NAMES = {
    0x0A: "MusicSegment",
    0x0B: "MusicTrack",
    0x0C: "MusicSwitchCntr",
    0x0D: "MusicRanSeqCntr",
}
MUSIC_HIRC_TYPES = set(HIRC_TYPE_NAMES.keys())
HIRC_TYPE_MUSIC_TRACK = 0x0B

# AkBankSourceData layout (14 bytes per source).
# pluginID(4) + streamType(1) + sourceID(4) + mediaSize(4) + sourceBits(1).
_SOURCE_DATA_SIZE = 14
_SOURCE_ID_OFFSET_IN_SOURCE = 5

# TrackSrcInfo (44 bytes per playlist item).
# trackID(4) + sourceID(4) + eventID(4) + fPlayAt(8) + fBeginTrim(8) + fEndTrim(8) + fSrcDuration(8).
_TRACK_SRC_INFO_SIZE = 44


def _find_hirc_sections(content: bytes):
    # Yield (data_start, data_size) for each HIRC chunk in a bnk.
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
        yield (pos + 8, section_size)


def _iter_music_types_in_content(content: bytes):
    for hs, hsz in _find_hirc_sections(content):
        se = hs + hsz
        if hs + 4 > se:
            continue
        n_obj = struct.unpack_from("<I", content, hs)[0]
        op = hs + 4
        for _ in range(n_obj):
            if op + 5 > se:
                break
            ot = content[op]
            osz = struct.unpack_from("<I", content, op + 1)[0]
            if ot in MUSIC_HIRC_TYPES:
                yield ot
            op = op + 5 + osz


def _collect_bnk_music_index(content: bytes):
    # Count music HIRC objects and collect every MusicTrack source id in one pass.
    # It is lightweight (no volume scan) and feeds the bnk-list search index.
    # Returns (music_count, set_of_source_ids).
    count = 0
    ids = set()
    for hs, hsz in _find_hirc_sections(content):
        se = hs + hsz
        if hs + 4 > se:
            continue
        n_obj = struct.unpack_from("<I", content, hs)[0]
        op = hs + 4
        for _ in range(n_obj):
            if op + 5 > se:
                break
            ot = content[op]
            osz = struct.unpack_from("<I", content, op + 1)[0]
            ds = op + 5
            de = ds + osz
            if de > len(content):
                break
            if ot in MUSIC_HIRC_TYPES:
                count += 1
                if ot == HIRC_TYPE_MUSIC_TRACK and ds + 9 <= de:
                    num_sources = struct.unpack_from("<I", content, ds + 5)[0]
                    if 0 <= num_sources <= 100:
                        p = ds + 9
                        for _ in range(num_sources):
                            if p + _SOURCE_DATA_SIZE > de:
                                break
                            ids.add(struct.unpack_from(
                                "<I", content, p + _SOURCE_ID_OFFSET_IN_SOURCE)[0])
                            p += _SOURCE_DATA_SIZE
                        if p + 4 <= de:
                            num_pl = struct.unpack_from("<I", content, p)[0]
                            p += 4
                            if 0 <= num_pl <= 200:
                                for _ in range(num_pl):
                                    if p + _TRACK_SRC_INFO_SIZE > de:
                                        break
                                    ids.add(struct.unpack_from("<I", content, p + 4)[0])
                                    p += _TRACK_SRC_INFO_SIZE
            op = de
    return count, ids


def _parse_music_track_fields(
    content: bytes, ds: int, de: int, abs_off_base: int
) -> Optional[dict]:
    # Extract MusicTrack obj_id + AkBankSourceData/TrackSrcInfo entries with absolute pck offsets.
    # Also returns the current loop_ms (TrackSrcInfo[0].fSrcDuration).
    if ds + 9 > de:
        return None
    obj_id = struct.unpack_from("<I", content, ds)[0]
    num_sources = struct.unpack_from("<I", content, ds + 5)[0]
    if num_sources < 0 or num_sources > 100:
        return None

    sources: List[dict] = []
    p = ds + 9
    for k in range(num_sources):
        if p + _SOURCE_DATA_SIZE > de:
            break
        sid_off = p + _SOURCE_ID_OFFSET_IN_SOURCE
        sid = struct.unpack_from("<I", content, sid_off)[0]
        sources.append({
            "index": k,
            "source_id": sid,
            "abs_offset_in_pck": abs_off_base + sid_off,
        })
        p += _SOURCE_DATA_SIZE

    playlist: List[dict] = []
    if p + 4 <= de:
        num_pl = struct.unpack_from("<I", content, p)[0]
        p += 4
        if 0 <= num_pl <= 200:
            for j in range(num_pl):
                if p + _TRACK_SRC_INFO_SIZE > de:
                    break
                ts_sid_off = p + 4
                ts_sid = struct.unpack_from("<I", content, ts_sid_off)[0]
                playlist.append({
                    "index": j,
                    "source_id": ts_sid,
                    "abs_offset_in_pck": abs_off_base + ts_sid_off,
                })
                p += _TRACK_SRC_INFO_SIZE

    loop_ms: Optional[float] = None
    loop_clear_offset_abs: Optional[int] = None
    loop_duration_offset_abs: Optional[int] = None
    if playlist:
        first_ts_sid_off = playlist[0]["abs_offset_in_pck"] - abs_off_base
        ts_struct_start = first_ts_sid_off - 4  # back up to trackID
        clear_off = ts_struct_start + 8
        dur_off = ts_struct_start + 36
        if 0 <= dur_off + 8 <= len(content):
            try:
                loop_ms = struct.unpack_from("<d", content, dur_off)[0]
                loop_clear_offset_abs = abs_off_base + clear_off
                loop_duration_offset_abs = abs_off_base + dur_off
            except Exception:
                loop_ms = None

    return {
        "obj_id": obj_id,
        "type": "MusicTrack",
        "type_hex": "0x0B",
        "body_size": de - ds,
        "sources": sources,
        "playlist": playlist,
        "loop_ms": loop_ms,
        "loop_clear_offset_abs": loop_clear_offset_abs,
        "loop_duration_offset_abs": loop_duration_offset_abs,
        "volume_db": None,
        "volume_offset_abs": None,
        "has_volume": False,
        "volume_insertable": False,
        # Internal: bnk-relative bounds used to disambiguate per-track volumes.
        # They matter when multiple tracks share the same source_id.
        # Stripped before leaving the parse.
        "_ds_local": ds,
        "_de_local": de,
    }


def _parse_music_object_basic(
    obj_type: int, content: bytes, ds: int, de: int
) -> Optional[dict]:
    if ds + 4 > de:
        return None
    obj_id = struct.unpack_from("<I", content, ds)[0]
    out: dict = {
        "obj_id": obj_id,
        "type": HIRC_TYPE_NAMES.get(obj_type, f"0x{obj_type:02X}"),
        "type_hex": f"0x{obj_type:02X}",
        "body_size": de - ds,
        "sources": [],
        "playlist": [],
        "loop_ms": None,
        "loop_clear_offset_abs": None,
        "loop_duration_offset_abs": None,
        "volume_db": None,
        "volume_offset_abs": None,
        "has_volume": False,
        "volume_insertable": False,
    }
    # NOTE: container-type AkPropBundle parsing is unreliable for Genshin's Wwise variant.
    # Both alignments (with/without bOverrideAttachmentParams) produce garbage prop_ids/values.
    # This affects MusicSegment, MusicRanSeqCntr and MusicSwitchCntr.
    # The Volume offset for these nodes most likely lives elsewhere.
    # Candidates: StateGroup attenuations, RTPC bindings or CAkBus volumes.
    # None of those are reachable from a simple AkPropBundle scan.
    # We deliberately do NOT expose volume editing for these types to avoid corrupting the bnk.
    return out


def _scan_bnk_music_objects(
    content: bytes, bnk_abs_offset_in_pck: int
) -> List[dict]:
    out: List[dict] = []
    for hs, hsz in _find_hirc_sections(content):
        se = hs + hsz
        if hs + 4 > se:
            continue
        n_obj = struct.unpack_from("<I", content, hs)[0]
        op = hs + 4
        for _ in range(n_obj):
            if op + 5 > se:
                break
            ot = content[op]
            osz = struct.unpack_from("<I", content, op + 1)[0]
            ds = op + 5
            de = ds + osz
            if de > len(content):
                break
            if ot in MUSIC_HIRC_TYPES:
                if ot == HIRC_TYPE_MUSIC_TRACK:
                    parsed = _parse_music_track_fields(
                        content, ds, de, bnk_abs_offset_in_pck
                    )
                else:
                    parsed = _parse_music_object_basic(ot, content, ds, de)
                if parsed is not None:
                    out.append(parsed)
            op = de

    # Second pass: lift AkPropBundle Volume offsets via the HIRC patcher.
    # Single call with all source_ids.
    # Then attribute each VolumePatchInfo to its owning MusicTrack.
    # Match is done by checking which track's body range contains volume_value_offset.
    # Multiple tracks can share the same source_id but each carries its own AkPropBundle.
    # Per-source dict-mapping was wrong.
    all_source_ids: set = set()
    for o in out:
        if o.get("type") == "MusicTrack":
            for s in o.get("sources", []):
                all_source_ids.add(s["source_id"])
    if not all_source_ids:
        for o in out:
            o.pop("_ds_local", None)
            o.pop("_de_local", None)
        return out
    try:
        targets = scan_bank_for_patch_targets(content, all_source_ids)
    except Exception:
        for o in out:
            o.pop("_ds_local", None)
            o.pop("_de_local", None)
        return out

    # Build a sorted index of (ds_local, de_local, track_dict) tuples.
    # Used for lookup of the owning track per volume_value_offset.
    track_ranges = []
    for o in out:
        if o.get("type") != "MusicTrack":
            continue
        ds_l = o.get("_ds_local")
        de_l = o.get("_de_local")
        if ds_l is not None and de_l is not None:
            track_ranges.append((ds_l, de_l, o))
    track_ranges.sort(key=lambda t: t[0])

    def _find_owner(off):
        # Linear-ish scan; ranges are non-overlapping and sorted by start.
        # For typical bnks (hundreds of tracks) this is plenty fast.
        for ds_l, de_l, owner in track_ranges:
            if ds_l <= off < de_l:
                return owner
            if ds_l > off:
                return None
        return None

    seen_track_ids = set()
    for vp in targets.volume_patches:
        owner = _find_owner(vp.volume_value_offset)
        if owner is None:
            continue
        # A located AkPropBundle means a Volume can be inserted or overwritten here.
        # Sourceless placeholder tracks never reach this, so they stay non-insertable.
        owner["volume_insertable"] = True
        if not vp.has_existing_volume:
            continue
        if owner["obj_id"] in seen_track_ids:
            continue  # one volume per track
        seen_track_ids.add(owner["obj_id"])
        vof = vp.volume_value_offset
        if 0 <= vof + 4 <= len(content):
            try:
                owner["volume_db"] = float(
                    struct.unpack_from("<f", content, vof)[0]
                )
                owner["volume_offset_abs"] = bnk_abs_offset_in_pck + vof
                owner["has_volume"] = True
            except Exception:
                pass

    # Strip internal-only fields from the returned dicts.
    for o in out:
        o.pop("_ds_local", None)
        o.pop("_de_local", None)
    return out


def _extract_track_source_ids(content, track_obj_id: int) -> set:
    # Walk HIRC, find MusicTrack with given obj_id, return set of its AkBankSourceData sourceIDs.
    out: set = set()
    for hs, hsz in _find_hirc_sections(content):
        se = hs + hsz
        if hs + 4 > se:
            continue
        n_obj = struct.unpack_from("<I", content, hs)[0]
        op = hs + 4
        for _ in range(n_obj):
            if op + 5 > se:
                break
            ot = content[op]
            osz = struct.unpack_from("<I", content, op + 1)[0]
            ds = op + 5
            de = ds + osz
            if de > len(content):
                break
            if ot == HIRC_TYPE_MUSIC_TRACK and ds + 9 <= de:
                obj_id = struct.unpack_from("<I", content, ds)[0]
                if obj_id == track_obj_id:
                    num_sources = struct.unpack_from("<I", content, ds + 5)[0]
                    if 0 <= num_sources <= 100:
                        p = ds + 9
                        for _ in range(num_sources):
                            if p + _SOURCE_DATA_SIZE > de:
                                break
                            out.add(struct.unpack_from(
                                "<I", content, p + _SOURCE_ID_OFFSET_IN_SOURCE
                            )[0])
                            p += _SOURCE_DATA_SIZE
                    return out
            op = de
    return out


def _insert_track_volumes(bnk_bytes: bytearray, volume_db_by_source: dict) -> int:
    # Insert a Volume prop into MusicTracks that lack one, growing bnk_bytes in place.
    # Returns the insert count; BNKFile reframes the chunk so only the object size field changes.
    try:
        bnk = BNKFile(bnk_bytes=bytes(bnk_bytes))
    except Exception:
        return 0
    if "HIRC" not in bnk.data:
        return 0
    mini = bytearray(bnk.data["HIRC"].getdata())
    targets = scan_bank_for_patch_targets(mini, set(volume_db_by_source.keys()))
    res = apply_volume_inserts(mini, targets.volume_patches, volume_db_by_source)
    if res["inserted"] <= 0:
        return 0
    bnk.data["HIRC"].data = BytesIO(bytes(mini[12:]))
    bnk_bytes[:] = bnk.get_bytes()
    return res["inserted"]


def apply_track_patches_to_bnk(bnk_bytes: bytearray, patches_for_bnk: list) -> dict:
    # Apply offset-free track patches to one bnk by obj_id: source remaps, loop, volume.
    # Inserting a volume on a track that lacks one grows the bnk, so the caller repacks on size change.
    result = {"remaps": 0, "loops": 0, "volumes": 0}
    if not patches_for_bnk:
        return result
    if not isinstance(bnk_bytes, bytearray):
        raise TypeError("bnk_bytes must be a bytearray (mutated in place)")

    # Pass 1: source-id remaps. Mutates bytes, so we re-parse afterwards for the rest.
    objs = _scan_bnk_music_objects(bnk_bytes, 0)
    by_obj = {o["obj_id"]: o for o in objs}
    for patch in patches_for_bnk:
        track = by_obj.get(int(patch.get("track_obj_id")))
        if track is None:
            logger.warning(
                f"[HIRC patch] track obj_id {patch.get('track_obj_id')} not found in bnk; skipping remaps"
            )
            continue
        for remap in patch.get("source_remaps", []) or []:
            slot = str(remap.get("slot", "src"))
            idx = int(remap.get("index", 0))
            try:
                new_id = int(remap.get("new_source_id"))
            except (TypeError, ValueError):
                continue
            arr = track.get("sources") if slot == "src" else track.get("playlist")
            if not arr or idx < 0 or idx >= len(arr):
                logger.warning(
                    f"[HIRC patch] remap slot {slot}[{idx}] out of range for track {track['obj_id']}"
                )
                continue
            off = arr[idx]["abs_offset_in_pck"]  # base 0 -> bnk-relative
            if off + 4 > len(bnk_bytes):
                continue
            cur = struct.unpack_from("<I", bnk_bytes, off)[0]
            old_expected = remap.get("old_source_id")
            if old_expected is not None and cur != int(old_expected):
                # Already remapped (idempotent re-apply) or stale descriptor: skip safely.
                logger.info(
                    f"[HIRC patch] remap skip {slot}[{idx}] track {track['obj_id']}: "
                    f"expected {old_expected}, found {cur}"
                )
                continue
            struct.pack_into("<I", bnk_bytes, off, new_id)
            result["remaps"] += 1

    # Pass 2: re-parse so source_ids / volume offsets reflect the remaps just written.
    objs2 = _scan_bnk_music_objects(bnk_bytes, 0)
    by_obj2 = {o["obj_id"]: o for o in objs2}
    loop_map = {}  # source_id -> loop_ms
    vol_insert_map = {}  # source_id -> db, for tracks without an existing Volume prop
    for patch in patches_for_bnk:
        track = by_obj2.get(int(patch.get("track_obj_id")))
        if track is None:
            continue
        vol = patch.get("volume_db")
        if vol is not None:
            if track.get("has_volume") and track.get("volume_offset_abs") is not None:
                voff = int(track["volume_offset_abs"])
                if 0 <= voff + 4 <= len(bnk_bytes):
                    struct.pack_into("<f", bnk_bytes, voff, float(vol))
                    result["volumes"] += 1
            else:
                # No existing Volume here, so insert one keyed by source_id (mirrors the loop map).
                for s in track.get("sources", []) or []:
                    vol_insert_map[s["source_id"]] = float(vol)
        loop_ms = patch.get("loop_ms")
        if loop_ms is not None:
            for s in track.get("sources", []) or []:
                loop_map[s["source_id"]] = float(loop_ms)

    # Loop durations reuse the HIRC patcher, matching by current source_id.
    # This mirrors hirc_editor_bridge._patch_loop_ms.
    if loop_map:
        try:
            targets = scan_bank_for_patch_targets(bytes(bnk_bytes), set(loop_map.keys()))
            dur_result = apply_duration_patches(bnk_bytes, targets, loop_map)
            result["loops"] = int(dur_result.get("patched_offsets", 0))
        except Exception as e:
            logger.warning(f"[HIRC patch] loop duration patch failed: {e}")

    # Volume inserts grow the bnk, so they run last after the size-preserving passes.
    if vol_insert_map:
        try:
            result["volumes"] += _insert_track_volumes(bnk_bytes, vol_insert_map)
        except Exception as e:
            logger.warning(f"[HIRC patch] volume insert failed: {e}")

    return result
