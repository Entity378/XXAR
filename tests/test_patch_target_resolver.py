import pytest

from helpers import build_bnk, build_pck, make_game_install, make_wem
from overlay_builders import bank, bnk_replacement, sound, wem_replacement, write_persist_manifest
from src.mods.persistent_originals import locate_pck_paths
from src.wwise.override_pck_patcher import patch_override_pcks
from src.wwise.patch_target_resolver import (
    add_streamed_duplicates,
    canonicalize_pck_keys,
    find_patch_pck_sources,
    install_whole_patch_bnks,
    plain_wem_id,
    resolve_and_extract,
    soundbank_bnk_ids,
    streamed_wem_pcks,
)

GAME_LAYOUTS = [
    pytest.param("zzz", "Full/SoundBank_SFX_1.pck", "Full/Streamed_SFX_1.pck", "Full/Patch.pck", id="zzz-sfx"),
    pytest.param("zzz", "Full/En/SoundBank_En_1.pck", "Full/En/Streamed_En_1.pck", "Full/En/Patch.pck", id="zzz-voice"),
    pytest.param("genshin", "Banks0.pck", "Streamed0.pck", "Patch.pck", id="genshin"),
    pytest.param("hsr", "SFX/Banks0.pck", "SFX/Streamed0.pck", "SFX/Hotfix.pck", id="hsr"),
]
ENGLISH = {1: "english"}
JAPANESE = {1: "japanese"}


def stat_counts(stats):
    return stats["remapped"], stats["orphan_added"], stats["dropped"]


@pytest.mark.parametrize(("game_id", "soundbank_rel", "streamed_rel", "override_rel"), GAME_LAYOUTS)
def test_wem_entry_on_an_override_moves_to_the_streamed_pck_holding_it(tmp_path, game_id, soundbank_rel, streamed_rel, override_rel):
    install = make_game_install(
        tmp_path, game_id,
        streaming_files={streamed_rel: build_pck(sounds=[sound(5001)])},
        persistent_files={override_rel: build_pck(sounds=[sound(5001, seed=99)])},
    )
    replacement = wem_replacement(5001)
    resolved = {override_rel: {"5001": replacement}}

    stats = resolve_and_extract(resolved, install.streaming_root, install.persistent_root, install.game)

    assert resolved == {streamed_rel: {"5001": replacement}}
    assert stat_counts(stats) == (1, 0, 0)
    assert stats["patch_bnk_content"] == {}


@pytest.mark.parametrize(("game_id", "soundbank_rel", "streamed_rel", "override_rel"), GAME_LAYOUTS)
def test_bnk_entry_on_an_override_moves_to_the_soundbank_copy_holding_the_wem(tmp_path, game_id, soundbank_rel, streamed_rel, override_rel):
    patched_wems = {7001: make_wem(71), 7003: make_wem(73)}
    install = make_game_install(
        tmp_path, game_id,
        streaming_files={soundbank_rel: build_pck(banks=[bank(700, {7001: make_wem(1), 7002: make_wem(2)})])},
        persistent_files={override_rel: build_pck(banks=[bank(700, patched_wems)])},
    )
    replacement = bnk_replacement(700, 7001)
    resolved = {override_rel: {"700|7001": replacement}}

    stats = resolve_and_extract(resolved, install.streaming_root, install.persistent_root, install.game)

    assert resolved == {soundbank_rel: {"700|7001": replacement}}
    assert stat_counts(stats) == (1, 0, 0)
    transported = stats["patch_bnk_content"][soundbank_rel][700]
    assert transported["wems"] == patched_wems
    assert "full_bnk_bytes" not in transported


def test_orphan_voice_bank_goes_whole_into_the_smallest_soundbank_of_its_language(tmp_path):
    orphan_bnk = build_bnk(800, {8001: make_wem(81)}, language_id=1)
    install = make_game_install(
        tmp_path, "zzz",
        streaming_files={
            "Full/SoundBank_SFX_1.pck": build_pck(banks=[bank(1, {})]),
            "Full/Jp/SoundBank_Jp_1.pck": build_pck(banks=[bank(2, {}, lang_id=1)], languages=JAPANESE),
            "Full/En/SoundBank_En_1.pck": build_pck(banks=[bank(3, {3001: make_wem(3)}, lang_id=1)], languages=ENGLISH),
            "Full/En/SoundBank_En_2.pck": build_pck(banks=[bank(4, {4001: make_wem(4, 512)}, lang_id=1)], languages=ENGLISH),
        },
        persistent_files={"Full/En/Patch.pck": build_pck(banks=[(800, 1, orphan_bnk)], languages=ENGLISH)},
    )
    replacement = bnk_replacement(800, 8001)
    resolved = {"Full/En/Patch.pck": {"800|8001": replacement}}

    stats = resolve_and_extract(resolved, install.streaming_root, install.persistent_root, install.game)

    assert resolved == {"Full/En/SoundBank_En_1.pck": {"800|8001": replacement}}
    assert stat_counts(stats) == (0, 1, 0)
    assert stats["patch_bnk_content"] == {"Full/En/SoundBank_En_1.pck": {800: {
        "source": "En/Patch.pck",
        "wems": {8001: make_wem(81)},
        "full_bnk_bytes": orphan_bnk,
        "host_lang_id": 1,
    }}}


def test_counterpart_lacking_the_wem_receives_the_whole_override_bank(tmp_path):
    install = make_game_install(
        tmp_path, "zzz",
        streaming_files={
            "Full/SoundBank_SFX_1.pck": build_pck(banks=[bank(1, {})]),
            "Full/SoundBank_SFX_2.pck": build_pck(banks=[bank(700, {7002: make_wem(2, 512)})]),
        },
        persistent_files={"Full/Patch.pck": build_pck(banks=[bank(700, {7001: make_wem(71)})])},
    )
    resolved = {"Full/Patch.pck": {"700|7001": bnk_replacement(700, 7001)}}

    stats = resolve_and_extract(resolved, install.streaming_root, install.persistent_root, install.game)

    assert list(resolved) == ["Full/SoundBank_SFX_2.pck"]
    assert stat_counts(stats) == (0, 1, 0)
    assert "full_bnk_bytes" in stats["patch_bnk_content"]["Full/SoundBank_SFX_2.pck"][700]


def test_colliding_voice_bank_ids_route_each_language_to_its_own_soundbank(tmp_path):
    english_patch_wem = make_wem(91)
    japanese_patch_wem = make_wem(92)
    install = make_game_install(
        tmp_path, "zzz",
        streaming_files={
            "Full/En/SoundBank_En_1.pck": build_pck(banks=[bank(900, {9001: make_wem(1)}, lang_id=1)], languages=ENGLISH),
            "Full/Jp/SoundBank_Jp_1.pck": build_pck(banks=[bank(900, {9101: make_wem(2)}, lang_id=1)], languages=JAPANESE),
        },
        persistent_files={
            "Full/En/Patch.pck": build_pck(banks=[bank(900, {9001: english_patch_wem}, lang_id=1)], languages=ENGLISH),
            "Full/Jp/Patch.pck": build_pck(banks=[bank(900, {9101: japanese_patch_wem}, lang_id=1)], languages=JAPANESE),
        },
    )
    resolved = {
        "Full/En/Patch.pck": {"900|9001": bnk_replacement(900, 9001, "en.wem")},
        "Full/Jp/Patch.pck": {"900|9101": bnk_replacement(900, 9101, "jp.wem")},
    }

    stats = resolve_and_extract(resolved, install.streaming_root, install.persistent_root, install.game)

    assert resolved == {
        "Full/En/SoundBank_En_1.pck": {"900|9001": bnk_replacement(900, 9001, "en.wem")},
        "Full/Jp/SoundBank_Jp_1.pck": {"900|9101": bnk_replacement(900, 9101, "jp.wem")},
    }
    assert stats["patch_bnk_content"]["Full/En/SoundBank_En_1.pck"][900]["wems"] == {9001: english_patch_wem}
    assert stats["patch_bnk_content"]["Full/Jp/SoundBank_Jp_1.pck"][900]["wems"] == {9101: japanese_patch_wem}


@pytest.mark.parametrize(("entry_key", "replacement"), [
    ("4242", wem_replacement(4242)),
    ("abc", {"file_type": "wem", "wem_path": "mod.wem"}),
    ("none|8001", {"file_type": "bnk", "bnk_id": None, "file_id": 8001, "wem_path": "mod.wem"}),
    ("800|8001", bnk_replacement(800, 8001)),
])
def test_override_entries_without_a_home_are_dropped(tmp_path, entry_key, replacement):
    install = make_game_install(
        tmp_path, "zzz",
        streaming_files={"Full/Streamed_SFX_1.pck": build_pck(sounds=[sound(5001)])},
        persistent_files={"Full/Patch.pck": build_pck(banks=[bank(800, {8001: make_wem(81)})])},
    )
    resolved = {"Full/Patch.pck": {entry_key: replacement}}

    stats = resolve_and_extract(resolved, install.streaming_root, install.persistent_root, install.game)

    assert resolved == {}
    assert stat_counts(stats) == (0, 0, 1)


def test_entry_already_at_the_destination_keeps_load_order_precedence(tmp_path):
    install = make_game_install(
        tmp_path, "zzz",
        streaming_files={"Full/Streamed_SFX_1.pck": build_pck(sounds=[sound(5001)])},
        persistent_files={"Full/Patch.pck": build_pck(sounds=[sound(5001)])},
    )
    resolved = {
        "Full/Streamed_SFX_1.pck": {"5001": wem_replacement(5001, "winner.wem")},
        "Full/Patch.pck": {"5001": wem_replacement(5001, "loser.wem")},
    }

    stats = resolve_and_extract(resolved, install.streaming_root, install.persistent_root, install.game)

    assert resolved == {"Full/Streamed_SFX_1.pck": {"5001": wem_replacement(5001, "winner.wem")}}
    assert stat_counts(stats) == (0, 0, 0)


def test_soundbank_entries_colliding_with_an_override_bank_carry_its_pristine_wems(tmp_path):
    patched_wems = {7001: make_wem(71)}
    install = make_game_install(
        tmp_path, "zzz",
        streaming_files={"Full/SoundBank_SFX_1.pck": build_pck(banks=[bank(700, {7001: make_wem(1)})])},
        persistent_files={"Full/Patch.pck": build_pck(banks=[bank(700, patched_wems)])},
    )
    resolved = {"Full/SoundBank_SFX_1.pck": {"700|7001": bnk_replacement(700, 7001)}}

    stats = resolve_and_extract(resolved, install.streaming_root, install.persistent_root, install.game)

    assert list(resolved) == ["Full/SoundBank_SFX_1.pck"]
    assert stats["patch_bnk_content"]["Full/SoundBank_SFX_1.pck"][700]["wems"] == patched_wems


def test_pristine_wems_are_read_from_the_backup_once_the_live_override_is_nulled(tmp_path):
    patched_wems = {7001: make_wem(71)}
    override_pck = build_pck(banks=[bank(700, patched_wems)])
    install = make_game_install(
        tmp_path, "zzz",
        streaming_files={"Full/SoundBank_SFX_1.pck": build_pck(banks=[bank(700, {7001: make_wem(1)})])},
        persistent_files={"Full/Patch.pck": override_pck},
    )
    write_persist_manifest(install, {"Full/Patch.pck": override_pck})
    patch_override_pcks(install.persistent_root, {"Full/SoundBank_SFX_1.pck": {"700|7001": bnk_replacement(700, 7001)}}, install.game)
    resolved = {"Full/Patch.pck": {"700|7001": bnk_replacement(700, 7001)}}

    stats = resolve_and_extract(resolved, install.streaming_root, install.persistent_root, install.game)

    assert list(resolved) == ["Full/SoundBank_SFX_1.pck"]
    assert stats["patch_bnk_content"]["Full/SoundBank_SFX_1.pck"][700]["wems"] == patched_wems


def test_resolver_is_a_no_op_without_protected_targets_or_overrides(tmp_path):
    install = make_game_install(tmp_path, "zzz", streaming_files={"Full/Streamed_SFX_1.pck": build_pck(sounds=[sound(5001)])})
    resolved = {"Full/Streamed_SFX_1.pck": {"5001": wem_replacement(5001)}}

    stats = resolve_and_extract(resolved, install.streaming_root, install.persistent_root, install.game)

    assert stats == {"remapped": 0, "orphan_added": 0, "dropped": 0, "patch_bnk_content": {}}
    assert resolved == {"Full/Streamed_SFX_1.pck": {"5001": wem_replacement(5001)}}


def test_find_patch_pck_sources_returns_the_live_overrides_even_with_a_backup(tmp_path):
    override_pck = build_pck(banks=[bank(700, {7001: make_wem(71)})])
    install = make_game_install(tmp_path, "zzz", persistent_files={
        "Full/Patch.pck": override_pck,
        "Full/En/Patch.pck": override_pck,
        "Full/Hotfix.pck": override_pck,
        "Full/SoundBank_SFX_1.pck": override_pck,
    })
    patch_override_pcks(install.persistent_root, {"a.pck": {"700|7001": bnk_replacement(700, 7001)}}, install.game)

    sources = find_patch_pck_sources(install.persistent_root, install.game)

    assert sorted(sources) == sorted([
        (str(install.persistent_root / "Full" / "Patch.pck"), "Patch.pck"),
        (str(install.persistent_root / "Full" / "En" / "Patch.pck"), "Patch.pck"),
        (str(install.persistent_root / "Full" / "Hotfix.pck"), "Hotfix.pck"),
    ])
    assert find_patch_pck_sources(tmp_path / "missing", install.game) == []


def test_canonicalize_merges_bare_and_folder_qualified_aliases(tmp_path):
    install = make_game_install(tmp_path, "zzz", streaming_files={"Full/Streamed_SFX_1.pck": build_pck(sounds=[sound(5001)])})
    resolved = {
        "Streamed_SFX_1.pck": {"5001": wem_replacement(5001, "bare.wem"), "5002": wem_replacement(5002, "bare.wem")},
        "Full/Streamed_SFX_1.pck": {"5001": wem_replacement(5001, "qualified.wem")},
    }

    merged = canonicalize_pck_keys(resolved, install.streaming_root, install.game)

    assert merged == 1
    assert resolved == {"Full/Streamed_SFX_1.pck": {
        "5001": wem_replacement(5001, "qualified.wem"),
        "5002": wem_replacement(5002, "bare.wem"),
    }}


def test_canonicalize_leaves_protected_and_unknown_keys_alone(tmp_path):
    install = make_game_install(tmp_path, "zzz", streaming_files={"Full/Patch.pck": b"stub"})
    resolved = {"Patch.pck": {"1": {}}, "Full/Hotfix.pck": {"2": {}}, "Missing.pck": {"3": {}}}

    assert canonicalize_pck_keys(resolved, install.streaming_root, install.game) == 0
    assert canonicalize_pck_keys(resolved, tmp_path / "missing", install.game) == 0
    assert resolved == {"Patch.pck": {"1": {}}, "Full/Hotfix.pck": {"2": {}}, "Missing.pck": {"3": {}}}


@pytest.mark.parametrize(("game_id", "streaming_files", "bare_key", "entries"), [
    pytest.param(
        "zzz", {"Full/Streamed_SFX_1.pck": build_pck(sounds=[sound(5001)])},
        "Streamed_SFX_1.pck", {"5001": wem_replacement(5001)}, id="zzz-sfx",
    ),
    pytest.param(
        "zzz", {"Full/En/Streamed_En_1.pck": build_pck(sounds=[sound(6001)])},
        "Streamed_En_1.pck", {"6001": wem_replacement(6001)}, id="zzz-nested-voice",
        marks=pytest.mark.xfail(strict=True, reason="bug: canonicalize_pck_keys searches only one folder level, ZZZ voices live in Full/En"),
    ),
    pytest.param(
        "hsr", {"English/External0.pck": build_pck(sounds=[sound(6001)]), "Japanese/External0.pck": build_pck(sounds=[sound(6101)])},
        "External0.pck", {"6101": wem_replacement(6101)}, id="hsr-shared-basename",
        marks=pytest.mark.xfail(strict=True, reason="bug: canonicalize_pck_keys picks the first folder, ignoring which language holds the entries"),
    ),
])
def test_canonical_key_names_the_pck_that_locate_pck_paths_rebuilds(tmp_path, game_id, streaming_files, bare_key, entries):
    install = make_game_install(tmp_path, game_id, streaming_files=streaming_files)
    source_pck, _output_pck = locate_pck_paths(install.streaming_root, install.persistent_root, bare_key, entries=entries)
    resolved = {bare_key: dict(entries)}

    canonicalize_pck_keys(resolved, install.streaming_root, install.game)

    assert list(resolved) == [source_pck.relative_to(install.streaming_root).as_posix()]


def test_soundbank_and_streamed_scans_cover_voice_pcks(tmp_path):
    voice_external_id = 2**40 + 7
    install = make_game_install(tmp_path, "zzz", streaming_files={
        "Full/SoundBank_SFX_1.pck": build_pck(banks=[bank(100, {})]),
        "Full/En/SoundBank_En_1.pck": build_pck(banks=[bank(300, {}, lang_id=1)], languages=ENGLISH),
        "Full/Streamed_SFX_1.pck": build_pck(sounds=[sound(5001)]),
        "Full/En/Streamed_En_1.pck": build_pck(sounds=[sound(6001, lang_id=1)], externals=[(voice_external_id, 1, make_wem(7))], languages=ENGLISH),
    })

    assert soundbank_bnk_ids(install.streaming_root, install.game) == {100, 300}
    assert streamed_wem_pcks(install.streaming_root, install.game) == {
        5001: ("Full/Streamed_SFX_1.pck", 0),
        6001: ("Full/En/Streamed_En_1.pck", 1),
        voice_external_id: ("Full/En/Streamed_En_1.pck", 1),
    }


def test_bnk_patch_is_mirrored_into_the_streamed_copy_of_the_same_wem(tmp_path):
    install = make_game_install(tmp_path, "zzz", streaming_files={
        "Full/Streamed_SFX_1.pck": build_pck(sounds=[sound(7001, lang_id=3)], languages={3: "sfx"}),
    })
    replacement = bnk_replacement(700, 7001, "mod.wem", volume_db=-3.0)
    resolved = {"Full/SoundBank_SFX_1.pck": {"700|7001": replacement}}

    mirrored = add_streamed_duplicates(resolved, install.streaming_root, install.game)

    assert mirrored == 1
    assert resolved == {
        "Full/SoundBank_SFX_1.pck": {"700|7001": bnk_replacement(700, 7001, "mod.wem", volume_db=-3.0)},
        "Full/Streamed_SFX_1.pck": {"7001": {
            "bnk_id": None, "file_id": 7001, "file_type": "wem", "lang_id": 3, "wem_path": "mod.wem", "volume_db": -3.0,
        }},
    }


@pytest.mark.parametrize("resolved", [
    {"Full/Streamed_SFX_1.pck": {"7001": wem_replacement(7001)}},
    {"Full/SoundBank_SFX_1.pck": {"700|4242": bnk_replacement(700, 4242)}},
    {"Streamed_SFX_1.pck": {"700|7001": bnk_replacement(700, 7001)}},
    {"Full/SoundBank_SFX_1.pck": {"700|7001": bnk_replacement(700, 7001)}, "Full/Streamed_SFX_1.pck": {"7001": wem_replacement(7001, "kept.wem")}},
])
def test_streamed_mirror_skips_entries_it_must_not_duplicate(tmp_path, resolved):
    install = make_game_install(tmp_path, "zzz", streaming_files={"Full/Streamed_SFX_1.pck": build_pck(sounds=[sound(7001)])})
    before = {pck_key: dict(entries) for pck_key, entries in resolved.items()}

    assert add_streamed_duplicates(resolved, install.streaming_root, install.game) == 0
    assert resolved == before


def test_streamed_mirror_reuses_the_caller_index_without_scanning(tmp_path):
    resolved = {"Full/SoundBank_SFX_1.pck": {"700|7001": bnk_replacement(700, 7001)}}

    mirrored = add_streamed_duplicates(resolved, None, None, streamed_index={7001: ("Full/Streamed_SFX_9.pck", 0)})

    assert mirrored == 1
    assert resolved["Full/Streamed_SFX_9.pck"]["7001"]["file_type"] == "wem"


def test_install_whole_patch_bnks_adds_only_banks_carrying_full_bytes():
    class RecordingPacker:
        def __init__(self):
            self.calls = []

        def add_or_replace_bnk_raw(self, bnk_id, bnk_bytes, lang_id):
            self.calls.append((bnk_id, bnk_bytes, lang_id))

    packer = RecordingPacker()
    patch_bnk_content = {
        700: {"wems": {}, "full_bnk_bytes": b"whole-700", "host_lang_id": 1},
        800: {"wems": {}, "full_bnk_bytes": b"whole-800"},
        900: {"wems": {}},
    }

    install_whole_patch_bnks(packer, [700, 800, 900, 1000], patch_bnk_content, {800: 4})

    assert packer.calls == [(700, b"whole-700", 1), (800, b"whole-800", 4)]


@pytest.mark.parametrize(("info", "key", "expected"), [
    ({"file_id": 5}, "ignored", 5),
    ({"file_id": "7"}, "ignored", 7),
    ({}, "12|34", 34),
    ({}, "56", 56),
    ({}, "abc", None),
    ({"file_id": None}, "None|abc", None),
])
def test_plain_wem_id(info, key, expected):
    assert plain_wem_id(info, key) == expected
