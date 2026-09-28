import pytest

from helpers import build_bnk, build_pck, make_wem
from mod_builders import (
    EMBEDDED_WEM_ID,
    GAME_IDS,
    SFX_BNK_ID,
    SHARED_WEM_ID,
    STREAMED_WEM_ID,
    VOICE_BNK_ID,
    VOICE_LANG_ID,
    VOICE_LANGUAGES,
    VOICE_WEM_ID,
    GameKeys,
    bank_wems,
    install_enabled,
    loose_wem,
    make_mod_env,
    mod_entry,
    pck_entries,
    run_apply,
)
from src.core.config_manager import get_game_state_dir
from src.wwise import patch_backup
from src.wwise.pck_indexer import PCKIndexer

PATCH_ONLY_WEM_ID = 130001
JP_VOICE_WEM_ID = 230001
EN_PATCH_ONLY_WEM_ID = 240001
JP_PATCH_ONLY_WEM_ID = 250001
ORPHAN_VOICE_BNK_ID = 3001
ORPHAN_VOICE_WEM_ID = 260001

ZZZ_JP_SOUNDBANK = "Full/Jp/SoundBank_Jp_0.pck"
ZZZ_EN_PATCH = "Full/En/Patch.pck"
ZZZ_JP_PATCH = "Full/Jp/Patch.pck"


def sfx_patch_pck():
    patch_bnk = build_bnk(SFX_BNK_ID, {EMBEDDED_WEM_ID: make_wem(50), PATCH_ONLY_WEM_ID: make_wem(51)})
    return build_pck(banks=[(SFX_BNK_ID, 0, patch_bnk)], sounds=[(STREAMED_WEM_ID, 0, make_wem(52))])


def bank_ids(pck_path):
    return [bank["id"] for bank in PCKIndexer(str(pck_path)).build_index()["banks"]]


def patch_env(tmp_path, game_id):
    keys = GameKeys(game_id)
    env = make_mod_env(tmp_path, game_id, persistent_files={keys.patch: sfx_patch_pck()})
    install_enabled(env, "Patch Mod", {"Patch.pck": [mod_entry(env.work_dir / "src", EMBEDDED_WEM_ID, make_wem(100), bnk_id=SFX_BNK_ID)]})
    return env


@pytest.mark.parametrize("game_id", GAME_IDS)
def test_a_patch_pck_replacement_is_rebuilt_into_the_soundbank(tmp_path, game_id):
    env = patch_env(tmp_path, game_id)

    run_apply(env)
    modded_wems = bank_wems(env.persistent_root / env.keys.soundbank, SFX_BNK_ID)

    assert modded_wems[EMBEDDED_WEM_ID] == make_wem(100)
    assert modded_wems[PATCH_ONLY_WEM_ID] == make_wem(51)
    assert modded_wems[SHARED_WEM_ID] == bank_wems(env.streaming_root / env.keys.soundbank, SFX_BNK_ID)[SHARED_WEM_ID]
    assert list(env.tracker.get_all_replacements()) == [env.keys.soundbank]


@pytest.mark.parametrize("game_id", GAME_IDS)
def test_the_live_patch_pck_only_gets_its_bank_id_nulled(tmp_path, game_id):
    env = patch_env(tmp_path, game_id)
    live_patch = env.persistent_root / env.keys.patch
    original_patch = live_patch.read_bytes()
    original_entries = list(pck_entries(live_patch).values())

    run_apply(env)

    assert len(live_patch.read_bytes()) == len(original_patch)
    assert bank_ids(live_patch) == [0]
    assert list(pck_entries(live_patch).values()) == original_entries


@pytest.mark.parametrize("game_id", GAME_IDS)
def test_the_pristine_patch_backup_lives_in_the_state_dir(tmp_path, game_id):
    env = patch_env(tmp_path, game_id)
    live_patch = env.persistent_root / env.keys.patch
    original_patch = live_patch.read_bytes()

    run_apply(env)
    backup = patch_backup.backup_path(live_patch, env.persistent_root, game_id)

    assert backup.is_relative_to(get_game_state_dir(game_id) / "patch_backups")
    assert backup.read_bytes() == original_patch
    assert list(env.persistent_root.rglob("*.xxar_backup")) == []


@pytest.mark.parametrize("game_id", GAME_IDS)
def test_disabling_the_patch_mod_restores_the_live_patch_pck(tmp_path, game_id):
    env = patch_env(tmp_path, game_id)
    live_patch = env.persistent_root / env.keys.patch
    original_patch = live_patch.read_bytes()
    run_apply(env)

    env.manager.set_all_mods_enabled(False)
    run_apply(env)

    assert live_patch.read_bytes() == original_patch
    assert not patch_backup.backup_path(live_patch, env.persistent_root, game_id).exists()
    assert sorted(path.name for path in env.persistent_root.rglob("*.pck")) == ["Patch.pck"]


@pytest.mark.parametrize("game_id", GAME_IDS)
def test_reapplying_a_patch_mod_nulls_from_the_pristine_backup(tmp_path, game_id):
    env = patch_env(tmp_path, game_id)
    live_patch = env.persistent_root / env.keys.patch
    original_patch = live_patch.read_bytes()

    run_apply(env)
    live_after_first_apply = live_patch.read_bytes()
    run_apply(env)

    assert live_patch.read_bytes() == live_after_first_apply
    assert patch_backup.backup_path(live_patch, env.persistent_root, game_id).read_bytes() == original_patch
    assert bank_wems(env.persistent_root / env.keys.soundbank, SFX_BNK_ID)[PATCH_ONLY_WEM_ID] == make_wem(51)


@pytest.mark.parametrize("game_id", GAME_IDS)
def test_a_streamed_wem_of_patch_pck_is_remapped_into_the_streamed_pck(tmp_path, game_id):
    keys = GameKeys(game_id)
    env = make_mod_env(tmp_path, game_id, persistent_files={keys.patch: sfx_patch_pck()})
    install_enabled(env, "Patch Streamed", {"Patch.pck": [mod_entry(env.work_dir / "src", STREAMED_WEM_ID, make_wem(101))]})

    run_apply(env)

    assert loose_wem(env.persistent_root / keys.streamed, STREAMED_WEM_ID) == make_wem(101)
    assert bank_ids(env.persistent_root / keys.patch) == [SFX_BNK_ID]


def test_a_patch_entry_without_any_counterpart_is_dropped(tmp_path):
    keys = GameKeys("zzz")
    env = make_mod_env(tmp_path, "zzz", persistent_files={keys.patch: sfx_patch_pck()})
    live_patch = env.persistent_root / keys.patch
    original_patch = live_patch.read_bytes()
    install_enabled(env, "Nowhere", {"Patch.pck": [mod_entry(env.work_dir / "src", 999999, make_wem(102))]})

    run_apply(env)

    assert live_patch.read_bytes() == original_patch
    assert not patch_backup.backup_path(live_patch, env.persistent_root, "zzz").exists()
    assert sorted(path.name for path in env.persistent_root.rglob("*.pck")) == ["Patch.pck"]


def zzz_voice_env(tmp_path, en_patch_banks):
    streaming_files = {
        ZZZ_JP_SOUNDBANK: build_pck(banks=[(VOICE_BNK_ID, VOICE_LANG_ID, build_bnk(VOICE_BNK_ID, {JP_VOICE_WEM_ID: make_wem(8)}, language_id=VOICE_LANG_ID))], languages=VOICE_LANGUAGES),
    }
    persistent_files = {
        ZZZ_EN_PATCH: build_pck(banks=en_patch_banks, languages=VOICE_LANGUAGES),
        ZZZ_JP_PATCH: build_pck(banks=[(VOICE_BNK_ID, VOICE_LANG_ID, build_bnk(VOICE_BNK_ID, {JP_VOICE_WEM_ID: make_wem(72), JP_PATCH_ONLY_WEM_ID: make_wem(73)}, language_id=VOICE_LANG_ID))], languages=VOICE_LANGUAGES),
    }
    return make_mod_env(tmp_path, "zzz", streaming_files=streaming_files, persistent_files=persistent_files)


def test_zzz_en_voice_mod_in_patch_pck_leaves_the_jp_override_alone(tmp_path):
    en_voice_bnk = build_bnk(VOICE_BNK_ID, {VOICE_WEM_ID: make_wem(70), EN_PATCH_ONLY_WEM_ID: make_wem(71)}, language_id=VOICE_LANG_ID)
    env = zzz_voice_env(tmp_path, [(VOICE_BNK_ID, VOICE_LANG_ID, en_voice_bnk)])
    jp_patch_before = (env.persistent_root / ZZZ_JP_PATCH).read_bytes()
    install_enabled(env, "En Voice", {"Patch.pck": [mod_entry(env.work_dir / "src", VOICE_WEM_ID, make_wem(103), bnk_id=VOICE_BNK_ID, lang_id=VOICE_LANG_ID)]})

    run_apply(env)

    assert bank_wems(env.persistent_root / env.keys.voice_soundbank, VOICE_BNK_ID) == {VOICE_WEM_ID: make_wem(103), EN_PATCH_ONLY_WEM_ID: make_wem(71)}
    assert not (env.persistent_root / ZZZ_JP_SOUNDBANK).exists()
    assert bank_ids(env.persistent_root / ZZZ_EN_PATCH) == [0]
    assert (env.persistent_root / ZZZ_JP_PATCH).read_bytes() == jp_patch_before


def test_zzz_orphan_voice_bank_lands_in_the_same_language_soundbank(tmp_path):
    orphan_bnk = build_bnk(ORPHAN_VOICE_BNK_ID, {ORPHAN_VOICE_WEM_ID: make_wem(74)}, language_id=VOICE_LANG_ID)
    env = zzz_voice_env(tmp_path, [(ORPHAN_VOICE_BNK_ID, VOICE_LANG_ID, orphan_bnk)])
    install_enabled(env, "Orphan Voice", {"Patch.pck": [mod_entry(env.work_dir / "a", ORPHAN_VOICE_WEM_ID, make_wem(104), bnk_id=ORPHAN_VOICE_BNK_ID, lang_id=VOICE_LANG_ID)]})
    install_enabled(env, "Plain Voice", {env.keys.voice_soundbank: [mod_entry(env.work_dir / "b", VOICE_WEM_ID, make_wem(105), bnk_id=VOICE_BNK_ID, lang_id=VOICE_LANG_ID)]})

    run_apply(env)
    en_overlay = env.persistent_root / env.keys.voice_soundbank

    assert sorted(bank_ids(en_overlay)) == [VOICE_BNK_ID, ORPHAN_VOICE_BNK_ID]
    assert bank_wems(en_overlay, ORPHAN_VOICE_BNK_ID) == {ORPHAN_VOICE_WEM_ID: make_wem(104)}
    assert bank_wems(en_overlay, VOICE_BNK_ID)[VOICE_WEM_ID] == make_wem(105)
    assert not (env.persistent_root / env.keys.soundbank).exists()
    assert bank_ids(env.persistent_root / ZZZ_EN_PATCH) == [0]
