from pathlib import Path

from src.core.config_manager import get_settings_file
from src.gui.utils.path_memory import get_last_dir, save_last_dir
from helpers import read_settings, write_settings


def test_saved_directory_round_trips(tmp_path):
    save_last_dir("import_audio", tmp_path)
    assert get_last_dir("import_audio") == str(tmp_path)
    assert read_settings()["last_dirs"] == {"import_audio": str(tmp_path)}


def test_saving_a_file_path_remembers_its_folder(tmp_path):
    picked_file = tmp_path / "song.wav"
    picked_file.write_bytes(b"RIFF")
    save_last_dir("import_audio", picked_file)
    assert get_last_dir("import_audio") == str(tmp_path)


def test_keys_are_independent_and_other_settings_survive(tmp_path):
    write_settings({"selected_game": "hsr", "last_dirs": {"export_mod": str(tmp_path)}})
    import_dir = tmp_path / "imports"
    import_dir.mkdir()
    save_last_dir("import_audio", import_dir)
    settings = read_settings()
    assert settings["selected_game"] == "hsr"
    assert settings["last_dirs"] == {"export_mod": str(tmp_path), "import_audio": str(import_dir)}


def test_missing_directory_falls_back(tmp_path):
    save_last_dir("import_audio", tmp_path / "gone" / "song.wav")
    assert get_last_dir("import_audio", fallback=str(tmp_path)) == str(tmp_path)
    assert get_last_dir("import_audio") == str(Path.home())


def test_unknown_or_empty_key_falls_back(tmp_path):
    assert get_last_dir("never_saved", fallback="D:/fallback") == "D:/fallback"
    assert get_last_dir("", fallback="D:/fallback") == "D:/fallback"
    assert get_last_dir(None) == str(Path.home())


def test_empty_key_or_path_is_not_saved(tmp_path):
    save_last_dir("", tmp_path)
    save_last_dir("import_audio", "")
    save_last_dir("import_audio", None)
    assert not get_settings_file().exists()


def test_malformed_settings_file_is_tolerated(tmp_path):
    get_settings_file().write_text("{broken", encoding="utf-8")
    assert get_last_dir("import_audio", fallback="D:/fallback") == "D:/fallback"
    save_last_dir("import_audio", tmp_path)
    assert get_last_dir("import_audio") == str(tmp_path)


def test_non_dict_last_dirs_is_replaced_on_save(tmp_path):
    write_settings({"last_dirs": ["not", "a", "dict"]})
    save_last_dir("import_audio", tmp_path)
    assert read_settings()["last_dirs"] == {"import_audio": str(tmp_path)}


def test_non_dict_last_dirs_falls_back_on_read():
    write_settings({"last_dirs": ["not", "a", "dict"]})
    assert get_last_dir("import_audio", fallback="D:/fallback") == "D:/fallback"
