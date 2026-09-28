import hashlib
import shutil
from types import SimpleNamespace

import pytest

import src.mods.package_manager as package_manager_module
from helpers import configure_game_in_settings, make_game_install
from real_game.real_game_helpers import (
    GAME_IDS,
    audio_pcks,
    game_pck_index,
    installed_game,
    music_source_ids,
    read_entries,
    replaceable_bank,
    smallest_pck,
)
from src.core.game_registry import get_game
from src.mods.package_manager import ModPackageManager
from src.mods.persistent_manager import PersistentModManager
from src.mods.persistent_originals import cleanup_persistent_overlay
from src.wwise.bnk_handler import BNKFile

pytestmark = pytest.mark.real_game


def md5_of(path):
    digest = hashlib.md5()
    with open(path, "rb") as pck_file:
        for block in iter(lambda: pck_file.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def unprotected_streaming_pcks(game_dirs):
    game = get_game(game_dirs.game_id)
    return [pck for pck in audio_pcks(game_dirs.streaming_root) if not game.is_protected_pck(pck.name)]


def most_different_in_size(candidates, reference_size, size_of):
    return max(candidates, key=lambda candidate: abs(size_of(candidate) - reference_size))


def bank_wem_target(game_dirs):
    source = smallest_pck(unprotected_streaming_pcks(game_dirs), lambda pck: replaceable_bank(pck) is not None, "with a replaceable bank")
    bank, bnk_bytes = replaceable_bank(source)
    bnk = BNKFile(bnk_bytes=bnk_bytes)
    target_wem_id, *other_wem_ids = [wem_id for wem_id in bnk.list_wems() if wem_id not in music_source_ids(source)]
    donor_wem_id = most_different_in_size(other_wem_ids, len(bnk.extract_wem(target_wem_id)), lambda wem_id: len(bnk.extract_wem(wem_id)))
    return SimpleNamespace(
        source=source, entry_key=("banks", bank["id"], bank["lang_id"]), wem_id=target_wem_id, bnk_id=bank["id"],
        lang_id=bank["lang_id"], file_type="bnk", replacement=bnk.extract_wem(donor_wem_id),
    )


def loose_wem_target(game_dirs):
    source = smallest_pck(
        unprotected_streaming_pcks(game_dirs),
        lambda pck: len(game_pck_index(pck)["sounds"]) + len(game_pck_index(pck)["externals"]) >= 2,
        "with two loose WEMs",
    )
    entries = read_entries(source)
    target_key, *other_keys = [key for key in entries if key[0] != "banks"]
    donor_key = most_different_in_size(other_keys, len(entries[target_key]), lambda key: len(entries[key]))
    return SimpleNamespace(
        source=source, entry_key=target_key, wem_id=target_key[1], bnk_id=None,
        lang_id=target_key[2], file_type="wem", replacement=entries[donor_key],
    )


def apply_like_the_mod_manager(manager, install):
    # Mirrors ModManagerBridge._start_apply: wipe the Persistent overlay, then rebuild every enabled mod.
    modded_keys = set(manager.persistent_mod_manager.get_all_replacements())
    cleanup_persistent_overlay(install.game.id, install.streaming_root, install.persistent_root, modded_keys)
    return manager.apply_mods(install.streaming_root, install.persistent_root)


@pytest.mark.parametrize("pick_target", [bank_wem_target, loose_wem_target], ids=["bank_wem", "loose_wem"])
@pytest.mark.parametrize("game_id", GAME_IDS)
def test_real_mod_round_trip_on_a_copy_changes_only_the_modded_wem(real_game_audio_dirs, game_id, pick_target, tmp_path, monkeypatch):
    game_dirs = installed_game(real_game_audio_dirs, game_id)
    target = pick_target(game_dirs)
    pck_key = target.source.relative_to(game_dirs.streaming_root).as_posix()
    install = make_game_install(tmp_path / "games", game_id)
    streaming_copy = install.streaming_root / pck_key
    streaming_copy.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(target.source, streaming_copy)
    pristine_md5 = md5_of(streaming_copy)
    configure_game_in_settings(install)
    app_temp = tmp_path / "app_temp"
    app_temp.mkdir()
    monkeypatch.setattr(package_manager_module, "get_temp_dir", lambda: app_temp)
    replacement_wem = tmp_path / "staged" / "replacement.wem"
    replacement_wem.parent.mkdir()
    replacement_wem.write_bytes(target.replacement)

    browser_tracker = PersistentModManager(install.persistent_root, tmp_path / "browser_tracker.json", game_id)
    browser_tracker.add_replacement(pck_key, target.wem_id, str(replacement_wem), target.file_type, target.lang_id, target.bnk_id)
    manager = ModPackageManager(game_id=game_id, persistent_mod_manager=PersistentModManager(install.persistent_root, game_id=game_id))
    package = manager.create_mod_package(
        tmp_path / f"round_trip{install.game.mod_file_ext}", {"name": "Round trip", "author": "tests", "version": "1.0.0"},
        browser_tracker.get_all_replacements(),
    )
    installed = manager.install_mod(package, game_audio_dir=install.streaming_root)
    manager.set_mod_enabled(installed["uuid"], True)

    summary = apply_like_the_mod_manager(manager, install)

    assert summary == {"applied_pcks": 1, "skipped_missing_original": []}
    original_entries = read_entries(streaming_copy)
    modded_entries = read_entries(install.persistent_root / pck_key)
    assert modded_entries.keys() == original_entries.keys()
    assert [key for key in original_entries if modded_entries[key] != original_entries[key]] == [target.entry_key]
    if target.bnk_id is None:
        assert modded_entries[target.entry_key] == target.replacement
    else:
        modded_bnk, original_bnk = BNKFile(bnk_bytes=modded_entries[target.entry_key]), BNKFile(bnk_bytes=original_entries[target.entry_key])
        assert modded_bnk.list_wems() == original_bnk.list_wems()
        assert modded_bnk.extract_wem(target.wem_id) == target.replacement
        assert all(modded_bnk.extract_wem(wem_id) == original_bnk.extract_wem(wem_id) for wem_id in original_bnk.list_wems() if wem_id != target.wem_id)
    assert set(manager.persistent_mod_manager.get_all_replacements()) == {pck_key}

    manager.set_mod_enabled(installed["uuid"], False)
    apply_like_the_mod_manager(manager, install)

    assert list(install.persistent_root.rglob("*.pck")) == []
    assert manager.persistent_mod_manager.get_all_replacements() == {}
    assert [path for path in install.streaming_root.rglob("*") if path.is_file()] == [streaming_copy]
    assert md5_of(streaming_copy) == pristine_md5
    assert list(app_temp.iterdir()) == []
