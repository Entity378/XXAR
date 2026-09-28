import json
import os

import pytest

from helpers import build_pck, make_game_install
from overlay_builders import (
    bank,
    distinct_pck,
    hash_sidecar_name,
    md5_hex,
    pkg_version_line,
    sound,
    with_bank_ids_zeroed,
    write_hash_sidecar,
    write_pkg_version,
)
from src.core.config_manager import get_game_state_dir
from src.mods import persistent_originals
from src.mods.persistent_originals import (
    cleanup_persistent_overlay,
    load_manifest_md5s,
    locate_pck_paths,
    promote_originals,
    relocate_orphan_sidecars,
    remove_misplaced_copies,
)
from src.wwise import patch_backup

ORIGINAL = distinct_pck(1)
MODDED = distinct_pck(2)
UPDATED_ORIGINAL = distinct_pck(3)
LARGER_MOD = distinct_pck(4, size=160)
REL = "Full/Streamed_SFX_2.pck"
VOICE_REL = "English/External0.pck"
EMPTY_STATS = {"promoted": 0, "updated": 0, "kept_mod": 0, "orphan": 0, "conflict": 0}


def run_cleanup(install, modded_keys=()):
    return cleanup_persistent_overlay(install.game.id, install.streaming_root, install.persistent_root, set(modded_keys))


def run_promote(install, modded_keys=()):
    return promote_originals(install.game.id, install.streaming_root, install.persistent_root, set(modded_keys))


def overlay_counts(result):
    return {key: result[key] for key in ("promoted", "updated", "kept_mod", "orphan", "conflict", "deleted", "kept")}


def counts(promoted=0, updated=0, kept_mod=0, orphan=0, conflict=0, deleted=0, kept=0):
    return {"promoted": promoted, "updated": updated, "kept_mod": kept_mod, "orphan": orphan,
            "conflict": conflict, "deleted": deleted, "kept": kept}


def read_or_none(path):
    if not path.exists():
        return None
    return path.read_bytes()


def sidecar_names(folder):
    return sorted(sidecar.name for sidecar in folder.glob("*.hash"))


def md5_cache_file(game_id="zzz"):
    return get_game_state_dir(game_id) / "originals_index.json"


@pytest.mark.parametrize(("game_id", "voice_rel"), [
    ("zzz", "Full/En/SoundBank_En_1.pck"),
    ("genshin", "English(US)/External0.pck"),
    ("hsr", "English/External0.pck"),
])
def test_load_manifest_md5s_walks_up_to_the_launcher_manifests(tmp_path, game_id, voice_rel):
    install = make_game_install(tmp_path, game_id)
    prefix = install.streaming_root.relative_to(install.game_root).as_posix()
    write_pkg_version(install, {"Sfx.pck": ORIGINAL})
    (install.game_root / "Audio_English(US)_pkg_version").write_text("\n".join([
        pkg_version_line(install, voice_rel, MODDED),
        "",
        "not json",
        json.dumps({"remoteName": f"{prefix}/NoSize.pck", "md5": md5_hex(LARGER_MOD)}),
        json.dumps({"remoteName": f"{prefix}/Notes.txt", "md5": md5_hex(b"notes"), "fileSize": 5}),
        json.dumps({"remoteName": f"{prefix}/BadHash.pck", "md5": "xyz", "fileSize": 5}),
        json.dumps({"remoteName": "Other_Data/StreamingAssets/Other.pck", "md5": md5_hex(b"other"), "fileSize": 5}),
    ]), encoding="utf-8")

    assert load_manifest_md5s(install.streaming_root) == {
        "Sfx.pck": (md5_hex(ORIGINAL), len(ORIGINAL)),
        voice_rel: (md5_hex(MODDED), len(MODDED)),
        "NoSize.pck": (md5_hex(LARGER_MOD), -1),
    }


def test_load_manifest_md5s_without_manifests_is_empty(tmp_path):
    install = make_game_install(tmp_path, "zzz")

    assert load_manifest_md5s(install.streaming_root) == {}


def test_manifest_verified_original_is_promoted_then_wiped_from_persistent(tmp_path):
    install = make_game_install(tmp_path, "zzz", persistent_files={REL: ORIGINAL})
    write_pkg_version(install, {REL: ORIGINAL})

    result = run_cleanup(install)

    assert overlay_counts(result) == counts(promoted=1, deleted=1)
    assert (install.streaming_root / REL).read_bytes() == ORIGINAL
    assert not (install.persistent_root / REL).exists()


def test_manifest_verified_original_overwrites_a_different_streaming_copy(tmp_path):
    install = make_game_install(tmp_path, "zzz", streaming_files={REL: MODDED}, persistent_files={REL: UPDATED_ORIGINAL})
    write_pkg_version(install, {REL: UPDATED_ORIGINAL})

    result = run_cleanup(install)

    assert overlay_counts(result) == counts(updated=1, deleted=1)
    assert (install.streaming_root / REL).read_bytes() == UPDATED_ORIGINAL
    assert not (install.persistent_root / REL).exists()


def test_mod_overlay_is_wiped_once_streaming_holds_the_original(tmp_path):
    install = make_game_install(tmp_path, "zzz", streaming_files={REL: ORIGINAL}, persistent_files={REL: MODDED})
    write_pkg_version(install, {REL: ORIGINAL})

    result = run_cleanup(install)

    assert overlay_counts(result) == counts(kept_mod=1, deleted=1)
    assert (install.streaming_root / REL).read_bytes() == ORIGINAL
    assert not (install.persistent_root / REL).exists()


def test_mod_without_a_streaming_original_is_never_deleted(tmp_path):
    install = make_game_install(tmp_path, "zzz", persistent_files={REL: MODDED})
    write_pkg_version(install, {REL: ORIGINAL})

    result = run_cleanup(install)

    assert overlay_counts(result) == counts(kept_mod=1, orphan=1, kept=1)
    assert (install.persistent_root / REL).read_bytes() == MODDED
    assert not (install.streaming_root / REL).exists()


def test_size_mismatch_is_a_mod_without_hashing_the_file(tmp_path):
    install = make_game_install(tmp_path, "zzz", persistent_files={REL: LARGER_MOD})
    write_pkg_version(install, {REL: ORIGINAL})

    stats, keep = run_promote(install)

    assert stats == {**EMPTY_STATS, "kept_mod": 1, "orphan": 1}
    assert keep == set()
    assert not md5_cache_file().exists()


def test_pck_missing_from_a_non_empty_manifest_is_never_adopted(tmp_path):
    install = make_game_install(tmp_path, "zzz", persistent_files={"Full/Unlisted.pck": ORIGINAL})
    write_pkg_version(install, {REL: ORIGINAL})

    result = run_cleanup(install)

    assert overlay_counts(result) == counts(conflict=1, kept=1)
    assert (install.persistent_root / "Full" / "Unlisted.pck").exists()
    assert not (install.streaming_root / "Full" / "Unlisted.pck").exists()


def test_verdicts_follow_the_current_manifest_not_the_md5_cache(tmp_path):
    install = make_game_install(tmp_path, "zzz", streaming_files={REL: ORIGINAL}, persistent_files={REL: ORIGINAL})
    manifest = write_pkg_version(install, {REL: ORIGINAL})
    assert run_promote(install) == (EMPTY_STATS, set())
    cached_files = json.loads(md5_cache_file().read_text(encoding="utf-8"))
    assert cached_files["schema"] == 2
    assert cached_files["files"][f"persistent/{REL}"]["md5"] == md5_hex(ORIGINAL)

    manifest.write_text(pkg_version_line(install, REL, UPDATED_ORIGINAL), encoding="utf-8")

    assert run_promote(install) == ({**EMPTY_STATS, "kept_mod": 1}, set())


@pytest.mark.parametrize(("schema", "size_offset", "expected_stats"), [
    (2, 0, {**EMPTY_STATS, "promoted": 1}),
    (2, 1, {**EMPTY_STATS, "kept_mod": 1, "orphan": 1}),
    (1, 0, {**EMPTY_STATS, "kept_mod": 1, "orphan": 1}),
])
def test_md5_cache_is_keyed_by_size_and_mtime(tmp_path, schema, size_offset, expected_stats):
    install = make_game_install(tmp_path, "zzz", persistent_files={REL: MODDED})
    write_pkg_version(install, {REL: ORIGINAL})
    persistent_stat = (install.persistent_root / REL).stat()
    forged_entry = {"size": persistent_stat.st_size + size_offset, "mtime": int(persistent_stat.st_mtime), "md5": md5_hex(ORIGINAL)}
    md5_cache_file().write_text(json.dumps({"schema": schema, "files": {f"persistent/{REL}": forged_entry}}), encoding="utf-8")

    stats, _keep = run_promote(install)

    assert stats == expected_stats


def test_sidecar_verified_original_is_promoted_together_with_its_sidecar(tmp_path):
    install = make_game_install(tmp_path, "hsr", persistent_files={VOICE_REL: ORIGINAL})
    write_hash_sidecar(install.persistent_root / "English", "External0.pck", ORIGINAL)

    result = run_cleanup(install)

    assert overlay_counts(result) == counts(promoted=1, deleted=1)
    assert result["sidecars_moved"] == 1
    assert (install.streaming_root / VOICE_REL).read_bytes() == ORIGINAL
    assert sidecar_names(install.streaming_root / "English") == [hash_sidecar_name("External0.pck", ORIGINAL)]
    assert list((install.persistent_root / "English").iterdir()) == []


def test_fresh_redownload_resyncs_the_streaming_copy_and_its_sidecar(tmp_path):
    install = make_game_install(tmp_path, "hsr", streaming_files={VOICE_REL: ORIGINAL}, persistent_files={VOICE_REL: UPDATED_ORIGINAL})
    write_hash_sidecar(install.streaming_root / "English", "External0.pck", ORIGINAL)
    write_hash_sidecar(install.persistent_root / "English", "External0.pck", UPDATED_ORIGINAL)

    result = run_cleanup(install)

    assert overlay_counts(result) == counts(updated=1, deleted=1)
    assert result["sidecars_moved"] == 1
    assert (install.streaming_root / VOICE_REL).read_bytes() == UPDATED_ORIGINAL
    assert sidecar_names(install.streaming_root / "English") == [hash_sidecar_name("External0.pck", UPDATED_ORIGINAL)]
    assert list((install.persistent_root / "English").iterdir()) == []


def test_sidecar_mismatch_is_a_mod_and_its_sidecar_rejoins_the_original(tmp_path):
    install = make_game_install(tmp_path, "hsr", streaming_files={VOICE_REL: ORIGINAL}, persistent_files={VOICE_REL: MODDED})
    write_hash_sidecar(install.persistent_root / "English", "External0.pck", ORIGINAL)

    result = run_cleanup(install)

    assert overlay_counts(result) == counts(kept_mod=1, deleted=1)
    assert result["sidecars_moved"] == 1
    assert (install.streaming_root / VOICE_REL).read_bytes() == ORIGINAL
    assert sidecar_names(install.streaming_root / "English") == [hash_sidecar_name("External0.pck", ORIGINAL)]


def test_heuristic_fills_a_missing_streaming_file_with_an_untracked_pck(tmp_path):
    install = make_game_install(tmp_path, "zzz", persistent_files={REL: ORIGINAL})

    result = run_cleanup(install, modded_keys={"Full/Other.pck"})

    assert overlay_counts(result) == counts(promoted=1, deleted=1)
    assert (install.streaming_root / REL).read_bytes() == ORIGINAL


def test_heuristic_never_overwrites_an_existing_streaming_file(tmp_path):
    install = make_game_install(tmp_path, "zzz", streaming_files={REL: ORIGINAL}, persistent_files={REL: UPDATED_ORIGINAL})

    result = run_cleanup(install)

    assert overlay_counts(result) == counts(conflict=1, kept=1)
    assert (install.streaming_root / REL).read_bytes() == ORIGINAL
    assert (install.persistent_root / REL).read_bytes() == UPDATED_ORIGINAL


def test_heuristic_wipes_a_persistent_copy_identical_to_streaming(tmp_path):
    install = make_game_install(tmp_path, "zzz", streaming_files={REL: ORIGINAL}, persistent_files={REL: ORIGINAL})

    result = run_cleanup(install)

    assert overlay_counts(result) == counts(deleted=1)
    assert not (install.persistent_root / REL).exists()


@pytest.mark.parametrize("modded_key", [REL, "Streamed_SFX_2.pck"])
@pytest.mark.parametrize(("streaming_files", "expected_counts"), [
    ({}, counts(kept_mod=1, orphan=1, kept=1)),
    ({REL: ORIGINAL}, counts(kept_mod=1, deleted=1)),
])
def test_heuristic_never_promotes_a_tracked_mod(tmp_path, modded_key, streaming_files, expected_counts):
    install = make_game_install(tmp_path, "zzz", streaming_files=streaming_files, persistent_files={REL: MODDED})

    result = run_cleanup(install, modded_keys={modded_key})

    assert overlay_counts(result) == expected_counts
    assert read_or_none(install.streaming_root / REL) == streaming_files.get(REL)


def test_heuristic_wipes_an_overlay_xxar_recorded_writing_and_forgets_it(tmp_path):
    install = make_game_install(tmp_path, "zzz", streaming_files={REL: ORIGINAL}, persistent_files={REL: MODDED, "Full/Patch.pck": MODDED})
    persistent_originals.record_written_overlays("zzz", install.persistent_root, [install.persistent_root / REL, install.persistent_root / "Full/Patch.pck"])
    assert persistent_originals.load_written_overlays("zzz") == {REL}

    result = run_cleanup(install)

    assert overlay_counts(result) == counts(kept_mod=1, deleted=1)
    assert not (install.persistent_root / REL).exists()
    assert (install.streaming_root / REL).read_bytes() == ORIGINAL
    assert persistent_originals.load_written_overlays("zzz") == set()


def test_protected_overrides_are_never_promoted_or_wiped_but_get_restored(tmp_path):
    override_pck = build_pck(banks=[bank(700, {})])
    stub = b"AKPK-stub"
    install = make_game_install(tmp_path, "zzz", streaming_files={"Full/En/Patch.pck": stub}, persistent_files={"Full/En/Patch.pck": override_pck})
    write_pkg_version(install, {"Full/En/Patch.pck": stub})
    live_patch_pck = install.persistent_root / "Full" / "En" / "Patch.pck"
    patch_backup.ensure_backup(live_patch_pck, install.persistent_root, install.game)
    live_patch_pck.write_bytes(with_bank_ids_zeroed(override_pck, [700]))

    result = run_cleanup(install)

    assert overlay_counts(result) == counts()
    assert result["override_restored"] == 1
    assert live_patch_pck.read_bytes() == override_pck
    assert (install.streaming_root / "Full" / "En" / "Patch.pck").read_bytes() == stub


def test_failed_promotion_keeps_the_only_good_copy(tmp_path, monkeypatch):
    install = make_game_install(tmp_path, "zzz", streaming_files={REL: MODDED}, persistent_files={REL: ORIGINAL})
    write_pkg_version(install, {REL: ORIGINAL})

    def failing_copy(source, destination):
        raise OSError("disk full")

    monkeypatch.setattr(persistent_originals, "_copy_original", failing_copy)

    result = run_cleanup(install)

    assert overlay_counts(result) == counts(kept=1)
    assert (install.persistent_root / REL).read_bytes() == ORIGINAL
    assert (install.streaming_root / REL).read_bytes() == MODDED


def test_relocate_orphan_sidecars_moves_a_stranded_sidecar_next_to_its_pck(tmp_path):
    install = make_game_install(tmp_path, "hsr", streaming_files={VOICE_REL: ORIGINAL})
    write_hash_sidecar(install.persistent_root / "English", "External0.pck", ORIGINAL)

    assert relocate_orphan_sidecars(install.game, install.streaming_root, install.persistent_root) == 1
    assert sidecar_names(install.streaming_root / "English") == [hash_sidecar_name("External0.pck", ORIGINAL)]
    assert sidecar_names(install.persistent_root / "English") == []


def test_relocate_orphan_sidecars_drops_a_duplicate_of_an_existing_sidecar(tmp_path):
    install = make_game_install(tmp_path, "hsr", streaming_files={VOICE_REL: UPDATED_ORIGINAL})
    write_hash_sidecar(install.streaming_root / "English", "External0.pck", UPDATED_ORIGINAL)
    write_hash_sidecar(install.persistent_root / "English", "External0.pck", ORIGINAL)

    assert relocate_orphan_sidecars(install.game, install.streaming_root, install.persistent_root) == 1
    assert sidecar_names(install.streaming_root / "English") == [hash_sidecar_name("External0.pck", UPDATED_ORIGINAL)]
    assert sidecar_names(install.persistent_root / "English") == []


@pytest.mark.parametrize(("streaming_files", "persistent_files", "pck_name"), [
    pytest.param({}, {}, "External0.pck", id="no-streaming-pck"),
    pytest.param({VOICE_REL: ORIGINAL}, {VOICE_REL: ORIGINAL}, "External0.pck", id="sidecar-beside-its-pck"),
    pytest.param({"English/Patch.pck": ORIGINAL}, {}, "Patch.pck", id="protected"),
])
def test_relocate_orphan_sidecars_leaves_other_sidecars_alone(tmp_path, streaming_files, persistent_files, pck_name):
    install = make_game_install(tmp_path, "hsr", streaming_files=streaming_files, persistent_files=persistent_files)
    sidecar = write_hash_sidecar(install.persistent_root / "English", pck_name, ORIGINAL)

    assert relocate_orphan_sidecars(install.game, install.streaming_root, install.persistent_root) == 0
    assert sidecar.exists()


def test_remove_misplaced_copies_deletes_root_level_strays_of_subfolder_originals(tmp_path):
    install = make_game_install(
        tmp_path, "zzz",
        streaming_files={"Full/SoundBank_SFX_1.pck": ORIGINAL, "SoundBank_SFX_1.pck": MODDED, "Root.pck": ORIGINAL, "Unknown.pck": ORIGINAL, "Patch.pck": ORIGINAL},
        persistent_files={"SoundBank_SFX_1.pck": MODDED, "Full/Patch.pck": ORIGINAL},
    )
    write_pkg_version(install, {"Full/SoundBank_SFX_1.pck": ORIGINAL, "Root.pck": ORIGINAL, "Full/Patch.pck": ORIGINAL})

    removed = remove_misplaced_copies("zzz", install.streaming_root, install.persistent_root)

    assert removed == 2
    assert sorted(pck.name for pck in install.streaming_root.glob("*.pck")) == ["Patch.pck", "Root.pck", "Unknown.pck"]
    assert list(install.persistent_root.glob("*.pck")) == []


def test_remove_misplaced_copies_keeps_strays_whose_true_original_is_missing(tmp_path):
    install = make_game_install(tmp_path, "zzz", streaming_files={"SoundBank_SFX_1.pck": ORIGINAL})
    write_pkg_version(install, {"Full/SoundBank_SFX_1.pck": ORIGINAL})

    assert remove_misplaced_copies("zzz", install.streaming_root, install.persistent_root) == 0
    assert remove_misplaced_copies("zzz", install.streaming_root, install.persistent_root, manifest={}) == 0
    assert (install.streaming_root / "SoundBank_SFX_1.pck").exists()


@pytest.mark.parametrize(("game_id", "streaming_files", "pck_key", "entries", "expected_rel"), [
    pytest.param("zzz", {REL: ORIGINAL}, REL, None, REL, id="folder-qualified"),
    pytest.param("zzz", {REL: ORIGINAL, "Full/Deep/Streamed_SFX_2.pck": ORIGINAL}, "Streamed_SFX_2.pck", None, REL, id="bare-shallowest"),
    pytest.param("zzz", {"Full/En/Streamed_En_1.pck": ORIGINAL}, "En/Streamed_En_1.pck", None, "Full/En/Streamed_En_1.pck", id="partial-path"),
    pytest.param(
        "hsr", {"English/External0.pck": build_pck(sounds=[sound(6001)]), "Japanese/External0.pck": build_pck(sounds=[sound(6101)])},
        "External0.pck", {"6101": {"file_id": 6101}}, "Japanese/External0.pck", id="shared-basename-by-entries",
    ),
])
def test_locate_pck_paths_mirrors_the_source_subpath_under_persistent(tmp_path, game_id, streaming_files, pck_key, entries, expected_rel):
    install = make_game_install(tmp_path, game_id, streaming_files=streaming_files)

    source_pck, output_pck = locate_pck_paths(install.streaming_root, install.persistent_root, pck_key, entries=entries)

    assert source_pck == install.streaming_root / expected_rel
    assert output_pck == install.persistent_root / expected_rel


def test_locate_pck_paths_without_a_source_returns_nothing(tmp_path):
    install = make_game_install(tmp_path, "zzz", streaming_files={REL: ORIGINAL})
    stale_full_path_key = str(tmp_path / "old_install" / "Streamed_SFX_2.pck")

    assert locate_pck_paths(install.streaming_root, install.persistent_root, "Missing.pck") == (None, None)
    assert locate_pck_paths(install.streaming_root, install.persistent_root, stale_full_path_key) == (None, None)


def test_cleanup_persistent_overlay_end_to_end(tmp_path):
    override_pck = build_pck(banks=[bank(700, {})])
    install = make_game_install(
        tmp_path, "zzz",
        streaming_files={"Full/Update.pck": MODDED, "Full/Overlay.pck": ORIGINAL, "Overlay.pck": MODDED},
        persistent_files={
            "Full/Promote.pck": ORIGINAL,
            "Full/Update.pck": UPDATED_ORIGINAL,
            "Full/Overlay.pck": MODDED,
            "Full/Orphan.pck": MODDED,
            "Full/Unlisted.pck": ORIGINAL,
            "Full/En/Patch.pck": override_pck,
        },
    )
    write_pkg_version(install, {
        "Full/Promote.pck": ORIGINAL,
        "Full/Update.pck": UPDATED_ORIGINAL,
        "Full/Overlay.pck": ORIGINAL,
        "Full/Orphan.pck": ORIGINAL,
    })
    live_patch_pck = install.persistent_root / "Full" / "En" / "Patch.pck"
    patch_backup.ensure_backup(live_patch_pck, install.persistent_root, install.game)
    live_patch_pck.write_bytes(with_bank_ids_zeroed(override_pck, [700]))

    result = run_cleanup(install, modded_keys={"Full/Overlay.pck", "Full/Orphan.pck"})

    assert result == {
        "promoted": 1, "updated": 1, "kept_mod": 2, "orphan": 1, "conflict": 1,
        "deleted": 3, "kept": 2, "sidecars_moved": 0, "override_restored": 1, "misplaced_removed": 1,
    }
    assert sorted(pck.relative_to(install.persistent_root).as_posix() for pck in install.persistent_root.rglob("*.pck")) == [
        "Full/En/Patch.pck", "Full/Orphan.pck", "Full/Unlisted.pck",
    ]
    assert live_patch_pck.read_bytes() == override_pck
    assert (install.streaming_root / "Full" / "Promote.pck").read_bytes() == ORIGINAL
    assert (install.streaming_root / "Full" / "Update.pck").read_bytes() == UPDATED_ORIGINAL
    assert not (install.streaming_root / "Overlay.pck").exists()


def test_cleanup_without_a_persistent_folder_does_nothing(tmp_path):
    install = make_game_install(tmp_path, "zzz", streaming_files={REL: ORIGINAL})
    os.rmdir(install.persistent_root)

    result = run_cleanup(install)

    assert set(result.values()) == {0}
    assert (install.streaming_root / REL).read_bytes() == ORIGINAL
