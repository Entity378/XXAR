import pytest

from helpers import build_bnk, make_wem
from hirc_builders import (
    PITCH,
    VOLUME,
    clip,
    music_ranseq_intro_loop,
    music_segment,
    music_switch,
    music_track,
    read_f32,
    read_f64,
    read_u32,
    sound,
)
from src.wwise.bnk_handler import BNKFile
from src.wwise.hirc_music import _collect_bnk_music_index, _extract_track_source_ids, _scan_bnk_music_objects, apply_track_patches_to_bnk

BANK_ID = 1376947663
TRACK_ID = 0x21F0B0D5
SECOND_TRACK_ID = 0x21F0B0D6
PLACEHOLDER_TRACK_ID = 0x21F0B0D7
SEGMENT_ID = 0x14874D4C
LOOP_SEGMENT_ID = 0x14874D4D
SWITCH_ID = 0x30000100
PLAYLIST_ID = 0x30000000
SFX_ID = 0x40000000
FIRST_SOURCE = 0x3C7B454C
SECOND_SOURCE = 0x3C7B454D
SFX_SOURCE = 0x3C7B4500
REMAPPED_SOURCE = 0x7A000001
MISSING_TRACK_ID = 0x7FFFFFFF
BANK_WEMS = {FIRST_SOURCE: make_wem(1, 40), 0x77: make_wem(2, 23)}
BANK_BASE_IN_PCK = 0x10000


def music_bank(first_track_props=(), second_track_props=(), first_source=FIRST_SOURCE, first_ms=5000.0, wems=None):
    return build_bnk(BANK_ID, wems=wems, hirc_objects=[
        music_track(TRACK_ID, [clip(first_source, duration=first_ms)], props=first_track_props, parent_id=SEGMENT_ID),
        music_segment(SEGMENT_ID, [TRACK_ID], first_ms),
        music_track(SECOND_TRACK_ID, [clip(SECOND_SOURCE, duration=8000.0)], props=second_track_props, parent_id=LOOP_SEGMENT_ID),
        music_segment(LOOP_SEGMENT_ID, [SECOND_TRACK_ID], 8000.0),
        music_track(PLACEHOLDER_TRACK_ID, [], source_ids=[]),
        music_ranseq_intro_loop(PLAYLIST_ID, SEGMENT_ID, LOOP_SEGMENT_ID),
        music_switch(SWITCH_ID, [PLAYLIST_ID]),
        sound(SFX_ID, SFX_SOURCE, props=[(VOLUME, -3.0)]),
    ])


def objects_by_id(bnk_bytes, bank_base=0):
    return {music_object["obj_id"]: music_object for music_object in _scan_bnk_music_objects(bnk_bytes, bank_base)}


def test_music_index_counts_music_objects_and_track_sources():
    two_source_track = music_track(TRACK_ID, [clip(SECOND_SOURCE)], source_ids=[FIRST_SOURCE, SECOND_SOURCE])
    bnk_bytes = build_bnk(BANK_ID, hirc_objects=[
        two_source_track,
        music_track(SECOND_TRACK_ID, [clip(REMAPPED_SOURCE)], source_ids=[]),
        music_segment(SEGMENT_ID, [TRACK_ID], 1000.0),
        music_ranseq_intro_loop(PLAYLIST_ID, SEGMENT_ID, SEGMENT_ID),
        music_switch(SWITCH_ID),
        sound(SFX_ID, SFX_SOURCE),
    ])

    music_count, source_ids, obj_ids = _collect_bnk_music_index(bnk_bytes)

    assert music_count == 5
    assert source_ids == {FIRST_SOURCE, SECOND_SOURCE, REMAPPED_SOURCE}
    assert obj_ids == {TRACK_ID, SECOND_TRACK_ID, SEGMENT_ID, PLAYLIST_ID, SWITCH_ID}


def test_scan_music_objects_describes_every_music_type():
    bnk_bytes = music_bank(first_track_props=[(VOLUME, -9.0)], second_track_props=[(PITCH, 100.0)], wems=BANK_WEMS)

    music_objects = objects_by_id(bnk_bytes, BANK_BASE_IN_PCK)

    assert {obj_id: music_object["type"] for obj_id, music_object in music_objects.items()} == {
        TRACK_ID: "MusicTrack",
        SEGMENT_ID: "MusicSegment",
        SECOND_TRACK_ID: "MusicTrack",
        LOOP_SEGMENT_ID: "MusicSegment",
        PLACEHOLDER_TRACK_ID: "MusicTrack",
        PLAYLIST_ID: "MusicRanSeqCntr",
        SWITCH_ID: "MusicSwitchCntr",
    }
    volume_fields = {
        obj_id: (music_object["has_volume"], music_object["volume_db"], music_object["volume_insertable"])
        for obj_id, music_object in music_objects.items()
    }
    assert volume_fields == {
        TRACK_ID: (True, -9.0, True),
        SEGMENT_ID: (False, None, False),
        SECOND_TRACK_ID: (False, None, True),
        LOOP_SEGMENT_ID: (False, None, False),
        PLACEHOLDER_TRACK_ID: (False, None, False),
        PLAYLIST_ID: (False, None, False),
        SWITCH_ID: (False, None, False),
    }
    assert not any(key.startswith("_") for music_object in music_objects.values() for key in music_object)


def test_scan_music_objects_reports_offsets_inside_the_pck():
    bnk_bytes = music_bank(first_track_props=[(VOLUME, -9.0)])

    first_track = objects_by_id(bnk_bytes, BANK_BASE_IN_PCK)[TRACK_ID]

    assert first_track["loop_ms"] == 5000.0
    assert [slot["source_id"] for slot in first_track["sources"] + first_track["playlist"]] == [FIRST_SOURCE, FIRST_SOURCE]
    for slot in first_track["sources"] + first_track["playlist"]:
        assert read_u32(bnk_bytes, slot["abs_offset_in_pck"] - BANK_BASE_IN_PCK) == FIRST_SOURCE
    assert read_f32(bnk_bytes, first_track["volume_offset_abs"] - BANK_BASE_IN_PCK) == -9.0
    assert read_f64(bnk_bytes, first_track["loop_duration_offset_abs"] - BANK_BASE_IN_PCK) == 5000.0
    assert first_track["loop_clear_offset_abs"] == first_track["playlist"][0]["abs_offset_in_pck"] + 4


def test_tracks_sharing_a_source_keep_their_own_volume():
    bnk_bytes = build_bnk(BANK_ID, hirc_objects=[
        music_track(TRACK_ID, [clip(FIRST_SOURCE)], props=[(VOLUME, -9.0)]),
        music_track(SECOND_TRACK_ID, [clip(FIRST_SOURCE)], props=[(VOLUME, -2.0)]),
    ])

    music_objects = objects_by_id(bnk_bytes)

    assert (music_objects[TRACK_ID]["volume_db"], music_objects[SECOND_TRACK_ID]["volume_db"]) == (-9.0, -2.0)


def test_extract_track_source_ids_reads_the_source_list():
    bnk_bytes = build_bnk(BANK_ID, hirc_objects=[
        sound(SFX_ID, SFX_SOURCE),
        music_track(TRACK_ID, [clip(SECOND_SOURCE)], source_ids=[FIRST_SOURCE, SECOND_SOURCE]),
    ])

    assert _extract_track_source_ids(bnk_bytes, TRACK_ID) == {FIRST_SOURCE, SECOND_SOURCE}
    assert _extract_track_source_ids(bnk_bytes, MISSING_TRACK_ID) == set()


def test_track_patches_need_a_mutable_bank():
    with pytest.raises(TypeError):
        apply_track_patches_to_bnk(music_bank(), [{"track_obj_id": TRACK_ID, "volume_db": -3.0}])


def test_no_track_patches_leave_the_bank_alone():
    bnk_bytes = bytearray(music_bank())

    assert apply_track_patches_to_bnk(bnk_bytes, []) == {"remaps": 0, "loops": 0, "volumes": 0}
    assert bytes(bnk_bytes) == music_bank()


def test_volume_patch_overwrites_an_existing_volume_in_place():
    bnk_bytes = bytearray(music_bank(first_track_props=[(VOLUME, -9.0)], wems=BANK_WEMS))

    result = apply_track_patches_to_bnk(bnk_bytes, [{"track_obj_id": TRACK_ID, "volume_db": -3.0}])

    assert result == {"remaps": 0, "loops": 0, "volumes": 1}
    assert bytes(bnk_bytes) == music_bank(first_track_props=[(VOLUME, -3.0)], wems=BANK_WEMS)


def test_volume_patch_inserts_a_missing_volume_and_grows_the_bank():
    original_bnk = music_bank(first_track_props=[(PITCH, 100.0)], wems=BANK_WEMS)
    bnk_bytes = bytearray(original_bnk)

    result = apply_track_patches_to_bnk(bnk_bytes, [{"track_obj_id": TRACK_ID, "volume_db": -4.5}])

    assert result == {"remaps": 0, "loops": 0, "volumes": 1}
    assert bytes(bnk_bytes) == music_bank(first_track_props=[(VOLUME, -4.5), (PITCH, 100.0)], wems=BANK_WEMS)
    assert len(bnk_bytes) == len(original_bnk) + 5
    assert BNKFile(bnk_bytes=bytes(bnk_bytes)).extract_wem(FIRST_SOURCE) == BANK_WEMS[FIRST_SOURCE]


def test_loop_patch_rewrites_the_clip_and_its_segment():
    bnk_bytes = bytearray(music_bank())

    result = apply_track_patches_to_bnk(bnk_bytes, [{"track_obj_id": TRACK_ID, "loop_ms": 7250.0}])

    assert result["loops"] > 0
    assert bytes(bnk_bytes) == music_bank(first_ms=7250.0)


def test_source_remap_rewrites_both_slots():
    bnk_bytes = bytearray(music_bank())
    remaps = [
        {"slot": "src", "index": 0, "old_source_id": FIRST_SOURCE, "new_source_id": REMAPPED_SOURCE},
        {"slot": "playlist", "index": 0, "old_source_id": FIRST_SOURCE, "new_source_id": REMAPPED_SOURCE},
    ]

    result = apply_track_patches_to_bnk(bnk_bytes, [{"track_obj_id": TRACK_ID, "source_remaps": remaps}])

    assert result == {"remaps": 2, "loops": 0, "volumes": 0}
    assert bytes(bnk_bytes) == music_bank(first_source=REMAPPED_SOURCE)


def test_source_remap_is_idempotent_and_skips_bad_descriptors():
    bnk_bytes = bytearray(music_bank())
    remaps = [
        {"slot": "src", "index": 0, "old_source_id": FIRST_SOURCE, "new_source_id": REMAPPED_SOURCE},
        {"slot": "playlist", "index": 0, "old_source_id": FIRST_SOURCE, "new_source_id": REMAPPED_SOURCE},
        {"slot": "playlist", "index": 3, "new_source_id": REMAPPED_SOURCE},
        {"slot": "src", "index": 0, "new_source_id": "not a number"},
    ]
    patches = [{"track_obj_id": TRACK_ID, "source_remaps": remaps}, {"track_obj_id": MISSING_TRACK_ID, "source_remaps": remaps}]
    apply_track_patches_to_bnk(bnk_bytes, patches)

    second_result = apply_track_patches_to_bnk(bnk_bytes, patches)

    assert second_result == {"remaps": 0, "loops": 0, "volumes": 0}
    assert bytes(bnk_bytes) == music_bank(first_source=REMAPPED_SOURCE)


def test_loop_patch_follows_a_remap_in_the_same_patch():
    bnk_bytes = bytearray(music_bank())
    remaps = [
        {"slot": "src", "index": 0, "new_source_id": REMAPPED_SOURCE},
        {"slot": "playlist", "index": 0, "new_source_id": REMAPPED_SOURCE},
    ]

    apply_track_patches_to_bnk(bnk_bytes, [{"track_obj_id": TRACK_ID, "source_remaps": remaps, "loop_ms": 6100.0, "volume_db": -2.0}])

    assert bytes(bnk_bytes) == music_bank(first_track_props=[(VOLUME, -2.0)], first_source=REMAPPED_SOURCE, first_ms=6100.0)
