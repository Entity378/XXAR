import pytest

from helpers import build_pck, make_game_install, make_wem
from overlay_builders import bank, bnk_replacement, sound, wem_replacement, with_bank_ids_zeroed, write_persist_manifest
from src.wwise import patch_backup
from src.wwise.override_pck_patcher import patch_override_pcks, restore_override_pck_backups

SFX_OVERRIDE_PCK = build_pck(
    banks=[bank(100, {1001: make_wem(1), 1002: make_wem(2)}), bank(200, {2001: make_wem(3)})],
    sounds=[sound(5001)],
)
EN_OVERRIDE_PCK = build_pck(banks=[bank(300, {3001: make_wem(31)}, lang_id=1)], languages={1: "english"})
JP_OVERRIDE_PCK = build_pck(banks=[bank(300, {3101: make_wem(41)}, lang_id=1)], languages={1: "japanese"})


def make_override_install(tmp_path, overrides):
    install = make_game_install(tmp_path, "zzz", persistent_files=overrides)
    write_persist_manifest(install, overrides)
    return install


def backup_of(install, rel):
    return patch_backup.backup_path(install.persistent_root / rel, install.persistent_root, "zzz")


@pytest.mark.parametrize("override_name", ["Patch.pck", "Hotfix.pck"])
def test_patch_override_pcks_zeroes_only_the_targeted_bank_id(tmp_path, override_name):
    rel = f"Full/{override_name}"
    install = make_override_install(tmp_path, {rel: SFX_OVERRIDE_PCK})
    replacements = {"Full/SoundBank_SFX_1.pck": {"100|1001": bnk_replacement(100, 1001)}}

    result = patch_override_pcks(install.persistent_root, replacements, install.game)

    assert result == {"patched_pcks": 1, "patched_bnk_ids": {100}}
    assert (install.persistent_root / rel).read_bytes() == with_bank_ids_zeroed(SFX_OVERRIDE_PCK, [100])
    assert backup_of(install, rel).read_bytes() == SFX_OVERRIDE_PCK


def test_reapplying_is_idempotent_and_keeps_the_backup_pristine(tmp_path):
    install = make_override_install(tmp_path, {"Full/Patch.pck": SFX_OVERRIDE_PCK})
    replacements = {"Full/SoundBank_SFX_1.pck": {"100|1001": bnk_replacement(100, 1001)}}

    patch_override_pcks(install.persistent_root, replacements, install.game)
    result = patch_override_pcks(install.persistent_root, replacements, install.game)

    assert result == {"patched_pcks": 1, "patched_bnk_ids": {100}}
    assert (install.persistent_root / "Full" / "Patch.pck").read_bytes() == with_bank_ids_zeroed(SFX_OVERRIDE_PCK, [100])
    assert backup_of(install, "Full/Patch.pck").read_bytes() == SFX_OVERRIDE_PCK


def test_reapplying_other_targets_restores_the_previously_nulled_bank(tmp_path):
    install = make_override_install(tmp_path, {"Full/Patch.pck": SFX_OVERRIDE_PCK})
    patch_override_pcks(install.persistent_root, {"a.pck": {"100|1001": bnk_replacement(100, 1001)}}, install.game)

    patch_override_pcks(install.persistent_root, {"a.pck": {"200|2001": bnk_replacement(200, 2001)}}, install.game)

    assert (install.persistent_root / "Full" / "Patch.pck").read_bytes() == with_bank_ids_zeroed(SFX_OVERRIDE_PCK, [200])


def test_colliding_voice_bank_is_nulled_only_in_the_language_owning_the_modded_wem(tmp_path):
    install = make_override_install(tmp_path, {"Full/En/Patch.pck": EN_OVERRIDE_PCK, "Full/Jp/Patch.pck": JP_OVERRIDE_PCK})
    replacements = {"Full/En/SoundBank_En_1.pck": {"300|3001": bnk_replacement(300, 3001)}}

    patch_override_pcks(install.persistent_root, replacements, install.game)
    result = patch_override_pcks(install.persistent_root, replacements, install.game)

    assert result == {"patched_pcks": 1, "patched_bnk_ids": {300}}
    assert (install.persistent_root / "Full" / "En" / "Patch.pck").read_bytes() == with_bank_ids_zeroed(EN_OVERRIDE_PCK, [300])
    assert (install.persistent_root / "Full" / "Jp" / "Patch.pck").read_bytes() == JP_OVERRIDE_PCK


def test_bank_whose_wem_no_override_embeds_is_nulled_wherever_it_collides(tmp_path):
    install = make_override_install(tmp_path, {"Full/En/Patch.pck": EN_OVERRIDE_PCK, "Full/Jp/Patch.pck": JP_OVERRIDE_PCK})
    replacements = {"Full/En/SoundBank_En_1.pck": {"300|9999": bnk_replacement(300, 9999)}}

    result = patch_override_pcks(install.persistent_root, replacements, install.game)

    assert result == {"patched_pcks": 2, "patched_bnk_ids": {300}}
    assert (install.persistent_root / "Full" / "En" / "Patch.pck").read_bytes() == with_bank_ids_zeroed(EN_OVERRIDE_PCK, [300])
    assert (install.persistent_root / "Full" / "Jp" / "Patch.pck").read_bytes() == with_bank_ids_zeroed(JP_OVERRIDE_PCK, [300])


@pytest.mark.parametrize("replacements", [
    {},
    {"Full/Streamed_SFX_1.pck": {"5001": wem_replacement(5001)}},
    {"Full/SoundBank_SFX_1.pck": {"900|9001": bnk_replacement(900, 9001)}},
])
def test_overrides_are_untouched_without_a_colliding_bank(tmp_path, replacements):
    install = make_override_install(tmp_path, {"Full/Patch.pck": SFX_OVERRIDE_PCK})

    result = patch_override_pcks(install.persistent_root, replacements, install.game)

    assert result["patched_pcks"] == 0
    assert result["patched_bnk_ids"] == set()
    assert (install.persistent_root / "Full" / "Patch.pck").read_bytes() == SFX_OVERRIDE_PCK


def test_nothing_happens_without_persistent_overrides(tmp_path):
    install = make_game_install(tmp_path, "zzz", persistent_files={"Full/SoundBank_SFX_1.pck": SFX_OVERRIDE_PCK})
    replacements = {"Full/SoundBank_SFX_1.pck": {"100|1001": bnk_replacement(100, 1001)}}

    result = patch_override_pcks(install.persistent_root, replacements, install.game)

    assert result == {"patched_pcks": 0, "patched_bnk_ids": set()}
    assert (install.persistent_root / "Full" / "SoundBank_SFX_1.pck").read_bytes() == SFX_OVERRIDE_PCK


def test_live_override_failing_verification_is_left_alone(tmp_path):
    nulled_live = with_bank_ids_zeroed(SFX_OVERRIDE_PCK, [200])
    install = make_game_install(tmp_path, "zzz", persistent_files={"Full/Patch.pck": nulled_live})
    write_persist_manifest(install, {"Full/Patch.pck": SFX_OVERRIDE_PCK})
    replacements = {"a.pck": {"100|1001": bnk_replacement(100, 1001)}}

    result = patch_override_pcks(install.persistent_root, replacements, install.game)

    assert result["patched_pcks"] == 0
    assert (install.persistent_root / "Full" / "Patch.pck").read_bytes() == nulled_live
    assert not backup_of(install, "Full/Patch.pck").exists()


def test_restore_override_pck_backups_restores_the_live_byte_identical(tmp_path):
    install = make_override_install(tmp_path, {"Full/Patch.pck": SFX_OVERRIDE_PCK, "Full/En/Patch.pck": EN_OVERRIDE_PCK})
    replacements = {"a.pck": {"100|1001": bnk_replacement(100, 1001)}, "b.pck": {"300|3001": bnk_replacement(300, 3001)}}
    patch_override_pcks(install.persistent_root, replacements, install.game)

    restored = restore_override_pck_backups(install.persistent_root, install.game)

    assert restored == 2
    assert (install.persistent_root / "Full" / "Patch.pck").read_bytes() == SFX_OVERRIDE_PCK
    assert (install.persistent_root / "Full" / "En" / "Patch.pck").read_bytes() == EN_OVERRIDE_PCK
    assert not backup_of(install, "Full/Patch.pck").exists()


def test_restore_override_pck_backups_sweeps_legacy_co_located_backups(tmp_path):
    install = make_game_install(tmp_path, "zzz", persistent_files={
        "Full/Patch.pck": with_bank_ids_zeroed(SFX_OVERRIDE_PCK, [100]),
        "Full/Patch.pck.xxar_backup": SFX_OVERRIDE_PCK,
    })

    restored = restore_override_pck_backups(install.persistent_root, install.game)

    assert restored == 1
    assert (install.persistent_root / "Full" / "Patch.pck").read_bytes() == SFX_OVERRIDE_PCK
    assert not (install.persistent_root / "Full" / "Patch.pck.xxar_backup").exists()
