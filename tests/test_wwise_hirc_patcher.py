from io import BytesIO

import pytest

from helpers import build_bnk, build_pck, make_wem
from hirc_builders import (
    END_MARKER_ID,
    ENTRY_MARKER_ID,
    LOW_PASS_FILTER,
    MUSIC_TRACK,
    PITCH,
    VOLUME,
    clip,
    music_ranseq_intro_loop,
    music_segment,
    music_track,
    read_f32,
    read_f64,
    read_u32,
    sound,
)
from src.wwise.bnk_handler import BNKFile
from src.wwise.hirc_patcher import apply_duration_patches, apply_volume_inserts, apply_volume_patches, scan_bank_for_patch_targets

BANK_ID = 1376947663
TRACK_ID = 0x21F0B0D5
LOOP_TRACK_ID = 0x21F0B0D6
THIRD_TRACK_ID = 0x21F0B0D7
SEGMENT_ID = 0x14874D4C
LOOP_SEGMENT_ID = 0x14874D4D
PLAYLIST_ID = 0x30000000
SFX_ID = 0x40000000
INTRO_SOURCE = 0x3C7B454C
LOOP_SOURCE = 0x3C7B454D
THIRD_SOURCE = 0x3C7B454E
UNUSED_SOURCE = 0x3C7B45FF
BANK_WEMS = {INTRO_SOURCE: make_wem(1, 40), 0x77: make_wem(2, 23)}
TRACK_SHAPES = [(0, ()), (2, ()), (0, (3,)), (1, (2, 5))]
TRACK_SHAPE_IDS = ["plain", "effects", "clip_automation", "effects_and_automation"]


def intro_loop_bank(intro_ms, loop_ms, segment_ms, loop_play_at=None, split_tracks=False, entry_ms=0.0):
    loop_play_at = intro_ms if loop_play_at is None else loop_play_at
    intro_clip = clip(INTRO_SOURCE, 0.0, intro_ms)
    loop_clip = clip(LOOP_SOURCE, loop_play_at, loop_ms)
    if split_tracks:
        tracks = [music_track(TRACK_ID, [intro_clip], parent_id=SEGMENT_ID), music_track(LOOP_TRACK_ID, [loop_clip], parent_id=SEGMENT_ID)]
    else:
        tracks = [music_track(TRACK_ID, [intro_clip, loop_clip], parent_id=SEGMENT_ID)]
    child_ids = [TRACK_ID, LOOP_TRACK_ID] if split_tracks else [TRACK_ID]
    return build_bnk(BANK_ID, hirc_objects=[*tracks, music_segment(SEGMENT_ID, child_ids, segment_ms, entry_marker_position=entry_ms)])


def single_clip_bank(clip_ms, segment_ms, entry_ms=0.0, **clip_fields):
    track = music_track(TRACK_ID, [clip(INTRO_SOURCE, duration=clip_ms, **clip_fields)], parent_id=SEGMENT_ID)
    return build_bnk(BANK_ID, hirc_objects=[track, music_segment(SEGMENT_ID, [TRACK_ID], segment_ms, entry_marker_position=entry_ms)])


def layered_bank(intro_ms, loop_ms, segment_ms, entry_ms):
    # Two lanes that both start at 0, like the HSR layers that share a pickup before the entry cue.
    return build_bnk(BANK_ID, hirc_objects=[
        music_track(TRACK_ID, [clip(INTRO_SOURCE, 0.0, intro_ms)], parent_id=SEGMENT_ID),
        music_track(LOOP_TRACK_ID, [clip(LOOP_SOURCE, 0.0, loop_ms)], parent_id=SEGMENT_ID),
        music_segment(SEGMENT_ID, [TRACK_ID, LOOP_TRACK_ID], segment_ms, entry_marker_position=entry_ms),
    ])


def intro_loop_playlist_bank(intro_ms, loop_ms):
    return build_bnk(BANK_ID, hirc_objects=[
        music_track(TRACK_ID, [clip(INTRO_SOURCE, 0.0, intro_ms)], parent_id=SEGMENT_ID),
        music_segment(SEGMENT_ID, [TRACK_ID], intro_ms),
        music_track(LOOP_TRACK_ID, [clip(LOOP_SOURCE, 0.0, loop_ms)], parent_id=LOOP_SEGMENT_ID),
        music_segment(LOOP_SEGMENT_ID, [LOOP_TRACK_ID], loop_ms),
        music_ranseq_intro_loop(PLAYLIST_ID, SEGMENT_ID, LOOP_SEGMENT_ID),
    ])


def volume_bank(intro_track_props, loop_track_props=(), third_track_props=(), shape=(0, ()), wems=None):
    fx_count, automation_point_counts = shape
    return build_bnk(BANK_ID, wems=wems, hirc_objects=[
        music_track(TRACK_ID, [clip(INTRO_SOURCE)], props=intro_track_props, fx_count=fx_count, automation_point_counts=automation_point_counts),
        music_track(LOOP_TRACK_ID, [clip(LOOP_SOURCE)], props=loop_track_props),
        music_track(THIRD_TRACK_ID, [clip(THIRD_SOURCE)], props=third_track_props),
        music_segment(SEGMENT_ID, [TRACK_ID, LOOP_TRACK_ID, THIRD_TRACK_ID], 1000.0),
    ])


def patch_durations(bnk_bytes, duration_ms_by_source):
    patched_bnk = bytearray(bnk_bytes)
    targets = scan_bank_for_patch_targets(patched_bnk, set(duration_ms_by_source))
    result = apply_duration_patches(patched_bnk, targets, duration_ms_by_source)
    return bytes(patched_bnk), result


def insert_volumes(bnk_bytes, volume_db_by_source):
    # Callers insert into the HIRC chunk alone and let BNKFile reframe the chunk size.
    bank = BNKFile(bnk_bytes=bnk_bytes)
    hirc_chunk = bytearray(bank.data["HIRC"].getdata())
    targets = scan_bank_for_patch_targets(hirc_chunk, set(volume_db_by_source))
    result = apply_volume_inserts(hirc_chunk, targets.volume_patches, volume_db_by_source)
    bank.data["HIRC"].data = BytesIO(bytes(hirc_chunk[12:]))
    return bank.get_bytes(), result


def test_scan_reports_clip_fields_and_the_linked_segment():
    bnk_bytes = intro_loop_bank(12215.0, 103473.0, 115688.0)

    targets = scan_bank_for_patch_targets(bnk_bytes, {INTRO_SOURCE, LOOP_SOURCE})

    clip_fields = [(read_u32(bnk_bytes, track.clear_region_offset - 4), read_f64(bnk_bytes, track.fPlayAt_offset), read_f64(bnk_bytes, track.fSrcDuration_offset)) for track in targets.tracks]
    assert clip_fields == [(INTRO_SOURCE, 0.0, 12215.0), (LOOP_SOURCE, 12215.0, 103473.0)]
    assert [track.source_id for track in targets.tracks] == [INTRO_SOURCE, LOOP_SOURCE]
    (segment,) = targets.segments
    assert segment.associated_source_ids == {INTRO_SOURCE, LOOP_SOURCE}
    assert segment.member_clips == targets.tracks
    assert read_f64(bnk_bytes, segment.fDuration_offset) == 115688.0
    assert read_u32(bnk_bytes, segment.end_marker_fPos_offset - 4) == END_MARKER_ID
    assert read_f64(bnk_bytes, segment.end_marker_fPos_offset) == 115688.0
    assert read_u32(bnk_bytes, segment.entry_marker_fPos_offset - 4) == ENTRY_MARKER_ID


def test_scan_finds_the_end_marker_after_a_named_marker():
    track = music_track(TRACK_ID, [clip(INTRO_SOURCE, duration=5000.0)])
    bnk_bytes = build_bnk(BANK_ID, hirc_objects=[
        track, music_segment(SEGMENT_ID, [TRACK_ID], 4800.0, entry_marker_name=b"LoopStart", entry_marker_position=250.0),
    ])

    (segment,) = scan_bank_for_patch_targets(bnk_bytes, {INTRO_SOURCE}).segments

    assert read_f64(bnk_bytes, segment.fDuration_offset) == 4800.0
    assert read_f64(bnk_bytes, segment.end_marker_fPos_offset) == 4800.0
    assert read_f64(bnk_bytes, segment.entry_marker_fPos_offset) == 250.0


@pytest.mark.parametrize("source_ids", [set(), {UNUSED_SOURCE}])
def test_scan_without_matching_sources_finds_nothing(source_ids):
    targets = scan_bank_for_patch_targets(intro_loop_bank(12215.0, 103473.0, 115688.0), source_ids)

    assert (targets.tracks, targets.segments, targets.volume_patches) == ([], [], [])


def test_scan_links_only_segments_listing_the_track():
    bnk_bytes = build_bnk(BANK_ID, hirc_objects=[
        music_track(TRACK_ID, [clip(INTRO_SOURCE, duration=2000.0)]),
        music_track(LOOP_TRACK_ID, [clip(LOOP_SOURCE, duration=3000.0)]),
        music_segment(SEGMENT_ID, [LOOP_TRACK_ID], 3000.0),
        music_segment(LOOP_SEGMENT_ID, [TRACK_ID], 2000.0),
    ])

    targets = scan_bank_for_patch_targets(bnk_bytes, {INTRO_SOURCE})

    (segment,) = targets.segments
    assert segment.associated_source_ids == {INTRO_SOURCE}
    assert read_f64(bnk_bytes, segment.fDuration_offset) == 2000.0


def test_scan_offsets_are_absolute_inside_a_whole_pck():
    first_bank = intro_loop_bank(12215.0, 103473.0, 115688.0)
    second_bank = build_bnk(BANK_ID + 1, wems=BANK_WEMS, hirc_objects=[
        music_track(THIRD_TRACK_ID, [clip(THIRD_SOURCE, duration=7000.0)], props=[(VOLUME, -9.0)]),
        music_segment(LOOP_SEGMENT_ID, [THIRD_TRACK_ID], 7000.0),
    ])
    pck_bytes = build_pck(banks=[(BANK_ID, 0, first_bank), (BANK_ID + 1, 0, second_bank)], block_size=16)

    targets = scan_bank_for_patch_targets(pck_bytes, {LOOP_SOURCE, THIRD_SOURCE})

    assert [(track.source_id, read_f64(pck_bytes, track.fSrcDuration_offset)) for track in targets.tracks] == [(LOOP_SOURCE, 103473.0), (THIRD_SOURCE, 7000.0)]
    assert sorted(read_f64(pck_bytes, segment.fDuration_offset) for segment in targets.segments) == [7000.0, 115688.0]
    existing_volumes = {patch.source_id: read_f32(pck_bytes, patch.volume_value_offset) for patch in targets.volume_patches if patch.has_existing_volume}
    assert existing_volumes == {THIRD_SOURCE: -9.0}


@pytest.mark.parametrize("shape", TRACK_SHAPES, ids=TRACK_SHAPE_IDS)
def test_scan_reports_each_track_volume_bundle(shape):
    bnk_bytes = volume_bank([(VOLUME, -9.0)], [(PITCH, 100.0), (LOW_PASS_FILTER, 20.0)], [], shape=shape)

    volume_patches = {patch.source_id: patch for patch in scan_bank_for_patch_targets(bnk_bytes, {INTRO_SOURCE, LOOP_SOURCE, THIRD_SOURCE}).volume_patches}

    assert {source_id: (patch.has_existing_volume, patch.cProps) for source_id, patch in volume_patches.items()} == {
        INTRO_SOURCE: (True, 1),
        LOOP_SOURCE: (False, 2),
        THIRD_SOURCE: (False, 0),
    }
    assert read_f32(bnk_bytes, volume_patches[INTRO_SOURCE].volume_value_offset) == -9.0
    for patch in volume_patches.values():
        assert bnk_bytes[patch.prop_bundle_cProps_offset] == patch.cProps
        assert patch.ids_start_offset == patch.prop_bundle_cProps_offset + 1
        assert bnk_bytes[patch.object_size_field_offset - 1] == MUSIC_TRACK


def test_apply_volume_patches_overwrites_only_existing_volumes():
    patched_bnk = bytearray(volume_bank([(VOLUME, -9.0)], [(PITCH, 100.0)]))
    targets = scan_bank_for_patch_targets(patched_bnk, {INTRO_SOURCE, LOOP_SOURCE, THIRD_SOURCE})

    result = apply_volume_patches(patched_bnk, targets.volume_patches, {INTRO_SOURCE: -3.0, LOOP_SOURCE: -6.0})

    assert result == {"patched": 1, "inserted": 0, "total_shift": 0}
    assert bytes(patched_bnk) == volume_bank([(VOLUME, -3.0)], [(PITCH, 100.0)])


def test_volume_patch_only_touches_music_tracks():
    shared_source = INTRO_SOURCE
    sfx_only_bank = build_bnk(BANK_ID, hirc_objects=[sound(SFX_ID, shared_source, props=[(VOLUME, -3.0)])])
    mixed_bank = build_bnk(BANK_ID, hirc_objects=[
        sound(SFX_ID, shared_source, props=[(VOLUME, -3.0)]),
        music_track(TRACK_ID, [clip(shared_source)], props=[(VOLUME, -9.0)]),
    ])
    patched_bnk = bytearray(mixed_bank)
    targets = scan_bank_for_patch_targets(patched_bnk, {shared_source})

    apply_volume_patches(patched_bnk, targets.volume_patches, {shared_source: -12.0})

    assert scan_bank_for_patch_targets(sfx_only_bank, {shared_source}).volume_patches == []
    assert bytes(patched_bnk) == build_bnk(BANK_ID, hirc_objects=[
        sound(SFX_ID, shared_source, props=[(VOLUME, -3.0)]),
        music_track(TRACK_ID, [clip(shared_source)], props=[(VOLUME, -12.0)]),
    ])


@pytest.mark.parametrize("shape", TRACK_SHAPES, ids=TRACK_SHAPE_IDS)
@pytest.mark.parametrize("existing_props", [[], [(PITCH, 100.0)], [(PITCH, 100.0), (LOW_PASS_FILTER, 20.0)]], ids=["empty_bundle", "one_prop", "two_props"])
def test_volume_insert_matches_a_native_volume_bundle(shape, existing_props):
    original_bnk = volume_bank(existing_props, shape=shape, wems=BANK_WEMS)

    patched_bnk, result = insert_volumes(original_bnk, {INTRO_SOURCE: -4.5})

    assert result == {"patched": 0, "inserted": 1, "total_shift": 5}
    assert patched_bnk == volume_bank([(VOLUME, -4.5), *existing_props], shape=shape, wems=BANK_WEMS)
    assert len(patched_bnk) == len(original_bnk) + 5
    (reparsed_patch,) = [patch for patch in scan_bank_for_patch_targets(patched_bnk, {INTRO_SOURCE}).volume_patches]
    assert reparsed_patch.has_existing_volume
    assert read_f32(patched_bnk, reparsed_patch.volume_value_offset) == -4.5


def test_volume_insert_keeps_every_offset_valid_across_several_tracks():
    original_bnk = volume_bank([], [(PITCH, 100.0)], [(VOLUME, -9.0)])

    patched_bnk, result = insert_volumes(original_bnk, {INTRO_SOURCE: -1.0, LOOP_SOURCE: -2.0, THIRD_SOURCE: -3.0})

    assert result["inserted"] == 2
    assert patched_bnk == volume_bank([(VOLUME, -1.0)], [(VOLUME, -2.0), (PITCH, 100.0)], [(VOLUME, -9.0)])


def test_volume_insert_adds_one_prop_per_track_shared_by_several_sources():
    two_clip_track = music_track(TRACK_ID, [clip(INTRO_SOURCE), clip(LOOP_SOURCE, play_at=1000.0)])
    original_bnk = build_bnk(BANK_ID, hirc_objects=[two_clip_track])

    patched_bnk, result = insert_volumes(original_bnk, {INTRO_SOURCE: -4.5, LOOP_SOURCE: -4.5})

    assert result["inserted"] == 1
    assert patched_bnk == build_bnk(BANK_ID, hirc_objects=[
        music_track(TRACK_ID, [clip(INTRO_SOURCE), clip(LOOP_SOURCE, play_at=1000.0)], props=[(VOLUME, -4.5)]),
    ])


@pytest.mark.parametrize("split_tracks", [False, True], ids=["one_track", "two_tracks"])
def test_duration_patch_re_times_a_concatenated_intro_and_loop(split_tracks):
    patched_bnk, result = patch_durations(
        intro_loop_bank(12215.0, 103473.0, 115688.0, split_tracks=split_tracks),
        {INTRO_SOURCE: 10000.0, LOOP_SOURCE: 90000.0},
    )

    assert patched_bnk == intro_loop_bank(10000.0, 90000.0, 100000.0, split_tracks=split_tracks)
    assert result["patched_source_ids"] == {INTRO_SOURCE, LOOP_SOURCE}


def test_duration_patch_on_the_loop_keeps_the_intro_schedule():
    patched_bnk, result = patch_durations(intro_loop_bank(12215.0, 103473.0, 115688.0), {LOOP_SOURCE: 90000.0})

    assert patched_bnk == intro_loop_bank(12215.0, 90000.0, 102215.0)
    assert result["patched_source_ids"] == {LOOP_SOURCE}


@pytest.mark.parametrize("split_tracks", [False, True], ids=["one_track", "two_tracks"])
def test_duration_patch_on_the_intro_re_times_the_loop(split_tracks):
    patched_bnk, result = patch_durations(intro_loop_bank(12215.0, 103473.0, 115688.0, split_tracks=split_tracks), {INTRO_SOURCE: 15000.0})

    assert patched_bnk == intro_loop_bank(15000.0, 103473.0, 118473.0, split_tracks=split_tracks)
    assert result["patched_source_ids"] == {INTRO_SOURCE, LOOP_SOURCE}


def clip_play_ats(bnk_bytes, source_id):
    return [read_f64(bnk_bytes, track.fPlayAt_offset) for track in scan_bank_for_patch_targets(bnk_bytes, {source_id}).tracks]


def segment_duration(bnk_bytes, source_id):
    return read_f64(bnk_bytes, scan_bank_for_patch_targets(bnk_bytes, {source_id}).segments[0].fDuration_offset)


def test_duration_patch_on_one_layer_leaves_the_parallel_layers_in_place():
    # A lane replaced at 0 must not drag another lane that only happens to start where it ends.
    layered_bank = build_bnk(BANK_ID, hirc_objects=[
        music_track(TRACK_ID, [clip(INTRO_SOURCE, 0.0, 3000.0)], parent_id=SEGMENT_ID),
        music_track(LOOP_TRACK_ID, [clip(LOOP_SOURCE, 3000.0, 3000.0)], parent_id=SEGMENT_ID),
        music_track(THIRD_TRACK_ID, [clip(THIRD_SOURCE, 0.0, 6000.0)], parent_id=SEGMENT_ID),
        music_segment(SEGMENT_ID, [TRACK_ID, LOOP_TRACK_ID, THIRD_TRACK_ID], 6000.0),
    ])

    patched_bnk, _ = patch_durations(layered_bank, {INTRO_SOURCE: 2400.0})

    assert clip_play_ats(patched_bnk, LOOP_SOURCE) == [3000.0]
    assert clip_play_ats(patched_bnk, THIRD_SOURCE) == [0.0]
    assert segment_duration(patched_bnk, THIRD_SOURCE) == 6000.0


def test_duration_patch_keeps_the_crossfade_between_a_replaced_intro_and_its_loop():
    crossfaded_bank = intro_loop_bank(8013.9, 85347.2, 93347.2, loop_play_at=8000.0, split_tracks=True)

    patched_bnk, result = patch_durations(crossfaded_bank, {INTRO_SOURCE: 10000.0})

    assert clip_play_ats(patched_bnk, LOOP_SOURCE) == [pytest.approx(9986.1)]
    assert segment_duration(patched_bnk, LOOP_SOURCE) == pytest.approx(95333.3)
    assert result["patched_source_ids"] == {INTRO_SOURCE, LOOP_SOURCE}


def test_duration_patch_reads_a_trimmed_loop_end_as_the_segment_end():
    trimmed_loop_bank = build_bnk(BANK_ID, hirc_objects=[
        music_track(TRACK_ID, [clip(INTRO_SOURCE, 0.0, 3107.1)], parent_id=SEGMENT_ID),
        music_track(LOOP_TRACK_ID, [clip(LOOP_SOURCE, 3096.8, 58861.6, end_trim=-22.9)], parent_id=SEGMENT_ID),
        music_segment(SEGMENT_ID, [TRACK_ID, LOOP_TRACK_ID], 61935.5),
    ])

    patched_bnk, _ = patch_durations(trimmed_loop_bank, {LOOP_SOURCE: 47089.3})

    assert clip_play_ats(patched_bnk, LOOP_SOURCE) == [3096.8]
    assert segment_duration(patched_bnk, LOOP_SOURCE) == pytest.approx(3096.8 + 47089.3)


def test_duration_patch_does_not_chain_switch_alternatives():
    alternatives_bank = build_bnk(BANK_ID, hirc_objects=[
        music_track(TRACK_ID, [clip(INTRO_SOURCE, 0.0, 12215.0), clip(LOOP_SOURCE, 12215.0, 103473.0)], parent_id=SEGMENT_ID, subtrack_count=2),
        music_segment(SEGMENT_ID, [TRACK_ID], 115688.0),
    ])

    patched_bnk, _ = patch_durations(alternatives_bank, {INTRO_SOURCE: 15000.0})

    assert clip_play_ats(patched_bnk, LOOP_SOURCE) == [12215.0]
    assert segment_duration(patched_bnk, LOOP_SOURCE) == 115688.0


def test_duration_patch_keeps_the_musical_length_of_a_loop_with_tail():
    patched_bnk, result = patch_durations(intro_loop_bank(12215.0, 103473.0, 110000.0), {INTRO_SOURCE: 10000.0, LOOP_SOURCE: 90000.0})

    assert patched_bnk == intro_loop_bank(10000.0, 90000.0, 110000.0, loop_play_at=12215.0)
    assert result["patched_source_ids"] == {INTRO_SOURCE, LOOP_SOURCE}


@pytest.mark.parametrize(
    "segment_ms, expected_segment_ms",
    [(10761.0, 12000.0), (10762.5, 12000.0), (10153.0, 10153.0)],
    ids=["concatenation", "within_tolerance", "loop_with_tail"],
)
def test_duration_patch_on_a_single_clip_segment(segment_ms, expected_segment_ms):
    patched_bnk, _ = patch_durations(single_clip_bank(10761.0, segment_ms), {INTRO_SOURCE: 12000.0})

    assert patched_bnk == single_clip_bank(12000.0, expected_segment_ms)


def test_duration_patch_moves_play_at_to_the_audible_start_and_clears_event_id_and_trims():
    original_bnk = single_clip_bank(10000.0, 9813.23, play_at=500.0, begin_trim=250.0, end_trim=-686.77, event_id=77)

    patched_bnk, _ = patch_durations(original_bnk, {INTRO_SOURCE: 12000.0})

    assert patched_bnk == single_clip_bank(12000.0, 12750.0, play_at=750.0)


def test_duration_patch_starts_the_new_audio_where_a_trimmed_lead_in_ended():
    # GI Banks1 bnk 207114398 track 853216092 trims a lead-in off a clip placed before the segment start.
    original_bnk = single_clip_bank(255000.0, 253048.78, play_at=-1951.22, begin_trim=1951.22)

    patched_bnk, _ = patch_durations(original_bnk, {INTRO_SOURCE: 157544.0})

    assert patched_bnk == single_clip_bank(157544.0, 157544.0)


def test_duration_patch_reads_an_end_trim_on_the_segment_end_as_a_concatenation():
    # GI Banks1 bnk 207114398 track 439374376 was taken for a loop-with-tail and kept a 16 s gap before its exit cue.
    original_bnk = single_clip_bank(241296.771, 240000.104, end_trim=-1296.667)

    patched_bnk, _ = patch_durations(original_bnk, {INTRO_SOURCE: 218410.0})

    assert patched_bnk == single_clip_bank(218410.0, 218410.0)


def test_duration_patch_moves_an_entry_cue_inside_a_replaced_clip_to_its_start():
    # Without pre-entry the audio before the entry cue is skipped, so the replacement must not start before it.
    patched_bnk, _ = patch_durations(single_clip_bank(10000.0, 10000.0, entry_ms=761.4), {INTRO_SOURCE: 12000.0})

    assert patched_bnk == single_clip_bank(12000.0, 12000.0)


def test_duration_patch_plays_a_replacement_of_a_trimmed_clip_whole_from_the_entry_cue():
    # GI Banks1 bnk 207114398 track 596725186 has a trimmed lead-in, an end trim on the segment end and its entry cue at 370 ms.
    original_bnk = single_clip_bank(253141.333, 247888.889, entry_ms=370.37, play_at=-1111.111, begin_trim=1111.111, end_trim=-4141.333)

    patched_bnk, _ = patch_durations(original_bnk, {INTRO_SOURCE: 218279.0})

    assert patched_bnk == single_clip_bank(218279.0, 218279.0)


def test_duration_patch_re_times_the_loop_after_a_trimmed_intro():
    # HSR Banks28 segment 382947072 trims its intro from a clip placed before the segment start.
    original_bnk = build_bnk(BANK_ID, hirc_objects=[
        music_track(TRACK_ID, [clip(INTRO_SOURCE, -4067.5, 16067.5, begin_trim=4067.5)], parent_id=SEGMENT_ID),
        music_track(LOOP_TRACK_ID, [clip(LOOP_SOURCE, 12000.0, 100000.0)], parent_id=SEGMENT_ID),
        music_segment(SEGMENT_ID, [TRACK_ID, LOOP_TRACK_ID], 112000.0),
    ])

    patched_bnk, _ = patch_durations(original_bnk, {INTRO_SOURCE: 15000.0})

    assert patched_bnk == intro_loop_bank(15000.0, 100000.0, 115000.0, split_tracks=True)


@pytest.mark.parametrize(
    "durations, expected_bnk",
    [
        ({INTRO_SOURCE: 6000.0}, intro_loop_bank(6000.0, 100000.0, 106000.0, entry_ms=6000.0)),
        ({LOOP_SOURCE: 90000.0}, intro_loop_bank(4700.0, 90000.0, 94700.0, entry_ms=4700.0)),
        ({INTRO_SOURCE: 6000.0, LOOP_SOURCE: 90000.0}, intro_loop_bank(6000.0, 90000.0, 96000.0, entry_ms=6000.0)),
    ],
    ids=["intro", "loop", "both"],
)
def test_duration_patch_keeps_the_entry_cue_on_the_loop_after_an_intro_in_pre_entry(durations, expected_bnk):
    # GI Banks15 bnk 2087051407 plays its intro only as pre-entry, and every loop enters where the loop clip starts.
    patched_bnk, _ = patch_durations(intro_loop_bank(4700.0, 100000.0, 104700.0, entry_ms=4700.0), durations)

    assert patched_bnk == expected_bnk


@pytest.mark.parametrize(
    "durations, expected_bnk",
    [
        ({INTRO_SOURCE: 5000.0}, layered_bank(5000.0, 8000.0, 8000.0, entry_ms=375.0)),
        ({INTRO_SOURCE: 5000.0, LOOP_SOURCE: 9000.0}, layered_bank(5000.0, 9000.0, 9000.0, entry_ms=0.0)),
    ],
    ids=["one_layer", "every_layer"],
)
def test_duration_patch_leaves_the_entry_cue_on_an_untouched_layer(durations, expected_bnk):
    # HSR Banks10 bnk 1376947663 has two layers that share a pickup before the entry cue.
    patched_bnk, _ = patch_durations(layered_bank(3429.1, 8000.0, 8000.0, entry_ms=375.0), durations)

    assert patched_bnk == expected_bnk


@pytest.mark.parametrize(
    "original_bnk, durations",
    [
        (intro_loop_bank(12215.0, 103473.0, 115688.0), {INTRO_SOURCE: 10000.0, LOOP_SOURCE: 90000.0}),
        (single_clip_bank(253141.333, 247888.889, entry_ms=370.37, play_at=-1111.111, begin_trim=1111.111, end_trim=-4141.333), {INTRO_SOURCE: 218279.0}),
        (intro_loop_bank(4700.0, 100000.0, 104700.0, entry_ms=4700.0), {INTRO_SOURCE: 6000.0}),
    ],
    ids=["intro_loop", "trimmed_clip_with_entry_cue", "intro_in_pre_entry"],
)
def test_duration_patch_is_idempotent(original_bnk, durations):
    once_patched_bnk, _ = patch_durations(original_bnk, durations)

    twice_patched_bnk, result = patch_durations(once_patched_bnk, durations)

    assert twice_patched_bnk == once_patched_bnk
    assert result == {"patched_offsets": 0, "patched_source_ids": set()}


def test_duration_patch_handles_each_segment_of_an_intro_loop_playlist():
    patched_bnk, result = patch_durations(intro_loop_playlist_bank(12215.0, 103473.0), {INTRO_SOURCE: 10000.0, LOOP_SOURCE: 90000.0})

    assert patched_bnk == intro_loop_playlist_bank(10000.0, 90000.0)
    assert result["patched_source_ids"] == {INTRO_SOURCE, LOOP_SOURCE}
