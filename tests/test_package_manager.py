import json
import shutil
import zipfile

import pytest
from PIL import Image

import src.core.app_config as app_config
from helpers import make_wem, read_settings, write_settings
from mod_builders import (
    EMBEDDED_WEM_ID,
    SFX_BNK_ID,
    SHARED_WEM_ID,
    STREAMED_WEM_ID,
    install_enabled,
    make_mod_env,
    mod_entry,
    package_mod,
)
from src.core.config_manager import get_custom_mod_library_settings_key, get_game_mod_library_dir
from src.mods.package_manager import (
    _AUDIO_SETTING_KEYS,
    InvalidModPackageError,
    ModPackageManager,
    count_replacements,
    is_hirc_mod,
)


@pytest.fixture
def env(tmp_path):
    return make_mod_env(tmp_path, "zzz")


def read_package(package_path):
    with zipfile.ZipFile(package_path) as archive:
        return json.loads(archive.read("metadata.json")), {name: archive.read(name) for name in archive.namelist()}


def write_package(package_path, metadata, entries=None, raw_metadata=None):
    package_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(package_path, "w") as archive:
        archive.writestr("metadata.json", raw_metadata if raw_metadata is not None else json.dumps(metadata))
        for name, content in (entries or {}).items():
            archive.writestr(name, content)
    return package_path


def minimal_metadata(**overrides):
    metadata = {
        "format_version": "3.0",
        "name": "Minimal",
        "author": "Tester",
        "version": "1.0.0",
        "replacements": {"Full/Streamed_SFX_0.pck": {"direct": {str(STREAMED_WEM_ID): {"wem_file": "wem_files/direct/120001.wem", "lang_id": 0, "file_type": "wem"}}}},
    }
    metadata.update(overrides)
    return metadata


def exported_replacements(manager, installed_mod_uuid):
    # Mirrors ModManagerBridge.exportMod by rebuilding tracker-shaped replacements from the installed metadata.json.
    mod_dir = manager.mods_dir / installed_mod_uuid
    installed_metadata = json.loads((mod_dir / "metadata.json").read_text())
    replacements = {}
    for pck_name, bnk_buckets in installed_metadata["replacements"].items():
        replacements[pck_name] = {}
        for bnk_key, files in bnk_buckets.items():
            bnk_id = None if bnk_key == "direct" else int(bnk_key[:-len(".bnk")])
            for file_id, file_info in files.items():
                tracker_key = f"{bnk_id}|{file_id}" if bnk_id is not None else file_id
                entry = {
                    "wem_path": str(mod_dir / file_info["wem_file"]),
                    "sound_name": file_info.get("sound_name", ""),
                    "lang_id": file_info.get("lang_id", 0),
                    "bnk_id": bnk_id,
                    "file_type": file_info.get("file_type", "wem"),
                }
                entry.update({key: file_info[key] for key in _AUDIO_SETTING_KEYS if key in file_info})
                replacements[pck_name][tracker_key] = entry
    return installed_metadata, replacements


def test_create_mod_package_writes_v3_metadata_and_wem_files(env):
    embedded_bytes = make_wem(100)
    streamed_bytes = make_wem(101)
    package_path = package_mod(env, "Weapon Pack", {
        env.keys.soundbank: [mod_entry(env.work_dir / "src", EMBEDDED_WEM_ID, embedded_bytes, bnk_id=SFX_BNK_ID)],
        env.keys.streamed: [mod_entry(env.work_dir / "src", STREAMED_WEM_ID, streamed_bytes)],
    })

    metadata, archive_files = read_package(package_path)

    assert metadata["format_version"] == "3.0"
    assert (metadata["name"], metadata["author"], metadata["version"], metadata["description"]) == ("Weapon Pack", "Tester", "1.0.0", "")
    assert metadata["app_version"] == app_config.APP_VERSION
    assert "thumbnail" not in metadata and "hirc_patches" not in metadata
    assert metadata["replacements"] == {
        "Full/SoundBank_SFX_0.pck": {"1001.bnk": {"110001": {"wem_file": "wem_files/1001/110001.wem", "sound_name": "", "lang_id": 0, "file_type": "bnk"}}},
        "Full/Streamed_SFX_0.pck": {"direct": {"120001": {"wem_file": "wem_files/direct/120001.wem", "sound_name": "", "lang_id": 0, "file_type": "wem"}}},
    }
    assert archive_files["wem_files/1001/110001.wem"] == embedded_bytes
    assert archive_files["wem_files/direct/120001.wem"] == streamed_bytes


def test_create_mod_package_skips_a_missing_source_wem(env):
    missing_key, missing_info = mod_entry(env.work_dir / "src", EMBEDDED_WEM_ID, make_wem(1), bnk_id=SFX_BNK_ID)
    missing_info["wem_path"] = str(env.work_dir / "does_not_exist.wem")
    package_path = package_mod(env, "Partial", {
        env.keys.soundbank: [(missing_key, missing_info)],
        env.keys.streamed: [mod_entry(env.work_dir / "src", STREAMED_WEM_ID, make_wem(2))],
    })

    metadata, archive_files = read_package(package_path)

    assert metadata["replacements"][env.keys.soundbank] == {}
    assert "wem_files/direct/120001.wem" in archive_files


def test_create_mod_package_stores_bnk_zero_under_its_own_bnk_key(env):
    package_path = package_mod(env, "Zero Bank", {"Patch.pck": [mod_entry(env.work_dir / "src", EMBEDDED_WEM_ID, make_wem(3), bnk_id=0)]})

    metadata, archive_files = read_package(package_path)

    assert metadata["replacements"]["Patch.pck"] == {"0.bnk": {"110001": {"wem_file": "wem_files/0/110001.wem", "sound_name": "", "lang_id": 0, "file_type": "bnk"}}}
    assert "wem_files/0/110001.wem" in archive_files


def test_create_mod_package_converts_the_thumbnail_to_png(env, tmp_path):
    thumbnail_source = tmp_path / "cover.jpg"
    Image.new("RGB", (8, 8), (200, 30, 30)).save(thumbnail_source, "JPEG")
    package_path = env.work_dir / "thumb.zzar"
    env.manager.create_mod_package(
        package_path,
        {"name": "Thumbnail", "author": "Tester"},
        {env.keys.streamed: dict([mod_entry(env.work_dir / "src", STREAMED_WEM_ID, make_wem(4))])},
        thumbnail_path=str(thumbnail_source),
    )

    metadata, archive_files = read_package(package_path)
    installed_mod_uuid = env.manager.install_mod(package_path)["uuid"]
    installed_mod = env.manager.get_installed_mods()[0]

    assert metadata["thumbnail"] == "thumbnail.png"
    assert archive_files["thumbnail.png"].startswith(b"\x89PNG\r\n\x1a\n")
    assert installed_mod["thumbnail_path"] == env.manager.mods_dir / installed_mod_uuid / "thumbnail.png"


def test_create_mod_package_ignores_an_unreadable_thumbnail(env, tmp_path):
    broken_thumbnail = tmp_path / "cover.png"
    broken_thumbnail.write_bytes(b"not an image")
    package_path = env.work_dir / "broken_thumb.zzar"
    env.manager.create_mod_package(
        package_path,
        {"name": "Broken Thumbnail", "author": "Tester"},
        {env.keys.streamed: dict([mod_entry(env.work_dir / "src", STREAMED_WEM_ID, make_wem(4))])},
        thumbnail_path=str(broken_thumbnail),
    )

    metadata, archive_files = read_package(package_path)

    assert "thumbnail" not in metadata
    assert "thumbnail.png" not in archive_files


@pytest.mark.parametrize(("staged_settings", "written_settings"), [
    ({}, {}),
    ({"loop_point_mode": "disabled", "loop_point_manual_ms": 5000, "volume_enabled": False, "volume_db": -3.0}, {}),
    ({"loop_point_mode": "auto"}, {"loop_point_mode": "auto"}),
    ({"loop_point_mode": "auto", "loop_point_manual_ms": 4321}, {"loop_point_mode": "auto"}),
    ({"loop_point_mode": "manual", "loop_point_manual_ms": 4321}, {"loop_point_mode": "manual", "loop_point_manual_ms": 4321}),
    ({"loop_point_mode": "manual", "loop_point_manual_ms": 0}, {"loop_point_mode": "manual"}),
    ({"volume_enabled": True}, {"volume_enabled": True}),
    ({"volume_enabled": True, "volume_db": -6.04}, {"volume_enabled": True, "volume_db": -6.0}),
    ({"volume_enabled": False, "volume_db": -6.0}, {}),
])
def test_create_mod_package_writes_audio_settings_only_when_non_default(env, staged_settings, written_settings):
    package_path = package_mod(env, "Settings", {env.keys.streamed: [mod_entry(env.work_dir / "src", STREAMED_WEM_ID, make_wem(5), **staged_settings)]})

    metadata, _ = read_package(package_path)
    written_entry = metadata["replacements"][env.keys.streamed]["direct"][str(STREAMED_WEM_ID)]

    assert {key: written_entry[key] for key in _AUDIO_SETTING_KEYS if key in written_entry} == written_settings
    assert set(written_entry) - set(_AUDIO_SETTING_KEYS) == {"wem_file", "sound_name", "lang_id", "file_type"}


def test_audio_setting_keys_list_the_four_persisted_settings():
    assert _AUDIO_SETTING_KEYS == ("loop_point_mode", "loop_point_manual_ms", "volume_enabled", "volume_db")


@pytest.mark.parametrize("staged_settings", [
    {},
    {"loop_point_mode": "manual", "loop_point_manual_ms": 1500, "volume_enabled": True, "volume_db": -2.5},
])
def test_reexporting_an_unchanged_installed_mod_keeps_its_metadata_byte_identical(env, staged_settings):
    original_package = package_mod(env, "Old Mod", {
        env.keys.soundbank: [mod_entry(env.work_dir / "src", EMBEDDED_WEM_ID, make_wem(6), bnk_id=SFX_BNK_ID, **staged_settings)],
        env.keys.streamed: [mod_entry(env.work_dir / "src", STREAMED_WEM_ID, make_wem(7))],
    })
    original_metadata, original_files = read_package(original_package)
    installed_mod_uuid = env.manager.install_mod(original_package)["uuid"]

    installed_metadata, replacements = exported_replacements(env.manager, installed_mod_uuid)
    reexported_package = env.work_dir / "reexported.zzar"
    env.manager.create_mod_package(reexported_package, installed_metadata, replacements)
    reexported_metadata, reexported_files = read_package(reexported_package)

    assert json.dumps(reexported_metadata["replacements"], indent=2) == json.dumps(original_metadata["replacements"], indent=2)
    assert {name: content for name, content in reexported_files.items() if name.startswith("wem_files/")} == {name: content for name, content in original_files.items() if name.startswith("wem_files/")}


def test_validate_accepts_a_created_package(env):
    package_path = package_mod(env, "Valid", {env.keys.streamed: [mod_entry(env.work_dir / "src", STREAMED_WEM_ID, make_wem(8))]})

    assert env.manager.validate_mod_package(package_path)["name"] == "Valid"


def test_validate_rejects_a_missing_file(env, tmp_path):
    with pytest.raises(InvalidModPackageError, match="File not found"):
        env.manager.validate_mod_package(tmp_path / "missing.zzar")


def test_validate_rejects_a_file_that_is_not_a_zip(env, tmp_path):
    not_a_zip = tmp_path / "mod.zzar"
    not_a_zip.write_bytes(b"plain text, not an archive")

    with pytest.raises(InvalidModPackageError, match="Not a valid ZIP"):
        env.manager.validate_mod_package(not_a_zip)


def test_validate_rejects_an_archive_without_metadata(env, tmp_path):
    package_path = tmp_path / "mod.zzar"
    with zipfile.ZipFile(package_path, "w") as archive:
        archive.writestr("wem_files/direct/1.wem", make_wem(1))

    with pytest.raises(InvalidModPackageError, match="Missing metadata.json"):
        env.manager.validate_mod_package(package_path)


def test_validate_rejects_malformed_metadata_json(env, tmp_path):
    package_path = write_package(tmp_path / "mod.zzar", None, raw_metadata="{not json")

    with pytest.raises(InvalidModPackageError, match="Invalid JSON"):
        env.manager.validate_mod_package(package_path)


@pytest.mark.parametrize("missing_field", ["name", "author", "version"])
def test_validate_rejects_metadata_missing_a_required_field(env, tmp_path, missing_field):
    metadata = minimal_metadata()
    del metadata[missing_field]
    package_path = write_package(tmp_path / "mod.zzar", metadata, {"wem_files/direct/120001.wem": make_wem(1)})

    with pytest.raises(InvalidModPackageError, match=f"Missing required field in metadata: {missing_field}"):
        env.manager.validate_mod_package(package_path)


def test_validate_rejects_metadata_without_replacements_or_hirc_patches(env, tmp_path):
    metadata = minimal_metadata()
    del metadata["replacements"]
    package_path = write_package(tmp_path / "mod.zzar", metadata)

    with pytest.raises(InvalidModPackageError, match="neither 'replacements' nor 'hirc_patches'"):
        env.manager.validate_mod_package(package_path)


def test_validate_accepts_a_hirc_only_mod(env, tmp_path):
    metadata = minimal_metadata(hirc_patches=[{"pck_name": "Full/SoundBank_SFX_0.pck", "bnk_id": 1003, "track_obj_id": 501, "loop_ms": 1000.0}])
    del metadata["replacements"]
    package_path = write_package(tmp_path / "mod.zzar", metadata)

    assert env.manager.validate_mod_package(package_path)["hirc_patches"][0]["track_obj_id"] == 501


@pytest.mark.parametrize("format_version", ["3.0", "1.0"])
def test_validate_rejects_a_referenced_wem_missing_from_the_archive(env, tmp_path, format_version):
    if format_version == "3.0":
        metadata = minimal_metadata()
    else:
        metadata = minimal_metadata(format_version="1.0", replacements={"Streamed_SFX_0.pck": {"120001": {"wem_file": "wem_files/120001.wem"}}})
    package_path = write_package(tmp_path / "mod.zzar", metadata)

    with pytest.raises(InvalidModPackageError, match="Referenced WEM file not found in archive"):
        env.manager.validate_mod_package(package_path)


def test_validate_defaults_a_legacy_mod_to_format_1_0(env, tmp_path):
    metadata = minimal_metadata(replacements={"Streamed_SFX_0.pck": {"120001": {"wem_file": "120001.wem"}}})
    del metadata["format_version"]
    package_path = write_package(tmp_path / "mod.zzar", metadata, {"120001.wem": make_wem(1)})

    assert env.manager.validate_mod_package(package_path)["format_version"] == "1.0"


def test_install_keeps_path_traversal_entries_inside_the_mod_dir(env, tmp_path):
    package_path = write_package(tmp_path / "packages" / "evil.zzar", minimal_metadata(), {
        "wem_files/direct/120001.wem": make_wem(1),
        "../../../escaped.txt": b"escaped",
    })

    installed_mod_uuid = env.manager.install_mod(package_path)["uuid"]

    assert list(tmp_path.rglob("escaped.txt")) == [env.manager.mods_dir / installed_mod_uuid / "escaped.txt"]


def test_validate_rejects_a_wem_file_reference_escaping_the_mod_dir(env, tmp_path):
    escaping_reference = "../../../outside.wem"
    metadata = minimal_metadata(replacements={"Full/Streamed_SFX_0.pck": {"direct": {"120001": {"wem_file": escaping_reference, "lang_id": 0, "file_type": "wem"}}}})
    package_path = write_package(tmp_path / "evil.zzar", metadata, {escaping_reference: make_wem(1)})

    with pytest.raises(InvalidModPackageError):
        env.manager.validate_mod_package(package_path)


@pytest.mark.parametrize(("metadata", "expected_count"), [
    ({"format_version": "1.0", "replacements": {"a.pck": {"1": {}, "2": {}}, "b.pck": {"3": {}}}}, 3),
    ({"format_version": "3.0", "replacements": {"a.pck": {"1.bnk": {"1": {}, "2": {}}, "direct": {"3": {}}}}}, 3),
    ({"format_version": "2.0", "replacements": {"a.pck": {"direct": {"3": {}}}}, "hirc_patches": [{}, {}]}, 3),
    ({"format_version": "3.0", "hirc_patches": [{}]}, 1),
    ("not a dict", 0),
])
def test_count_replacements_handles_every_layout(metadata, expected_count):
    assert count_replacements(metadata) == expected_count


@pytest.mark.parametrize(("metadata", "expected"), [
    ({"hirc_patches": [{"bnk_id": 1}]}, True),
    ({"replacements": {"a.pck": {"1.bnk": {"5": {"is_add": True}}}}}, True),
    ({"replacements": {"a.pck": {"5": {"is_add": True}}}}, True),
    ({"replacements": {"a.pck": {"1.bnk": {"5": {"wem_file": "x"}}}}, "hirc_patches": []}, False),
    ({"replacements": {"a.pck": "garbage"}}, False),
    (None, False),
])
def test_is_hirc_mod_detects_track_patches_and_adds(metadata, expected):
    assert is_hirc_mod(metadata) is expected


def test_install_mod_extracts_the_package_and_persists_the_config(env):
    package_path = package_mod(env, "Installed", {env.keys.streamed: [mod_entry(env.work_dir / "src", STREAMED_WEM_ID, make_wem(9))]}, version="2.1.0")

    install_result = env.manager.install_mod(package_path)
    mod_dir = env.manager.mods_dir / install_result["uuid"]
    saved_config = json.loads(env.manager.config_path.read_text())

    assert {key: install_result[key] for key in ("replaced", "mod_name", "version")} == {"replaced": False, "mod_name": "Installed", "version": "2.1.0"}
    assert (mod_dir / "wem_files" / "direct" / "120001.wem").read_bytes() == make_wem(9)
    assert json.loads((mod_dir / "metadata.json").read_text())["name"] == "Installed"
    assert saved_config["load_order"] == [install_result["uuid"]]
    assert saved_config["installed_mods"][install_result["uuid"]]["enabled"] is False
    assert saved_config["installed_mods"][install_result["uuid"]]["metadata"]["version"] == "2.1.0"


def test_get_installed_mods_follows_the_load_order(env):
    first_mod_uuid = env.manager.install_mod(package_mod(env, "First", {env.keys.streamed: [mod_entry(env.work_dir / "a", STREAMED_WEM_ID, make_wem(1))]}))["uuid"]
    second_mod_uuid = env.manager.install_mod(package_mod(env, "Second", {env.keys.streamed: [mod_entry(env.work_dir / "b", STREAMED_WEM_ID, make_wem(2))]}))["uuid"]

    env.manager.update_load_order([second_mod_uuid, first_mod_uuid])
    installed_mods = env.manager.get_installed_mods()

    assert [(mod["uuid"], mod["priority"], mod["metadata"]["name"]) for mod in installed_mods] == [(second_mod_uuid, 0, "Second"), (first_mod_uuid, 1, "First")]
    assert all(mod["thumbnail_path"] is None and mod["enabled"] is False for mod in installed_mods)


def test_enabled_state_and_load_order_survive_a_reload(env):
    first_mod_uuid = env.manager.install_mod(package_mod(env, "First", {env.keys.streamed: [mod_entry(env.work_dir / "a", STREAMED_WEM_ID, make_wem(1))]}))["uuid"]
    second_mod_uuid = env.manager.install_mod(package_mod(env, "Second", {env.keys.streamed: [mod_entry(env.work_dir / "b", STREAMED_WEM_ID, make_wem(2))]}))["uuid"]
    env.manager.set_mod_enabled(second_mod_uuid, True)
    env.manager.update_load_order([second_mod_uuid, first_mod_uuid])

    reloaded_manager = ModPackageManager(game_id="zzz")

    assert [(mod["uuid"], mod["enabled"]) for mod in reloaded_manager.get_installed_mods()] == [(second_mod_uuid, True), (first_mod_uuid, False)]


def test_set_all_mods_enabled_toggles_every_mod(env):
    for index in range(3):
        env.manager.install_mod(package_mod(env, f"Mod {index}", {env.keys.streamed: [mod_entry(env.work_dir / str(index), STREAMED_WEM_ID, make_wem(index))]}))

    env.manager.set_all_mods_enabled(True)
    enabled_after_enable = [mod["enabled"] for mod in ModPackageManager(game_id="zzz").get_installed_mods()]
    env.manager.set_all_mods_enabled(False)
    enabled_after_disable = [mod["enabled"] for mod in ModPackageManager(game_id="zzz").get_installed_mods()]

    assert enabled_after_enable == [True, True, True]
    assert enabled_after_disable == [False, False, False]


def test_remove_mod_deletes_its_files_and_config_entry(env):
    kept_mod_uuid = env.manager.install_mod(package_mod(env, "Kept", {env.keys.streamed: [mod_entry(env.work_dir / "a", STREAMED_WEM_ID, make_wem(1))]}))["uuid"]
    removed_mod_uuid = env.manager.install_mod(package_mod(env, "Removed", {env.keys.streamed: [mod_entry(env.work_dir / "b", STREAMED_WEM_ID, make_wem(2))]}))["uuid"]

    env.manager.remove_mod(removed_mod_uuid)
    saved_config = json.loads(env.manager.config_path.read_text())

    assert not (env.manager.mods_dir / removed_mod_uuid).exists()
    assert saved_config["load_order"] == [kept_mod_uuid]
    assert list(saved_config["installed_mods"]) == [kept_mod_uuid]


def test_update_load_order_rejects_an_unknown_uuid(env):
    installed_mod_uuid = env.manager.install_mod(package_mod(env, "Only", {env.keys.streamed: [mod_entry(env.work_dir / "a", STREAMED_WEM_ID, make_wem(1))]}))["uuid"]

    with pytest.raises(ValueError, match="Unknown mod UUID"):
        env.manager.update_load_order([installed_mod_uuid, "not-installed"])

    assert json.loads(env.manager.config_path.read_text())["load_order"] == [installed_mod_uuid]


@pytest.mark.parametrize(("new_version", "replaces"), [("1.1.0", True), ("1.0", True), ("0.9.9", False)])
def test_installing_a_mod_with_the_same_name_compares_versions(env, new_version, replaces):
    old_mod_uuid = env.manager.install_mod(package_mod(env, "Versioned", {env.keys.streamed: [mod_entry(env.work_dir / "old", STREAMED_WEM_ID, make_wem(1))]}, version="1.0.0"))["uuid"]

    install_result = env.manager.install_mod(package_mod(env, "Versioned", {env.keys.streamed: [mod_entry(env.work_dir / "new", STREAMED_WEM_ID, make_wem(2))]}, version=new_version))
    installed_versions = [mod["metadata"]["version"] for mod in env.manager.get_installed_mods()]

    if replaces:
        assert install_result["replaced"] is True
        assert installed_versions == [new_version]
        assert not (env.manager.mods_dir / old_mod_uuid).exists()
    else:
        assert install_result is None
        assert installed_versions == ["1.0.0"]
        assert (env.manager.mods_dir / old_mod_uuid).exists()


def test_custom_mod_library_root_holds_the_mods(env, tmp_path):
    custom_library = tmp_path / "custom_library"
    settings = read_settings()
    settings[get_custom_mod_library_settings_key("zzz")] = str(custom_library)
    write_settings(settings)

    custom_manager = ModPackageManager(game_id="zzz")
    installed_mod_uuid = custom_manager.install_mod(package_mod(env, "Relocated", {env.keys.streamed: [mod_entry(env.work_dir / "a", STREAMED_WEM_ID, make_wem(1))]}))["uuid"]

    assert custom_manager.mod_library_path == custom_library
    assert (custom_library / "mods" / installed_mod_uuid / "metadata.json").exists()
    assert list(json.loads((custom_library / "mod_config.json").read_text())["installed_mods"]) == [installed_mod_uuid]
    assert not (get_game_mod_library_dir("zzz") / "mods" / installed_mod_uuid).exists()


def test_explicit_mod_library_path_overrides_settings(env, tmp_path):
    explicit_library = tmp_path / "explicit"

    explicit_manager = ModPackageManager(mod_library_path=explicit_library, game_id="zzz")

    assert explicit_manager.config_path == explicit_library / "mod_config.json"
    assert (explicit_library / "mods").is_dir()


@pytest.mark.parametrize(("game_id", "mod_file_ext"), [("zzz", ".zzar"), ("genshin", ".giar"), ("hsr", ".srar")])
def test_each_game_uses_its_own_extension_and_library(tmp_path, game_id, mod_file_ext):
    app_config.switch_active_game(game_id)
    game_env = make_mod_env(tmp_path, game_id)

    installed_mod_uuid = install_enabled(game_env, "Per Game", {game_env.keys.streamed: [mod_entry(game_env.work_dir / "src", STREAMED_WEM_ID, make_wem(1))]})
    other_game_ids = {"zzz", "genshin", "hsr"} - {game_id}

    assert app_config.MOD_FILE_EXT == mod_file_ext
    assert game_env.manager.mod_library_path == get_game_mod_library_dir(game_id)
    assert (get_game_mod_library_dir(game_id) / "mods" / installed_mod_uuid).is_dir()
    assert all(ModPackageManager(game_id=other_game_id).get_installed_mods() == [] for other_game_id in other_game_ids)


def test_manager_without_game_id_follows_the_selected_game(env):
    settings = read_settings()
    settings["selected_game"] = "hsr"
    write_settings(settings)

    assert ModPackageManager().game_id == "hsr"


def test_corrupt_mod_config_loads_as_an_empty_library(env):
    env.manager.config_path.write_text("{broken")

    reloaded_manager = ModPackageManager(game_id="zzz")

    assert reloaded_manager.mod_config == {"installed_mods": {}, "load_order": []}


def test_a_mod_whose_folder_vanished_is_dropped_from_the_config(env):
    kept_mod_uuid = install_enabled(env, "Kept", {env.keys.streamed: [mod_entry(env.work_dir / "a", STREAMED_WEM_ID, make_wem(1))]})
    vanished_mod_uuid = install_enabled(env, "Vanished", {env.keys.soundbank: [mod_entry(env.work_dir / "b", EMBEDDED_WEM_ID, make_wem(2), bnk_id=SFX_BNK_ID)]})
    shutil.rmtree(env.manager.mods_dir / vanished_mod_uuid)

    resolved = env.manager.resolve_conflicts()

    assert [mod["uuid"] for mod in env.manager.get_installed_mods()] == [kept_mod_uuid]
    assert list(resolved) == [env.keys.streamed]
    assert json.loads(env.manager.config_path.read_text())["load_order"] == [kept_mod_uuid]


def test_resolve_conflicts_skips_an_installed_wem_file_escaping_the_mod_dir(env):
    installed_mod_uuid = install_enabled(env, "Tampered", {env.keys.streamed: [mod_entry(env.work_dir / "a", STREAMED_WEM_ID, make_wem(1))]})
    installed_replacements = env.manager.mod_config["installed_mods"][installed_mod_uuid]["metadata"]["replacements"]
    installed_replacements[env.keys.streamed]["direct"][str(STREAMED_WEM_ID)]["wem_file"] = "../../outside.wem"

    assert env.manager.resolve_conflicts() == {env.keys.streamed: {}}


def test_resolve_conflicts_lets_the_later_mod_in_load_order_win(env):
    conflict_key = f"{SFX_BNK_ID}|{EMBEDDED_WEM_ID}"
    earlier_mod_uuid = install_enabled(env, "Earlier", {env.keys.soundbank: [mod_entry(env.work_dir / "a", EMBEDDED_WEM_ID, make_wem(1), bnk_id=SFX_BNK_ID)]})
    later_mod_uuid = install_enabled(env, "Later", {env.keys.soundbank: [mod_entry(env.work_dir / "b", EMBEDDED_WEM_ID, make_wem(2), bnk_id=SFX_BNK_ID)]})

    winner_by_load_order = env.manager.resolve_conflicts()[env.keys.soundbank][conflict_key]
    env.manager.update_load_order([later_mod_uuid, earlier_mod_uuid])
    winner_after_reorder = env.manager.resolve_conflicts()[env.keys.soundbank][conflict_key]

    assert (winner_by_load_order["mod_name"], winner_by_load_order["conflicts_with"]) == ("Later", [earlier_mod_uuid])
    assert (winner_after_reorder["mod_name"], winner_after_reorder["conflicts_with"]) == ("Earlier", [later_mod_uuid])
    assert winner_after_reorder["wem_path"] == str(env.manager.mods_dir / earlier_mod_uuid / "wem_files" / "1001" / "110001.wem")


def test_resolve_conflicts_honors_an_explicit_preference(env):
    conflict_key = f"{SFX_BNK_ID}|{EMBEDDED_WEM_ID}"
    install_enabled(env, "Earlier", {env.keys.soundbank: [mod_entry(env.work_dir / "a", EMBEDDED_WEM_ID, make_wem(1), bnk_id=SFX_BNK_ID)]})
    install_enabled(env, "Later", {env.keys.soundbank: [mod_entry(env.work_dir / "b", EMBEDDED_WEM_ID, make_wem(2), bnk_id=SFX_BNK_ID)]})

    resolved = env.manager.resolve_conflicts(preferences={f"{env.keys.soundbank}:{conflict_key}": "Earlier", "malformed-key": "Later"})

    assert resolved[env.keys.soundbank][conflict_key]["mod_name"] == "Earlier"


def test_resolve_conflicts_ignores_disabled_mods(env):
    install_enabled(env, "Enabled", {env.keys.soundbank: [mod_entry(env.work_dir / "a", EMBEDDED_WEM_ID, make_wem(1), bnk_id=SFX_BNK_ID)]})
    disabled_mod_uuid = install_enabled(env, "Disabled", {env.keys.soundbank: [mod_entry(env.work_dir / "b", EMBEDDED_WEM_ID, make_wem(2), bnk_id=SFX_BNK_ID)]})
    env.manager.set_mod_enabled(disabled_mod_uuid, False)

    winner = env.manager.resolve_conflicts()[env.keys.soundbank][f"{SFX_BNK_ID}|{EMBEDDED_WEM_ID}"]

    assert (winner["mod_name"], winner["conflicts_with"]) == ("Enabled", [])


def test_resolve_conflicts_collides_a_legacy_flat_mod_with_a_v3_mod(env, tmp_path):
    legacy_metadata = {
        "format_version": "1.0", "name": "Legacy", "author": "Old", "version": "1.0.0",
        "replacements": {env.keys.soundbank: {str(EMBEDDED_WEM_ID): {"wem_file": "legacy.wem", "bnk_id": SFX_BNK_ID, "file_type": "bnk"}}},
    }
    legacy_mod_uuid = env.manager.install_mod(write_package(tmp_path / "legacy.zzar", legacy_metadata, {"legacy.wem": make_wem(1)}))["uuid"]
    env.manager.set_mod_enabled(legacy_mod_uuid, True)
    install_enabled(env, "Modern", {env.keys.soundbank: [mod_entry(env.work_dir / "b", EMBEDDED_WEM_ID, make_wem(2), bnk_id=SFX_BNK_ID)]})

    resolved_entries = env.manager.resolve_conflicts()[env.keys.soundbank]

    assert list(resolved_entries) == [f"{SFX_BNK_ID}|{EMBEDDED_WEM_ID}"]
    assert resolved_entries[f"{SFX_BNK_ID}|{EMBEDDED_WEM_ID}"]["conflicts_with"] == [legacy_mod_uuid]


def test_resolve_conflicts_carries_audio_settings_and_add_flags(env):
    install_enabled(env, "Settings", {env.keys.streamed: [
        mod_entry(env.work_dir / "a", STREAMED_WEM_ID, make_wem(1), loop_point_mode="manual", loop_point_manual_ms=2500, volume_enabled=True, volume_db=-3.5),
        mod_entry(env.work_dir / "a", 4000000001, make_wem(2), is_add=True),
    ]})

    resolved_entries = env.manager.resolve_conflicts()[env.keys.streamed]

    assert {key: resolved_entries[str(STREAMED_WEM_ID)][key] for key in _AUDIO_SETTING_KEYS} == {"loop_point_mode": "manual", "loop_point_manual_ms": 2500, "volume_enabled": True, "volume_db": -3.5}
    assert resolved_entries["4000000001"]["is_add"] is True
    assert not any(key in resolved_entries["4000000001"] for key in _AUDIO_SETTING_KEYS)


def test_conflict_summaries_name_winners_and_losers(env):
    install_enabled(env, "Alpha", {
        env.keys.soundbank: [mod_entry(env.work_dir / "a", EMBEDDED_WEM_ID, make_wem(1), bnk_id=SFX_BNK_ID), mod_entry(env.work_dir / "a", SHARED_WEM_ID, make_wem(2), bnk_id=SFX_BNK_ID)],
        env.keys.streamed: [mod_entry(env.work_dir / "a", STREAMED_WEM_ID, make_wem(3))],
    })
    install_enabled(env, "Beta", {env.keys.soundbank: [mod_entry(env.work_dir / "b", EMBEDDED_WEM_ID, make_wem(4), bnk_id=SFX_BNK_ID), mod_entry(env.work_dir / "b", SHARED_WEM_ID, make_wem(5), bnk_id=SFX_BNK_ID)]})

    summary = env.manager.get_mod_conflicts_summary()

    assert summary["total_replacements"] == 3
    assert sorted(summary["affected_pcks"]) == sorted([env.keys.soundbank, env.keys.streamed])
    assert sorted((conflict["file_id"], conflict["winner_mod"], tuple(conflict["loser_mods"])) for conflict in summary["conflicts"]) == [
        (f"{SFX_BNK_ID}|{EMBEDDED_WEM_ID}", "Beta", ("Alpha",)),
        (f"{SFX_BNK_ID}|{SHARED_WEM_ID}", "Beta", ("Alpha",)),
    ]
    assert [(pair["mods"], pair["winner_mod"], pair["conflict_count"]) for pair in summary["mod_conflicts"]] == [(["Alpha", "Beta"], "Beta", 2)]


def test_conflict_summary_without_conflicts_has_no_mod_pairs(env):
    install_enabled(env, "Alone", {env.keys.streamed: [mod_entry(env.work_dir / "a", STREAMED_WEM_ID, make_wem(1))]})

    summary = env.manager.get_mod_conflicts_summary()

    assert summary == {"total_replacements": 1, "affected_pcks": [env.keys.streamed], "conflicts": []}
