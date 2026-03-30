import configparser
import hashlib
import json
import shutil
import threading
from pathlib import Path

from src.config_manager import get_game_data_dir
from src.game_registry import get_game

from .base_handler import BaseBrowserHandler

# Signalled when no backup is in progress; restore/save_patched_hashes wait on it.
_backup_done = threading.Event()
_backup_done.set()

# Subfolder inside the app data dir that stores the original VO backup.
_BACKUP_DIR_NAME = "original_vo"

# File that records the game version at the time the backup was taken.
_VERSION_FILE_NAME = "vo_version.txt"

# JSON file that stores per-PCK hashes (original + patched).
_HASHES_FILE_NAME = "vo_hashes.json"


def _vo_folder_names(game):
    # Derive VO folder names from the game definition.
    non_lang = set(game.non_language_tabs or ())
    return {name for name, _ in game.language_folders if name not in non_lang}


def _read_game_version(data_folder: Path) -> str | None:
    # Read game_version from the game's *config.ini*.
    config_ini = data_folder.parent / "config.ini"
    if not config_ini.is_file():
        return None
    try:
        cp = configparser.ConfigParser()
        cp.read(str(config_ini), encoding="utf-8")
        return cp.get("general", "game_version", fallback=None)
    except Exception:
        return None


def _backup_needed(app_game_dir: Path, current_version: str) -> bool:
    """Return *True* when the VO backup is missing or outdated."""
    version_file = app_game_dir / _VERSION_FILE_NAME
    if not version_file.is_file():
        return True
    try:
        saved = version_file.read_text(encoding="utf-8").strip()
    except Exception:
        return True
    return saved != current_version


# Hash helpers 
def _compute_file_hash(filepath: Path) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_hashes(app_game_dir: Path) -> dict:
    hashes_file = app_game_dir / _HASHES_FILE_NAME
    if not hashes_file.is_file():
        return {}
    try:
        return json.loads(hashes_file.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_hashes(app_game_dir: Path, hashes: dict):
    hashes_file = app_game_dir / _HASHES_FILE_NAME
    hashes_file.write_text(json.dumps(hashes, indent=2), encoding="utf-8")


# Selective backup
def _selective_backup(persistent_root: Path, backup_dir: Path,
                      vo_names: set, hashes: dict) -> int:
    """Copy only PCK files whose hash differs from both stored original and
    patched hashes (i.e. files the game actually replaced during an update).

    Returns the number of files copied.
    """
    copied = 0
    for folder in sorted(persistent_root.iterdir()):
        if not folder.is_dir() or folder.name not in vo_names:
            continue

        dest_folder = backup_dir / folder.name
        dest_folder.mkdir(parents=True, exist_ok=True)

        for pck in sorted(folder.glob("*.pck")):
            rel_key = f"{folder.name}/{pck.name}"
            current_hash = _compute_file_hash(pck)

            stored = hashes.get(rel_key, {})
            if current_hash == stored.get("original") or \
               current_hash == stored.get("patched"):
                continue

            # Hash differs from both -> game updated this file.
            shutil.copy2(pck, dest_folder / pck.name)
            hashes[rel_key] = {"original": current_hash, "patched": None}
            copied += 1
            print(f"[HSR VO Backup] Updated {rel_key}")

    return copied


class SRARBrowserHandler(BaseBrowserHandler):
    game_id = "hsr"

    def scan_language_folders(self, data_folder):
        """Override to run the VO backup check before the normal scan."""
        self._ensure_vo_backup(data_folder)
        super().scan_language_folders(data_folder)

    # VO backup
    def _ensure_vo_backup(self, data_folder: Path):
        """Back up original VO PCK files from Persistent when the game
        updates (new ``game_version`` in *config.ini*).
        """
        current_version = _read_game_version(data_folder)
        if not current_version:
            print("[HSR VO Backup] Could not read game_version from config.ini")
            return

        app_game_dir = get_game_data_dir(self.game_id)
        if not _backup_needed(app_game_dir, current_version):
            print(
                f"[HSR VO Backup] Backup up-to-date (version {current_version})"
            )
            return

        persistent_root = data_folder.joinpath(*self.game.persistent_audio_subpath)
        if not persistent_root.is_dir():
            print(f"[HSR VO Backup] Persistent folder not found: {persistent_root}")
            return

        backup_dir = app_game_dir / _BACKUP_DIR_NAME
        backup_dir.mkdir(parents=True, exist_ok=True)
        vo_names = _vo_folder_names(self.game)

        self._emit_status("Backing up HSR voice-over files...")

        _backup_done.clear()
        thread = threading.Thread(
            target=self._run_vo_backup,
            args=(persistent_root, backup_dir, vo_names,
                  app_game_dir, current_version),
            daemon=True,
        )
        thread.start()

    def _run_vo_backup(self, persistent_root, backup_dir, vo_names,
                       app_game_dir, version):
        try:
            hashes = _load_hashes(app_game_dir)
            copied = _selective_backup(
                persistent_root, backup_dir, vo_names, hashes
            )
            _save_hashes(app_game_dir, hashes)

            version_file = app_game_dir / _VERSION_FILE_NAME
            version_file.write_text(version, encoding="utf-8")

            if copied > 0:
                self._emit_status(
                    f"HSR voice-over backup complete "
                    f"({copied} file(s) updated, v{version})"
                )
                print(
                    f"[HSR VO Backup] Backed up {copied} file(s) "
                    f"(version {version})"
                )
            else:
                print(
                    f"[HSR VO Backup] No files changed, version updated "
                    f"to {version}"
                )
        except Exception as e:
            print(f"[HSR VO Backup] Error: {e}")
            self._emit_status(f"HSR voice-over backup failed: {e}")
        finally:
            _backup_done.set()

    # Persistent cleanup policy
    @staticmethod
    def should_skip_persistent_cleanup_folder(_lang_folder, _pck_count):
        # VO folders in Persistent are NEVER deleted.
        return True

    @staticmethod
    def restore_persistent_originals(persistent_path):
        # Restore VO folders in Persistent from backup before applying mods.
        _backup_done.wait()
        game = get_game("hsr")
        vo_names = _vo_folder_names(game)
        backup_root = get_game_data_dir("hsr") / _BACKUP_DIR_NAME

        if not backup_root.is_dir():
            return

        persistent_path = Path(persistent_path)
        restored = 0

        for backup_folder in sorted(backup_root.iterdir()):
            if not backup_folder.is_dir():
                continue
            if backup_folder.name not in vo_names:
                continue
            if not any(backup_folder.glob("*.pck")):
                continue

            dest = persistent_path / backup_folder.name
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(backup_folder, dest)
            restored += 1
            print(f"[HSR VO Restore] Restored {backup_folder.name} → {dest}")

        if restored:
            print(f"[HSR VO Restore] Restored {restored} VO folder(s)")

    # Patched hash tracking
    @staticmethod
    def save_patched_hashes(persistent_path):
        # Hash all PCK files in Persistent VO folders after mod application
        _backup_done.wait()
        game = get_game("hsr")
        vo_names = _vo_folder_names(game)
        app_game_dir = get_game_data_dir("hsr")
        hashes = _load_hashes(app_game_dir)

        persistent_path = Path(persistent_path)
        updated = 0

        for folder in sorted(persistent_path.iterdir()):
            if not folder.is_dir() or folder.name not in vo_names:
                continue
            for pck in sorted(folder.glob("*.pck")):
                rel_key = f"{folder.name}/{pck.name}"
                current_hash = _compute_file_hash(pck)
                entry = hashes.setdefault(rel_key, {"original": None})
                entry["patched"] = current_hash
                updated += 1

        _save_hashes(app_game_dir, hashes)
        print(f"[HSR VO Hashes] Saved patched hashes for {updated} file(s)")
