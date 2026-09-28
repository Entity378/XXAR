import json

import pytest

from helpers import build_pck, make_game_install, make_wem
from overlay_builders import bank, with_bank_ids_zeroed, write_persist_manifest, xxh64_tag
from src.core.config_manager import get_game_state_dir
from src.wwise import patch_backup

PATCH_REL = "Full/En/Patch.pck"


def pristine_override(seed=1, extra_wems=0):
    wems = {1000 + seed * 10 + index: make_wem(seed * 100 + index) for index in range(1 + extra_wems)}
    return build_pck(banks=[bank(100 + seed, wems)])


def make_override_install(tmp_path, content, game_id="zzz", rel=PATCH_REL):
    install = make_game_install(tmp_path, game_id, persistent_files={rel: content})
    return install, install.persistent_root / rel


def backup_root(game_id="zzz"):
    return get_game_state_dir(game_id) / "patch_backups"


def read_ledger(game_id="zzz"):
    return json.loads((backup_root(game_id) / "backup_index.json").read_text(encoding="utf-8"))


def test_backup_path_mirrors_the_persistent_subpath_in_the_state_dir(tmp_path):
    install, live_patch_pck = make_override_install(tmp_path, pristine_override())

    assert patch_backup.backup_path(live_patch_pck, install.persistent_root, "zzz") == backup_root() / "Full" / "En" / "Patch.pck.xxar_backup"
    assert patch_backup.backup_path(tmp_path / "elsewhere" / "Patch.pck", install.persistent_root, "zzz") is None


@pytest.mark.parametrize(("game_id", "rel"), [
    ("zzz", "Full/En/Patch.pck"),
    ("genshin", "Patch.pck"),
    ("hsr", "English/Hotfix.pck"),
])
def test_ensure_backup_captures_a_verified_live_and_records_its_tag(tmp_path, game_id, rel):
    pristine = pristine_override()
    install, live_patch_pck = make_override_install(tmp_path, pristine, game_id, rel)
    write_persist_manifest(install, {rel: pristine})

    backup = patch_backup.ensure_backup(live_patch_pck, install.persistent_root, install.game)

    assert backup == backup_root(game_id) / f"{rel}.xxar_backup"
    assert backup.read_bytes() == pristine
    assert read_ledger(game_id) == {rel: xxh64_tag(pristine)}


@pytest.mark.parametrize("game_id", ["zzz", "genshin", "hsr"])
def test_ensure_backup_never_captures_a_nulled_live(tmp_path, game_id):
    pristine = pristine_override()
    install, live_patch_pck = make_override_install(tmp_path, with_bank_ids_zeroed(pristine, [101]), game_id)
    write_persist_manifest(install, {PATCH_REL: pristine})

    assert patch_backup.ensure_backup(live_patch_pck, install.persistent_root, install.game) is None
    assert not patch_backup.backup_path(live_patch_pck, install.persistent_root, game_id).exists()


def test_ensure_backup_refuses_a_live_with_the_wrong_size(tmp_path):
    pristine = pristine_override()
    install, live_patch_pck = make_override_install(tmp_path, pristine + b"\x00" * 16)
    write_persist_manifest(install, {PATCH_REL: pristine})

    assert patch_backup.ensure_backup(live_patch_pck, install.persistent_root, install.game) is None
    assert not list(backup_root().rglob("*.xxar_backup"))


def test_ensure_backup_without_a_manifest_trusts_the_live(tmp_path):
    pristine = pristine_override()
    install, live_patch_pck = make_override_install(tmp_path, pristine)

    backup = patch_backup.ensure_backup(live_patch_pck, install.persistent_root, install.game)

    assert backup.read_bytes() == pristine
    assert read_ledger() == {PATCH_REL: None}


def test_ensure_backup_keeps_the_existing_backup_while_the_tag_is_unchanged(tmp_path):
    pristine = pristine_override()
    install, live_patch_pck = make_override_install(tmp_path, pristine)
    write_persist_manifest(install, {PATCH_REL: pristine})
    patch_backup.ensure_backup(live_patch_pck, install.persistent_root, install.game)
    live_patch_pck.write_bytes(with_bank_ids_zeroed(pristine, [101]))

    backup = patch_backup.ensure_backup(live_patch_pck, install.persistent_root, install.game)

    assert backup.read_bytes() == pristine


def test_ensure_backup_recaptures_when_the_game_updates_the_override(tmp_path):
    old_pristine = pristine_override(seed=1)
    install, live_patch_pck = make_override_install(tmp_path, old_pristine)
    write_persist_manifest(install, {PATCH_REL: old_pristine})
    patch_backup.ensure_backup(live_patch_pck, install.persistent_root, install.game)
    new_pristine = pristine_override(seed=2, extra_wems=1)
    live_patch_pck.write_bytes(new_pristine)
    write_persist_manifest(install, {PATCH_REL: new_pristine})

    backup = patch_backup.ensure_backup(live_patch_pck, install.persistent_root, install.game)

    assert backup.read_bytes() == new_pristine
    assert read_ledger() == {PATCH_REL: xxh64_tag(new_pristine)}


def test_ensure_backup_keeps_the_backup_when_the_stored_tag_is_unknown(tmp_path):
    pristine = pristine_override()
    install, live_patch_pck = make_override_install(tmp_path, pristine)
    patch_backup.ensure_backup(live_patch_pck, install.persistent_root, install.game)
    live_patch_pck.write_bytes(with_bank_ids_zeroed(pristine, [101]))
    write_persist_manifest(install, {PATCH_REL: pristine})

    backup = patch_backup.ensure_backup(live_patch_pck, install.persistent_root, install.game)

    assert backup.read_bytes() == pristine


def test_ensure_backup_keeps_the_backup_when_the_manifest_disappears(tmp_path):
    pristine = pristine_override()
    install, live_patch_pck = make_override_install(tmp_path, pristine)
    manifest = write_persist_manifest(install, {PATCH_REL: pristine})
    patch_backup.ensure_backup(live_patch_pck, install.persistent_root, install.game)
    manifest.unlink()
    live_patch_pck.write_bytes(pristine_override(seed=3))

    backup = patch_backup.ensure_backup(live_patch_pck, install.persistent_root, install.game)

    assert backup.read_bytes() == pristine


def test_ensure_backup_replaces_a_backup_whose_size_disagrees_with_the_manifest(tmp_path):
    old_content = pristine_override(seed=1)
    install, live_patch_pck = make_override_install(tmp_path, old_content)
    patch_backup.ensure_backup(live_patch_pck, install.persistent_root, install.game)
    new_pristine = pristine_override(seed=2, extra_wems=2)
    live_patch_pck.write_bytes(new_pristine)
    write_persist_manifest(install, {PATCH_REL: new_pristine})

    backup = patch_backup.ensure_backup(live_patch_pck, install.persistent_root, install.game)

    assert backup.read_bytes() == new_pristine
    assert read_ledger() == {PATCH_REL: xxh64_tag(new_pristine)}


def test_pristine_path_reads_the_backup_only_while_it_is_valid(tmp_path):
    pristine = pristine_override(seed=1)
    install, live_patch_pck = make_override_install(tmp_path, pristine)
    write_persist_manifest(install, {PATCH_REL: pristine})
    assert patch_backup.pristine_path(live_patch_pck, install.persistent_root, install.game) == str(live_patch_pck)

    backup = patch_backup.ensure_backup(live_patch_pck, install.persistent_root, install.game)
    live_patch_pck.write_bytes(with_bank_ids_zeroed(pristine, [101]))
    assert patch_backup.pristine_path(live_patch_pck, install.persistent_root, install.game) == str(backup)

    updated_pristine = pristine_override(seed=2)
    live_patch_pck.write_bytes(updated_pristine)
    write_persist_manifest(install, {PATCH_REL: updated_pristine})
    assert patch_backup.pristine_path(live_patch_pck, install.persistent_root, install.game) == str(live_patch_pck)


def test_legacy_co_located_backup_moves_into_the_state_dir_on_first_read(tmp_path):
    pristine = pristine_override()
    install, live_patch_pck = make_override_install(tmp_path, with_bank_ids_zeroed(pristine, [101]))
    legacy_backup = live_patch_pck.with_name("Patch.pck.xxar_backup")
    legacy_backup.write_bytes(pristine)
    write_persist_manifest(install, {PATCH_REL: pristine})

    read_path = patch_backup.pristine_path(live_patch_pck, install.persistent_root, install.game)

    assert read_path == str(backup_root() / "Full" / "En" / "Patch.pck.xxar_backup")
    assert not legacy_backup.exists()
    assert (backup_root() / "Full" / "En" / "Patch.pck.xxar_backup").read_bytes() == pristine
    assert read_ledger() == {PATCH_REL: xxh64_tag(pristine)}


def test_migrate_persistent_backups_moves_only_protected_overrides(tmp_path):
    pristine = pristine_override()
    install = make_game_install(tmp_path, "zzz", persistent_files={
        "Full/En/Patch.pck": pristine,
        "Full/En/Patch.pck.xxar_backup": pristine,
        "Full/SoundBank_SFX_1.pck.xxar_backup": b"not an override",
    })

    moved = patch_backup.migrate_persistent_backups(install.persistent_root, install.game)

    assert moved == 1
    assert (backup_root() / "Full" / "En" / "Patch.pck.xxar_backup").exists()
    assert (install.persistent_root / "Full" / "SoundBank_SFX_1.pck.xxar_backup").exists()


def test_restore_backups_puts_every_original_back_and_clears_the_ledger(tmp_path):
    sfx_pristine = pristine_override(seed=1)
    voice_pristine = pristine_override(seed=2)
    install = make_game_install(tmp_path, "zzz", persistent_files={"Full/Patch.pck": sfx_pristine, PATCH_REL: voice_pristine})
    live_sfx_patch_pck = install.persistent_root / "Full" / "Patch.pck"
    live_voice_patch_pck = install.persistent_root / PATCH_REL
    patch_backup.ensure_backup(live_sfx_patch_pck, install.persistent_root, install.game)
    patch_backup.ensure_backup(live_voice_patch_pck, install.persistent_root, install.game)
    live_sfx_patch_pck.write_bytes(with_bank_ids_zeroed(sfx_pristine, [101]))
    live_voice_patch_pck.write_bytes(with_bank_ids_zeroed(voice_pristine, [102]))

    restored = patch_backup.restore_backups(install.persistent_root, install.game)

    assert restored == 2
    assert live_sfx_patch_pck.read_bytes() == sfx_pristine
    assert live_voice_patch_pck.read_bytes() == voice_pristine
    assert not list(backup_root().rglob("*.xxar_backup"))
    assert read_ledger() == {}


def test_restore_backups_recreates_an_override_the_game_wiped(tmp_path):
    pristine = pristine_override()
    install, live_patch_pck = make_override_install(tmp_path, pristine)
    patch_backup.ensure_backup(live_patch_pck, install.persistent_root, install.game)
    live_patch_pck.unlink()

    assert patch_backup.restore_backups(install.persistent_root, install.game) == 1
    assert live_patch_pck.read_bytes() == pristine


@pytest.mark.xfail(strict=True, reason="bug: restore_backups checks only the size, so a same-size stale backup overwrites the updated override")
def test_restore_backups_never_puts_back_a_backup_the_game_update_made_stale(tmp_path):
    old_pristine = pristine_override(seed=1)
    install, live_patch_pck = make_override_install(tmp_path, old_pristine)
    write_persist_manifest(install, {PATCH_REL: old_pristine})
    patch_backup.ensure_backup(live_patch_pck, install.persistent_root, install.game)
    # The update swaps a WEM payload in place, so the override keeps its size.
    updated_pristine = build_pck(banks=[bank(101, {1010: make_wem(777)})])
    live_patch_pck.write_bytes(updated_pristine)
    write_persist_manifest(install, {PATCH_REL: updated_pristine})

    patch_backup.restore_backups(install.persistent_root, install.game)

    assert live_patch_pck.read_bytes() == updated_pristine


def test_restore_backups_drops_a_backup_whose_size_disagrees_with_the_manifest(tmp_path):
    old_content = pristine_override(seed=1)
    install, live_patch_pck = make_override_install(tmp_path, old_content)
    patch_backup.ensure_backup(live_patch_pck, install.persistent_root, install.game)
    new_pristine = pristine_override(seed=2, extra_wems=2)
    live_patch_pck.write_bytes(new_pristine)
    write_persist_manifest(install, {PATCH_REL: new_pristine})

    assert patch_backup.restore_backups(install.persistent_root, install.game) == 0
    assert live_patch_pck.read_bytes() == new_pristine
    assert not list(backup_root().rglob("*.xxar_backup"))
    assert read_ledger() == {}
