import struct

from helpers import hirc_object

SOUND = 0x02
MUSIC_SEGMENT = 0x0A
MUSIC_TRACK = 0x0B
MUSIC_SWITCH = 0x0C
MUSIC_RANSEQ = 0x0D
VOLUME = 0x00
PITCH = 0x02
LOW_PASS_FILTER = 0x03
END_MARKER_ID = 0x5BBBD648
ENTRY_MARKER_ID = 0x0298DF12
VORBIS_PLUGIN_ID = 0x00040001
STREAMING = 2

# Positioning and state bytes that follow the RangedModifiers of a real GI MusicTrack.
TRACK_TAIL = bytes.fromhex("0000000100000000000000000064000000")


def clip(source_id, play_at=0.0, duration=1000.0, begin_trim=0.0, end_trim=0.0, event_id=0):
    return struct.pack("<III4d", 0, source_id, event_id, play_at, begin_trim, end_trim, duration)


def clip_source_id(track_clip):
    return struct.unpack_from("<I", track_clip, 4)[0]


def prop_bundle(props=()):
    prop_ids = bytes(prop_id for prop_id, _ in props)
    prop_values = b"".join(struct.pack("<f", value) for _, value in props)
    return bytes([len(props)]) + prop_ids + prop_values


def music_node_base(parent_id=0, props=(), fx_count=0):
    fx_chunk = b"\x00" + b"\x00" * 6 * fx_count if fx_count else b""
    return struct.pack("<BB", 0, fx_count) + fx_chunk + struct.pack("<IB", parent_id, 0) + prop_bundle(props) + b"\x00"


def music_track(obj_id, clips, source_ids=None, props=(), parent_id=0, fx_count=0, automation_point_counts=(), subtrack_count=1):
    if source_ids is None:
        source_ids = list(dict.fromkeys(clip_source_id(track_clip) for track_clip in clips))
    body = struct.pack("<BI", 0, len(source_ids))
    for source_id in source_ids:
        body += struct.pack("<IBIIB", VORBIS_PLUGIN_ID, STREAMING, source_id, 4096, 0)
    body += struct.pack("<I", len(clips)) + b"".join(clips)
    body += struct.pack("<II", subtrack_count, len(automation_point_counts))
    for clip_index, point_count in enumerate(automation_point_counts):
        body += struct.pack("<III", clip_index, 0, point_count) + b"\x00" * 12 * point_count
    body += struct.pack("<IB", 0, 0)
    body += music_node_base(parent_id, props, fx_count) + TRACK_TAIL
    return hirc_object(MUSIC_TRACK, obj_id, body)


def meter_and_stingers():
    return struct.pack("<ddfBBBI", 1000.0, 0.0, 120.0, 4, 4, 0, 0)


def music_children(child_ids):
    return struct.pack("<I", len(child_ids)) + b"".join(struct.pack("<I", child_id) for child_id in child_ids)


def music_segment(obj_id, child_ids, duration, end_marker_position=None, entry_marker_name=b""):
    end_position = duration if end_marker_position is None else end_marker_position
    body = b"\x00" + music_node_base() + b"\x00" * 20 + music_children(child_ids) + meter_and_stingers()
    body += struct.pack("<dI", duration, 2)
    body += struct.pack("<IdI", ENTRY_MARKER_ID, 0.0, len(entry_marker_name)) + entry_marker_name
    body += struct.pack("<IdI", END_MARKER_ID, end_position, 0)
    return hirc_object(MUSIC_SEGMENT, obj_id, body)


def playlist_item(segment_id, item_id, child_count, loop_count, rs_type=0xFFFFFFFF):
    return struct.pack("<IIIIhhhIHBB", segment_id, item_id, child_count, rs_type, loop_count, 0, 0, 50000, 0, 0, 0)


def music_ranseq_intro_loop(obj_id, intro_segment_id, loop_segment_id):
    # Root sequence plays the intro leaf once, then the loop leaf forever (loop count 0).
    playlist = [
        playlist_item(0, obj_id + 1, 2, 1, rs_type=0),
        playlist_item(intro_segment_id, obj_id + 2, 0, 1),
        playlist_item(loop_segment_id, obj_id + 3, 0, 0),
    ]
    body = b"\x00" + music_node_base() + b"\x00" * 20 + music_children([intro_segment_id, loop_segment_id])
    body += meter_and_stingers() + struct.pack("<I", 0)
    body += struct.pack("<I", len(playlist)) + b"".join(playlist)
    return hirc_object(MUSIC_RANSEQ, obj_id, body)


def music_switch(obj_id, child_ids=()):
    body = b"\x00" + music_node_base() + b"\x00" * 20 + music_children(list(child_ids)) + meter_and_stingers()
    return hirc_object(MUSIC_SWITCH, obj_id, body)


def sound(obj_id, source_id, props=()):
    body = struct.pack("<IBIIB", VORBIS_PLUGIN_ID, 0, source_id, 4096, 0)
    body += struct.pack("<BBBIIB", 0, 0, 0, 0, 0, 0) + prop_bundle(props) + b"\x00" + b"\x00" * 12
    return hirc_object(SOUND, obj_id, body)


def read_u32(content, offset):
    return struct.unpack_from("<I", content, offset)[0]


def read_f32(content, offset):
    return struct.unpack_from("<f", content, offset)[0]


def read_f64(content, offset):
    return struct.unpack_from("<d", content, offset)[0]
