import json
import os
import time
from pathlib import Path

import pytest

from src.core import migration
from src.core.migration import run_migrations


@pytest.fixture
def user_dirs(isolated_user_dirs):
    return isolated_user_dirs.config_dir, isolated_user_dirs.data_dir


def write_file(path, content="data"):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def tree_snapshot(*roots):
    snapshot = {}
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.is_file() and path.name != "migration.log":
                snapshot[str(path.relative_to(root.parent))] = path.read_bytes()
    return snapshot


def test_fresh_install_is_a_noop(user_dirs):
    roaming, local = user_dirs
    run_migrations()
    assert not roaming.exists()
    assert {entry.name for entry in local.iterdir()} <= {"logs"}
    assert not (local / ".migration.lock").exists()


def test_current_layout_is_left_untouched(user_dirs):
    roaming, local = user_dirs
    write_file(roaming / "games" / "zzz" / "mod_library" / "mod_config.json", "{}")
    write_file(local / "tools" / "ffmpeg.exe", "binary")
    write_file(local / "state" / "zzz" / "originals_index.json", "{}")
    before = tree_snapshot(roaming, local)
    run_migrations()
    assert tree_snapshot(roaming, local) == before


def test_games_move_from_local_to_roaming(user_dirs):
    roaming, local = user_dirs
    write_file(local / "games" / "zzz" / "mod_library" / "mods" / "abc" / "metadata.json", '{"name": "abc"}')
    write_file(local / "games" / "genshin" / "sound_database.json", "{}")
    run_migrations()
    assert (roaming / "games" / "zzz" / "mod_library" / "mods" / "abc" / "metadata.json").read_text(encoding="utf-8") == '{"name": "abc"}'
    assert (roaming / "games" / "genshin" / "sound_database.json").exists()
    assert not (local / "games").exists()


def test_tools_move_from_roaming_to_local(user_dirs):
    roaming, local = user_dirs
    write_file(roaming / "tools" / "ffmpeg" / "ffmpeg.exe", "ffmpeg")
    write_file(roaming / "tools" / "vgmstream" / "vgmstream-cli.exe", "vgmstream")
    run_migrations()
    assert (local / "tools" / "ffmpeg" / "ffmpeg.exe").read_text(encoding="utf-8") == "ffmpeg"
    assert (local / "tools" / "vgmstream" / "vgmstream-cli.exe").exists()
    assert not (roaming / "tools").exists()


def test_backup_dir_is_renamed_to_state(user_dirs):
    _, local = user_dirs
    write_file(local / "backup" / "hsr" / "originals_index.json", '{"entries": {}}')
    run_migrations()
    assert (local / "state" / "hsr" / "originals_index.json").read_text(encoding="utf-8") == '{"entries": {}}'
    assert not (local / "backup").exists()


def test_stale_trees_are_dropped(user_dirs):
    roaming, local = user_dirs
    write_file(local / "launcher" / "cache" / "qml" / "Main.qmlc")
    write_file(local / "launcher" / "cache" / "XXAR-Installer-v1.0.0.exe")
    write_file(local / "XXAR" / "cache" / "qtpipelinecache" / "cache.bin")
    write_file(roaming / "temp" / "scratch.wav")
    write_file(local / "XXAR.lnk", "shortcut")
    run_migrations()
    assert not (local / "launcher").exists()
    assert not (local / "XXAR").exists()
    assert not (roaming / "temp").exists()
    assert not (local / "XXAR.lnk").exists()


def test_run_migrations_is_idempotent(user_dirs):
    roaming, local = user_dirs
    write_file(local / "games" / "zzz" / "mod_library" / "mod_config.json", '{"load_order": []}')
    write_file(roaming / "tools" / "ffmpeg.exe", "ffmpeg")
    write_file(local / "backup" / "zzz" / "originals_index.json", "{}")
    write_file(local / "launcher" / "old.exe")
    run_migrations()
    after_first_run = tree_snapshot(roaming, local)
    run_migrations()
    assert tree_snapshot(roaming, local) == after_first_run
    assert not (local / ".migration.lock").exists()


def test_resume_keeps_same_size_destination_files_and_fills_missing_ones(user_dirs):
    roaming, local = user_dirs
    write_file(local / "games" / "zzz" / "mod_library" / "mod_config.json", "LOCAL")
    write_file(local / "games" / "zzz" / "mod_library" / "mods" / "only_local.zzar", "only local")
    write_file(roaming / "games" / "zzz" / "mod_library" / "mod_config.json", "ROAMG")
    write_file(roaming / "games" / "zzz" / "mod_library" / "mods" / "only_roaming.zzar", "only roaming")
    run_migrations()
    roaming_library = roaming / "games" / "zzz" / "mod_library"
    assert (roaming_library / "mod_config.json").read_text(encoding="utf-8") == "ROAMG"
    assert (roaming_library / "mods" / "only_local.zzar").read_text(encoding="utf-8") == "only local"
    assert (roaming_library / "mods" / "only_roaming.zzar").read_text(encoding="utf-8") == "only roaming"
    assert not (local / "games").exists()


def test_resume_completes_a_partially_copied_destination_file(user_dirs):
    roaming, local = user_dirs
    write_file(roaming / "tools" / "ffmpeg.exe", "full ffmpeg binary")
    write_file(local / "tools" / "ffmpeg.exe", "full ff")
    run_migrations()
    assert (local / "tools" / "ffmpeg.exe").read_text(encoding="utf-8") == "full ffmpeg binary"
    assert not (roaming / "tools").exists()


def test_empty_destination_tree_is_replaced_by_the_source(user_dirs):
    roaming, local = user_dirs
    (roaming / "games" / "zzz" / "empty_dir").mkdir(parents=True)
    write_file(local / "games" / "zzz" / "mod_library" / "mod_config.json", "{}")
    run_migrations()
    assert (roaming / "games" / "zzz" / "mod_library" / "mod_config.json").exists()
    assert not (local / "games").exists()


def test_legacy_mod_state_moves_to_the_selected_game(user_dirs):
    roaming, local = user_dirs
    local_games = local / "games"
    write_file(roaming / "settings.json", json.dumps({"selected_game": "genshin"}))
    write_file(roaming / "mod_config.json", json.dumps({"installed_mods": {}, "load_order": ["a"]}))
    tracker = {
        "Music.pck": {
            "1": {"wem_path": str(local_games / "genshin" / "mod_library" / "mods" / "a" / "1.wem")},
            "2": {"wem_path": str(local_games / "genshin" / "x.wem").upper()},
            "3": {"wem_path": "D:/elsewhere/3.wem"},
            "4": "not a dict",
        },
        "broken": [],
    }
    write_file(roaming / "mod_tracker.json", json.dumps(tracker))
    run_migrations()
    target_dir = roaming / "games" / "genshin"
    assert json.loads((target_dir / "mod_config.json").read_text(encoding="utf-8"))["load_order"] == ["a"]
    migrated_tracker = json.loads((target_dir / "mod_tracker.json").read_text(encoding="utf-8"))
    roaming_games = str(roaming / "games")
    assert migrated_tracker["Music.pck"]["1"]["wem_path"] == str(roaming / "games" / "genshin" / "mod_library" / "mods" / "a" / "1.wem")
    assert migrated_tracker["Music.pck"]["2"]["wem_path"].startswith(roaming_games)
    assert migrated_tracker["Music.pck"]["3"]["wem_path"] == "D:/elsewhere/3.wem"
    assert migrated_tracker["Music.pck"]["4"] == "not a dict"
    assert not (roaming / "mod_config.json").exists()
    assert not (roaming / "mod_tracker.json").exists()


def test_legacy_mod_state_defaults_to_zzz_on_malformed_settings(user_dirs):
    roaming, _ = user_dirs
    write_file(roaming / "settings.json", "{broken")
    write_file(roaming / "mod_config.json", "{}")
    run_migrations()
    assert (roaming / "games" / "zzz" / "mod_config.json").exists()


def test_legacy_mod_state_never_overwrites_existing_per_game_files(user_dirs):
    roaming, _ = user_dirs
    write_file(roaming / "mod_config.json", '{"legacy": true}')
    write_file(roaming / "mod_tracker.json", '{"legacy": {}}')
    write_file(roaming / "games" / "zzz" / "mod_config.json", '{"current": true}')
    write_file(roaming / "games" / "zzz" / "mod_tracker.json", '{"current": {}}')
    run_migrations()
    assert json.loads((roaming / "games" / "zzz" / "mod_config.json").read_text(encoding="utf-8")) == {"current": True}
    assert json.loads((roaming / "games" / "zzz" / "mod_tracker.json").read_text(encoding="utf-8")) == {"current": {}}
    assert (roaming / "mod_config.json").exists()
    assert (roaming / "mod_tracker.json").exists()


def test_unreadable_legacy_tracker_is_left_in_place(user_dirs):
    roaming, _ = user_dirs
    write_file(roaming / "mod_tracker.json", "{broken")
    run_migrations()
    assert (roaming / "mod_tracker.json").read_text(encoding="utf-8") == "{broken"
    assert not (roaming / "games" / "zzz" / "mod_tracker.json").exists()


def test_fresh_lock_from_another_migration_skips_the_run(user_dirs):
    roaming, local = user_dirs
    write_file(local / "games" / "zzz" / "mod_config.json")
    write_file(local / ".migration.lock", "4242")
    run_migrations()
    assert (local / "games" / "zzz" / "mod_config.json").exists()
    assert not (roaming / "games").exists()
    assert (local / ".migration.lock").exists()


def test_stale_lock_is_reclaimed(user_dirs):
    roaming, local = user_dirs
    write_file(local / "games" / "zzz" / "mod_config.json")
    lock_path = write_file(local / ".migration.lock", "4242")
    stale_time = time.time() - migration.LOCK_STALE_SECONDS - 60
    os.utime(lock_path, (stale_time, stale_time))
    run_migrations()
    assert (roaming / "games" / "zzz" / "mod_config.json").exists()
    assert not lock_path.exists()


def test_migration_writes_its_log_under_local_logs(user_dirs):
    _, local = user_dirs
    write_file(local / "backup" / "zzz" / "originals_index.json")
    run_migrations()
    assert "Migrating" in (local / "logs" / "migration.log").read_text(encoding="utf-8")


def test_non_windows_platforms_are_never_migrated(user_dirs, monkeypatch):
    roaming, local = user_dirs
    monkeypatch.setattr(migration, "IS_WINDOWS", False)
    write_file(local / "games" / "zzz" / "mod_config.json")
    run_migrations()
    assert (local / "games" / "zzz" / "mod_config.json").exists()
    assert not roaming.exists()
