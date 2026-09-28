import math
import struct

import pytest

from real_game.real_game_helpers import (
    GAME_IDS,
    audio_pcks,
    bank_pck_sample,
    by_size,
    copy_into,
    has_only_standard_chunks,
    installed_game,
    iter_banks,
    label,
    read_entries,
)
from src.gui.backend.audio_games.base_handler import BaseBrowserHandler
from src.wwise.bnk_handler import BNKFile
from src.wwise.hirc_music import _collect_bnk_music_index, _scan_bnk_music_objects, apply_track_patches_to_bnk
from src.wwise.hirc_patcher import scan_bank_for_patch_targets

pytestmark = pytest.mark.real_game

VOLUME_DB = -4.5


def music_banks(pcks):
    for pck in pcks:
        for bank, bnk_bytes in iter_banks(pck):
            if _collect_bnk_music_index(bnk_bytes)[0]:
                yield pck, bank, bnk_bytes


def read_double(content, offset):
    return struct.unpack_from("<d", content, offset)[0]


def track_source_ids(track):
    return {source["source_id"] for source in track["sources"] + track["playlist"]}


def tracks_with_private_sources(bnk_bytes):
    tracks = [music_object for music_object in _scan_bnk_music_objects(bnk_bytes, 0) if music_object["type"] == "MusicTrack"]
    for track in tracks:
        other_sources = set().union(*(track_source_ids(other) for other in tracks if other is not track))
        if track["sources"] and not track_source_ids(track) & other_sources:
            yield track


def find_music_track(game_dirs, predicate, description):
    for pck, bank, bnk_bytes in music_banks(bank_pck_sample(game_dirs)):
        if not has_only_standard_chunks(bnk_bytes):
            continue
        for track in tracks_with_private_sources(bnk_bytes):
            if predicate(track):
                return f"{label(pck, game_dirs)} bank {bank['id']}", bnk_bytes, track
    pytest.skip(f"no sampled MusicTrack {description} in {game_dirs.game_id}")


def track_summary(music_objects):
    return {
        music_object["obj_id"]: (music_object["has_volume"], music_object["volume_db"], music_object["loop_ms"], sorted(track_source_ids(music_object)))
        for music_object in music_objects
    }


def find_volume_insert_candidate(game_dirs):
    # The bank whose volume-less tracks use sources no other bank of its pck references, so only it may change.
    bank_pcks = [pck for pck in audio_pcks(game_dirs.streaming_root) if pck.name not in ("Patch.pck", "Hotfix.pck")]
    for pck in by_size(bank_pcks):
        banks = [(bank, bnk_bytes) for bank, bnk_bytes in iter_banks(pck) if _collect_bnk_music_index(bnk_bytes)[0]]
        sources_by_bank = {(bank["id"], bank["lang_id"]): _collect_bnk_music_index(bnk_bytes)[1] for bank, bnk_bytes in banks}
        for bank, bnk_bytes in banks:
            if not has_only_standard_chunks(bnk_bytes):
                continue
            bank_key = (bank["id"], bank["lang_id"])
            sources_elsewhere = set().union(*(sources for key, sources in sources_by_bank.items() if key != bank_key))
            hirc_chunk = bytearray(BNKFile(bnk_bytes=bnk_bytes).data["HIRC"].getdata())
            targets = scan_bank_for_patch_targets(hirc_chunk, sources_by_bank[bank_key] - sources_elsewhere)
            volume_less_patches = [patch for patch in targets.volume_patches if not patch.has_existing_volume]
            if volume_less_patches:
                inserted_bundles = {patch.prop_bundle_cProps_offset for patch in volume_less_patches}
                return pck, bank, {patch.source_id for patch in volume_less_patches}, len(inserted_bundles)
    pytest.skip(f"no volume-less MusicTrack in {game_dirs.game_id}")


@pytest.mark.parametrize("game_id", GAME_IDS)
def test_real_music_banks_scan_into_consistent_patch_targets(real_game_audio_dirs, game_id):
    game_dirs = installed_game(real_game_audio_dirs, game_id)
    problems = []
    track_count = 0
    for pck, bank, bnk_bytes in music_banks(bank_pck_sample(game_dirs)):
        bank_label = f"{label(pck, game_dirs)} bank {bank['id']}"
        music_count, source_ids, object_ids = _collect_bnk_music_index(bnk_bytes)
        music_objects = _scan_bnk_music_objects(bnk_bytes, 0)
        if len(music_objects) != music_count or {music_object["obj_id"] for music_object in music_objects} != object_ids:
            problems.append(f"{bank_label}: the music index and the object scan disagree")
        tracks = [music_object for music_object in music_objects if music_object["type"] == "MusicTrack"]
        track_count += len(tracks)
        for track in tracks:
            if track["loop_ms"] is not None and not (math.isfinite(track["loop_ms"]) and track["loop_ms"] >= 0):
                problems.append(f"{bank_label}: track {track['obj_id']} loop {track['loop_ms']}")
            if track["has_volume"] and not math.isfinite(track["volume_db"]):
                problems.append(f"{bank_label}: track {track['obj_id']} volume {track['volume_db']}")
        targets = scan_bank_for_patch_targets(bnk_bytes, source_ids)
        for clip in targets.tracks:
            play_at, duration = read_double(bnk_bytes, clip.fPlayAt_offset), read_double(bnk_bytes, clip.fSrcDuration_offset)
            if clip.source_id not in source_ids or not (math.isfinite(play_at) and math.isfinite(duration) and duration >= 0):
                problems.append(f"{bank_label}: clip of {clip.source_id} plays at {play_at} for {duration}")
        for segment in targets.segments:
            if not math.isfinite(read_double(bnk_bytes, segment.fDuration_offset)) or not segment.associated_source_ids <= source_ids:
                problems.append(f"{bank_label}: segment duration at {segment.fDuration_offset} is unreadable")
        for volume in targets.volume_patches:
            if not volume.volume_value_offset + 4 <= len(bnk_bytes) or bnk_bytes[volume.prop_bundle_cProps_offset] != volume.cProps:
                problems.append(f"{bank_label}: volume bundle of {volume.source_id} points outside its bank")
    assert track_count
    assert not problems, "\n".join(problems[:20])


@pytest.mark.parametrize(
    ("mode", "wants_existing_volume", "growth"),
    [("insert", False, 5), ("overwrite", True, 0)],
    ids=["insert", "overwrite"],
)
@pytest.mark.parametrize("game_id", GAME_IDS)
def test_real_track_volume_patch_touches_only_its_track(real_game_audio_dirs, game_id, mode, wants_existing_volume, growth):
    game_dirs = installed_game(real_game_audio_dirs, game_id)
    bank_label, bnk_bytes, track = find_music_track(
        game_dirs, lambda candidate: candidate["volume_insertable"] and candidate["has_volume"] == wants_existing_volume,
        f"that needs a volume {mode}",
    )
    patched = bytearray(bnk_bytes)

    result = apply_track_patches_to_bnk(patched, [{"track_obj_id": track["obj_id"], "volume_db": VOLUME_DB}])

    assert result == {"remaps": 0, "loops": 0, "volumes": 1}, bank_label
    assert len(patched) == len(bnk_bytes) + growth
    before = track_summary(_scan_bnk_music_objects(bnk_bytes, 0))
    after = track_summary(_scan_bnk_music_objects(bytes(patched), 0))
    assert after.pop(track["obj_id"])[:2] == (True, pytest.approx(VOLUME_DB))
    before.pop(track["obj_id"])
    assert after == before
    patched_bnk, original_bnk = BNKFile(bnk_bytes=bytes(patched)), BNKFile(bnk_bytes=bnk_bytes)
    assert patched_bnk.get_bytes() == bytes(patched)
    assert [patched_bnk.extract_wem(wem_id) for wem_id in patched_bnk.list_wems()] == [original_bnk.extract_wem(wem_id) for wem_id in original_bnk.list_wems()]


@pytest.mark.parametrize("game_id", GAME_IDS)
def test_real_track_loop_patch_sets_the_clip_duration_in_place(real_game_audio_dirs, game_id):
    game_dirs = installed_game(real_game_audio_dirs, game_id)
    bank_label, bnk_bytes, track = find_music_track(
        game_dirs, lambda candidate: len(candidate["playlist"]) == 1 and candidate["loop_ms"], "with a single clip",
    )
    new_loop_ms = round(track["loop_ms"]) + 1234.0
    patched = bytearray(bnk_bytes)

    result = apply_track_patches_to_bnk(patched, [{"track_obj_id": track["obj_id"], "loop_ms": new_loop_ms}])

    assert result["loops"] >= 1, bank_label
    assert len(patched) == len(bnk_bytes)
    patched_track = next(music_object for music_object in _scan_bnk_music_objects(bytes(patched), 0) if music_object["obj_id"] == track["obj_id"])
    assert patched_track["loop_ms"] == new_loop_ms
    event_id_offset = patched_track["loop_clear_offset_abs"]
    assert patched[event_id_offset : event_id_offset + 4] == bytes(4)
    assert patched[event_id_offset + 12 : event_id_offset + 28] == bytes(16)


@pytest.mark.parametrize("game_id", GAME_IDS)
def test_real_volume_insert_rebuild_changes_only_the_patched_bank(real_game_audio_dirs, game_id, tmp_path):
    game_dirs = installed_game(real_game_audio_dirs, game_id)
    source, bank, volume_less_sources, inserted_bundles = find_volume_insert_candidate(game_dirs)
    original = copy_into(source, tmp_path / "original")
    target = tmp_path / "persistent" / source.name

    rebuilt = BaseBrowserHandler._rebuild_pck_with_hirc_patches(
        original.read_bytes(), target, original, volume_less_sources, {}, {source_id: VOLUME_DB for source_id in volume_less_sources}, set(),
    )

    assert rebuilt
    original_entries, rebuilt_entries = read_entries(original), read_entries(target)
    bank_key = ("banks", bank["id"], bank["lang_id"])
    assert rebuilt_entries.keys() == original_entries.keys()
    assert [key for key in original_entries if rebuilt_entries[key] != original_entries[key]] == [bank_key]
    patched_bytes = rebuilt_entries[bank_key]
    assert len(patched_bytes) - len(original_entries[bank_key]) == 5 * inserted_bundles
    patched_bnk = BNKFile(bnk_bytes=patched_bytes)
    assert patched_bnk.get_bytes() == patched_bytes
    hirc_chunk = bytearray(patched_bnk.data["HIRC"].getdata())
    volumes = {
        patch.source_id: struct.unpack_from("<f", hirc_chunk, patch.volume_value_offset)[0]
        for patch in scan_bank_for_patch_targets(hirc_chunk, volume_less_sources).volume_patches
        if patch.has_existing_volume
    }
    assert volumes == {source_id: pytest.approx(VOLUME_DB) for source_id in volume_less_sources}
    assert sorted(path.name for path in target.parent.iterdir()) == [source.name]
