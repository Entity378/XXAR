import json
import zipfile

import pytest
from PIL import Image

from helpers import build_bnk, build_pck, make_wem, record_signal, wait_until
from mod_builders import (
    EMBEDDED_WEM_ID,
    GAME_IDS,
    LAYOUTS,
    SECOND_SFX_BNK_ID,
    SECOND_SFX_BNK_WEM_ID,
    SECOND_STREAMED_WEM_ID,
    SFX_BNK_ID,
    SHARED_WEM_ID,
    STREAMED_WEM_ID,
    VOICE_BNK_ID,
    VOICE_LANG_ID,
    VOICE_WEM_ID,
    GameKeys,
    bank_wems,
    loose_wem,
    make_mod_env,
    run_apply,
)
from src.gui.backend.base_worker import WorkerRegistry, game_write_state
from src.gui.backend.import_worker import ImportWorker
from src.wwise import patch_backup

PATCH_ONLY_WEM_ID = 130001
UNKNOWN_WEM_ID = 999999
EXTERNAL_WEM_ID = 0x1122334455667788


def sfx_patch_pck():
    patch_bnk = build_bnk(SFX_BNK_ID, {EMBEDDED_WEM_ID: make_wem(50), PATCH_ONLY_WEM_ID: make_wem(51)})
    return build_pck(banks=[(SFX_BNK_ID, 0, patch_bnk)], sounds=[(STREAMED_WEM_ID, 0, make_wem(52))])


def write_source_wems(env, file_names):
    source_dir = env.work_dir / "wems"
    source_dir.mkdir(parents=True, exist_ok=True)
    files = {}
    for index, file_name in enumerate(file_names):
        source_path = source_dir / f"{file_name}.wem"
        source_path.write_bytes(make_wem(500 + index))
        files[file_name] = {"path": str(source_path)}
    return files


def import_data(env, import_mode, files, thumbnail=""):
    return {
        "import_mode": import_mode,
        "files": files,
        "metadata": {"name": "Imported", "author": "Importer", "version": "1.2.0", "description": "From the wizard"},
        "thumbnail": thumbnail,
        "save_path": str(env.work_dir / f"imported{env.game.mod_file_ext}"),
    }


def run_import(env, data, game_audio_dir=None):
    # Starts the worker through a WorkerRegistry with the game lock, like ImportWizardConnector does.
    worker = ImportWorker(data, str(game_audio_dir or env.streaming_root), env.manager, str(env.persistent_root))
    finished = record_signal(worker.finished)
    percents = record_signal(worker.progressPercent)
    registry = WorkerRegistry("import_tests")
    assert registry.start("import", worker, holds_game_lock=True)
    assert wait_until(lambda: finished and not registry.is_running("import"), timeout=20)
    return finished[0], [percent for (percent,) in percents]


def wem_entry(wem_file, lang_id=0, file_type="wem"):
    return {"wem_file": wem_file, "sound_name": "", "lang_id": lang_id, "file_type": file_type}


def test_scan_sources_union_streaming_pcks_with_persistent_overrides(tmp_path):
    keys = GameKeys("zzz")
    env = make_mod_env(tmp_path, "zzz", persistent_files={
        keys.patch: sfx_patch_pck(),
        "Full/En/Hotfix.pck": build_pck(),
        keys.soundbank: build_pck(),
    })
    live_patch = env.persistent_root / keys.patch
    patch_backup.ensure_backup(live_patch, env.persistent_root, env.game)
    worker = ImportWorker(import_data(env, "wem_folder", {}), str(env.streaming_root), env.manager, str(env.persistent_root))

    scan_sources = worker._build_scan_sources(env.streaming_root)

    assert sorted((str(path), logical_name, priority) for path, logical_name, priority in scan_sources) == sorted([
        (str(env.streaming_root / keys.soundbank), keys.soundbank, 1),
        (str(env.streaming_root / keys.streamed), keys.streamed, 0),
        (str(env.streaming_root / keys.voice_soundbank), keys.voice_soundbank, 0),
        (str(env.streaming_root / keys.voice_streamed), keys.voice_streamed, 0),
        (str(patch_backup.backup_path(live_patch, env.persistent_root, "zzz")), "Patch.pck", -1),
        (str(env.persistent_root / "Full" / "En" / "Hotfix.pck"), "Hotfix.pck", -1),
    ])


def test_scan_sources_honor_the_name_filter_on_both_roots(tmp_path):
    keys = GameKeys("zzz")
    env = make_mod_env(tmp_path, "zzz", persistent_files={keys.patch: sfx_patch_pck()})
    worker = ImportWorker(import_data(env, "pck_file", {}), str(env.streaming_root), env.manager, str(env.persistent_root))

    scan_sources = worker._build_scan_sources(env.streaming_root, name_filter={"Streamed_SFX_0.pck", "Patch.pck"})

    assert sorted((logical_name, priority) for _, logical_name, priority in scan_sources) == [("Full/Streamed_SFX_0.pck", 0), ("Patch.pck", -1)]


def voice_priority_cases():
    for game_id in GAME_IDS:
        marks = []
        if game_id == "zzz":
            marks = [pytest.mark.xfail(strict=True, reason="bug: ImportWorker ranks only SoundBank_SFX_ as soundbank, so ZZZ voice banks tie with streamed pcks")]
        yield pytest.param(game_id, marks=marks)


@pytest.mark.parametrize("game_id", list(voice_priority_cases()))
def test_a_voice_soundbank_outranks_its_streamed_pck(tmp_path, game_id):
    env = make_mod_env(tmp_path, game_id)
    worker = ImportWorker(import_data(env, "wem_folder", {}), str(env.streaming_root), env.manager, str(env.persistent_root))
    layout = LAYOUTS[game_id]

    assert worker._get_pck_priority(layout.voice_soundbank) > worker._get_pck_priority(layout.voice_streamed)


@pytest.mark.parametrize("game_id", GAME_IDS)
def test_wem_import_targets_each_file_where_the_game_plays_it(tmp_path, qapp, game_id):
    keys = GameKeys(game_id)
    env = make_mod_env(tmp_path, game_id, persistent_files={keys.patch: sfx_patch_pck()})
    source_files = write_source_wems(env, [str(wem_id) for wem_id in (EMBEDDED_WEM_ID, SHARED_WEM_ID, STREAMED_WEM_ID, PATCH_ONLY_WEM_ID, VOICE_WEM_ID, UNKNOWN_WEM_ID)])

    (success, message), percents = run_import(env, import_data(env, "wem_folder", source_files))
    installed_mod = env.manager.get_installed_mods()[0]

    assert success is True and message.startswith("Mod imported and installed successfully!\nImported v1.2.0")
    assert percents[-1] == 100
    assert installed_mod["enabled"] is False
    assert installed_mod["metadata"]["replacements"] == {
        keys.soundbank: {"1001.bnk": {
            str(EMBEDDED_WEM_ID): wem_entry(f"wem_files/1001/{EMBEDDED_WEM_ID}.wem", file_type="bnk"),
            str(SHARED_WEM_ID): wem_entry(f"wem_files/1001/{SHARED_WEM_ID}.wem", file_type="bnk"),
        }},
        keys.streamed: {"direct": {str(STREAMED_WEM_ID): wem_entry(f"wem_files/direct/{STREAMED_WEM_ID}.wem")}},
        "Patch.pck": {"1001.bnk": {str(PATCH_ONLY_WEM_ID): wem_entry(f"wem_files/1001/{PATCH_ONLY_WEM_ID}.wem", file_type="bnk")}},
        keys.voice_soundbank: {"2001.bnk": {str(VOICE_WEM_ID): wem_entry(f"wem_files/2001/{VOICE_WEM_ID}.wem", lang_id=VOICE_LANG_ID, file_type="bnk")}},
        "Unknown.pck": {"direct": {str(UNKNOWN_WEM_ID): wem_entry(f"wem_files/direct/{UNKNOWN_WEM_ID}.wem")}},
    }


def test_wem_import_saves_the_package_and_installs_its_audio(tmp_path, qapp):
    env = make_mod_env(tmp_path, "zzz")
    thumbnail_source = tmp_path / "cover.bmp"
    Image.new("RGB", (4, 4), (10, 200, 10)).save(thumbnail_source, "BMP")
    source_files = write_source_wems(env, [str(STREAMED_WEM_ID)])
    data = import_data(env, "wem_file", source_files, thumbnail=str(thumbnail_source))

    run_import(env, data)
    installed_mod = env.manager.get_installed_mods()[0]
    with zipfile.ZipFile(data["save_path"]) as archive:
        packaged_metadata = json.loads(archive.read("metadata.json"))
        packaged_thumbnail = archive.read("thumbnail.png")

    assert packaged_metadata == installed_mod["metadata"]
    assert (packaged_metadata["format_version"], packaged_metadata["description"], packaged_metadata["thumbnail"]) == ("3.0", "From the wizard", "thumbnail.png")
    assert packaged_thumbnail.startswith(b"\x89PNG")
    assert (env.manager.mods_dir / installed_mod["uuid"] / "wem_files" / "direct" / f"{STREAMED_WEM_ID}.wem").read_bytes() == (env.work_dir / "wems" / f"{STREAMED_WEM_ID}.wem").read_bytes()
    assert game_write_state().busy is False


def test_a_hex_named_wem_matches_a_64_bit_external(tmp_path, qapp):
    keys = GameKeys("zzz")
    streamed_with_external = build_pck(sounds=[(STREAMED_WEM_ID, 0, make_wem(4))], externals=[(EXTERNAL_WEM_ID, 0, make_wem(11))])
    env = make_mod_env(tmp_path, "zzz", streaming_files={keys.streamed: streamed_with_external})
    source_files = write_source_wems(env, [f"{EXTERNAL_WEM_ID:016x}"])

    run_import(env, import_data(env, "wem_file", source_files))

    assert env.manager.get_installed_mods()[0]["metadata"]["replacements"] == {
        keys.streamed: {"direct": {str(EXTERNAL_WEM_ID): wem_entry(f"wem_files/direct/{EXTERNAL_WEM_ID}.wem")}},
    }


def test_an_unmatched_wem_inside_a_bnk_folder_keeps_that_bnk(tmp_path, qapp):
    env = make_mod_env(tmp_path, "zzz")
    bnk_folder = env.work_dir / "loose" / "4242_bnk"
    bnk_folder.mkdir(parents=True)
    (bnk_folder / f"{UNKNOWN_WEM_ID}.wem").write_bytes(make_wem(12))

    run_import(env, import_data(env, "wem_folder", {str(UNKNOWN_WEM_ID): {"path": str(bnk_folder / f"{UNKNOWN_WEM_ID}.wem")}}))

    assert env.manager.get_installed_mods()[0]["metadata"]["replacements"] == {
        "Unknown.pck": {"4242.bnk": {str(UNKNOWN_WEM_ID): wem_entry(f"wem_files/4242/{UNKNOWN_WEM_ID}.wem", file_type="bnk")}},
    }


@pytest.mark.parametrize("game_id", GAME_IDS)
def test_an_imported_mod_applies_end_to_end(tmp_path, qapp, game_id):
    keys = GameKeys(game_id)
    env = make_mod_env(tmp_path, game_id, persistent_files={keys.patch: sfx_patch_pck()})
    source_files = write_source_wems(env, [str(wem_id) for wem_id in (EMBEDDED_WEM_ID, SHARED_WEM_ID, STREAMED_WEM_ID, PATCH_ONLY_WEM_ID, VOICE_WEM_ID)])
    run_import(env, import_data(env, "wem_folder", source_files))
    env.manager.set_all_mods_enabled(True)

    run_apply(env)
    modded_sfx_bank = bank_wems(env.persistent_root / keys.soundbank, SFX_BNK_ID)

    def source_bytes(wem_id):
        return (env.work_dir / "wems" / f"{wem_id}.wem").read_bytes()

    assert {wem_id: modded_sfx_bank[wem_id] for wem_id in (EMBEDDED_WEM_ID, SHARED_WEM_ID, PATCH_ONLY_WEM_ID)} == {wem_id: source_bytes(wem_id) for wem_id in (EMBEDDED_WEM_ID, SHARED_WEM_ID, PATCH_ONLY_WEM_ID)}
    assert loose_wem(env.persistent_root / keys.streamed, SHARED_WEM_ID) == source_bytes(SHARED_WEM_ID)
    assert loose_wem(env.persistent_root / keys.streamed, STREAMED_WEM_ID) == source_bytes(STREAMED_WEM_ID)
    assert bank_wems(env.persistent_root / keys.voice_soundbank, VOICE_BNK_ID)[VOICE_WEM_ID] == source_bytes(VOICE_WEM_ID)


def modded_sfx_pcks(env, embedded_bytes, streamed_bytes):
    modded_dir = env.work_dir / "modded"
    modded_dir.mkdir(parents=True, exist_ok=True)
    layout = LAYOUTS[env.game.id]
    modded_soundbank = build_pck(banks=[
        (SFX_BNK_ID, 0, build_bnk(SFX_BNK_ID, {EMBEDDED_WEM_ID: embedded_bytes, SHARED_WEM_ID: make_wem(2, 48)})),
        (SECOND_SFX_BNK_ID, 0, build_bnk(SECOND_SFX_BNK_ID, {SECOND_SFX_BNK_WEM_ID: make_wem(3)})),
    ])
    modded_streamed = build_pck(sounds=[(SHARED_WEM_ID, 0, make_wem(2, 200)), (STREAMED_WEM_ID, 0, streamed_bytes), (SECOND_STREAMED_WEM_ID, 0, make_wem(5))])
    (modded_dir / layout.soundbank).write_bytes(modded_soundbank)
    (modded_dir / layout.streamed).write_bytes(modded_streamed)
    return {
        layout.soundbank[:-len(".pck")]: {"path": str(modded_dir / layout.soundbank)},
        layout.streamed[:-len(".pck")]: {"path": str(modded_dir / layout.streamed)},
    }


def test_pck_import_keeps_only_the_changed_wems_of_a_single_pck(tmp_path, qapp):
    env = make_mod_env(tmp_path, "zzz")
    modded_files = modded_sfx_pcks(env, make_wem(77), make_wem(78))
    streamed_only = {name: info for name, info in modded_files.items() if name.startswith("Streamed")}

    run_import(env, import_data(env, "pck_file", streamed_only))

    assert env.manager.get_installed_mods()[0]["metadata"]["replacements"] == {
        env.keys.streamed: {"direct": {str(STREAMED_WEM_ID): wem_entry(f"wem_files/direct/{STREAMED_WEM_ID}.wem")}},
    }


@pytest.mark.xfail(strict=True, reason="bug: pck import keys extracted wems by id, so a bnk prefetch and its streamed copy overwrite each other")
def test_pck_import_ignores_an_unchanged_wem_present_in_two_pcks(tmp_path, qapp):
    env = make_mod_env(tmp_path, "zzz")
    modded_files = modded_sfx_pcks(env, make_wem(77), make_wem(78))

    run_import(env, import_data(env, "pck_folder", modded_files))

    assert env.manager.get_installed_mods()[0]["metadata"]["replacements"] == {
        env.keys.soundbank: {"1001.bnk": {str(EMBEDDED_WEM_ID): wem_entry(f"wem_files/1001/{EMBEDDED_WEM_ID}.wem", file_type="bnk")}},
        env.keys.streamed: {"direct": {str(STREAMED_WEM_ID): wem_entry(f"wem_files/direct/{STREAMED_WEM_ID}.wem")}},
    }


def test_import_reports_a_missing_game_audio_dir(tmp_path, qapp):
    env = make_mod_env(tmp_path, "zzz")
    source_files = write_source_wems(env, [str(STREAMED_WEM_ID)])

    (success, message), _ = run_import(env, import_data(env, "wem_file", source_files), game_audio_dir=env.streaming_root / "missing")

    assert success is False
    assert message == "Failed to convert mod: Game audio directory not set. Please set it in Settings first."
    assert env.manager.get_installed_mods() == []

