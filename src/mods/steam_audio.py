"""Prepare downloaded ZZZ voice packs as verified StreamingAssets originals.

The Steam distribution downloads voice packs into Persistent.  XXAR must not
rebuild those files until there is a pristine base copy and the game's base
audio manifest names that copy.  The remote/local Persistent manifests remain
owned by the game; this module never edits them or their revision/cache files.
"""

import copy
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import tempfile

import xxhash

from src.core.config_manager import get_game_state_dir
from src.core.game_registry import get_game


class SteamAudioError(RuntimeError):
    """No safe pristine source is available, or preparation failed."""


def _manifest(path):
    try:
        raw = path.read_bytes()
        obj = json.loads(raw)
        entries = obj["files"]
        if not isinstance(entries, list):
            raise ValueError("files is not an array")
        by_name = {}
        for entry in entries:
            name = entry["remoteName"]
            rel = PurePosixPath(name)
            if (not isinstance(name, str) or not name or rel.is_absolute()
                    or ".." in rel.parts or "\\" in name or str(rel) != name):
                raise ValueError("unsafe resource path")
            if name in by_name:
                raise ValueError("duplicate resource path")
            by_name[name] = entry
        return raw, obj, by_name
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise SteamAudioError(f"Cannot read ZZZ audio manifest {path}: {exc}") from exc


def _expected(entry):
    try:
        size = entry["fileSize"]
        tag = str(entry["md5"])
        if isinstance(size, bool) or int(size) != size or int(size) < 0:
            raise ValueError("invalid file size")
        if not tag.isdecimal() or not 0 <= int(tag) <= 0xffffffffffffffff:
            raise ValueError("invalid xxHash64")
        return int(size), int(tag)
    except (KeyError, TypeError, ValueError) as exc:
        raise SteamAudioError("Invalid size/xxHash64 for " + entry.get("remoteName", "audio file")) from exc


def _matches(path, entry):
    size, tag = _expected(entry)
    try:
        if not path.is_file() or path.stat().st_size != size:
            return False
        digest = xxhash.xxh64()
        with path.open("rb") as audio:
            for block in iter(lambda: audio.read(4 << 20), b""):
                digest.update(block)
        return digest.intdigest() == tag
    except OSError:
        return False


def _atomic_copy(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".xxar-", dir=target.parent)
    os.close(fd)
    temporary = Path(name)
    try:
        shutil.copy2(source, temporary)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def _atomic_bytes(data, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".xxar-", dir=target.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def _roots(streaming_root, persistent_root):
    # Accept audio roots only; constructing game paths from arbitrary callers
    # would otherwise allow a malformed selection to overwrite another file.
    streaming = Path(streaming_root).resolve()
    persistent = Path(persistent_root).resolve()
    suffix = ("Audio", "Windows")
    if (streaming.parts[-2:] != suffix or persistent.parts[-2:] != suffix
            or streaming.parent.parent.name != "StreamingAssets"
            or persistent.parent.parent.name != "Persistent"
            or streaming.parent.parent.parent != persistent.parent.parent.parent):
        return None
    return streaming, persistent, streaming.parent.parent, persistent.parent.parent


def prepare_steam_audio(game_id, streaming_root, persistent_root, progress_cb=None):
    """Register verified downloaded voice originals, then allow normal apply.

    All sources are validated and staged before any game file changes.  A failed
    commit restores the exact prior manifest and every changed Streaming PCK.
    Transaction backups remain in the application state directory for recovery.
    Persistent PCKs are never removed or changed here.
    """
    stats = {"prepared": False, "promoted": 0, "updated": 0, "registered": 0, "verified_rels": []}
    if game_id != "zzz":
        return stats
    roots = _roots(streaming_root, persistent_root)
    if roots is None:
        return stats
    streaming, persistent, streaming_top, persistent_top = roots
    game = get_game(game_id)
    languages = {folder for folder, _ in game.language_folders}
    voice_files = {
        p.relative_to(persistent).as_posix(): p
        for language in languages
        for p in (persistent / "Full" / language).glob("*.pck")
        if not game.is_protected_pck(p.name)
    }
    installation = hashlib.sha256(str(streaming).encode()).hexdigest()[:20]
    state_dir = get_game_state_dir(game_id) / "steam_audio" / installation
    state_path = state_dir / "registration.json"
    registration = {}
    if state_path.is_file():
        try:
            registration = json.loads(state_path.read_text(encoding="utf-8"))
            if not isinstance(registration, dict) or not isinstance(registration.get("entries"), dict):
                raise ValueError("expected a registration object")
            if registration.get("streaming_root") != str(streaming):
                raise ValueError("installation mismatch")
        except (ValueError, OSError, TypeError) as exc:
            raise SteamAudioError(f"Invalid Steam audio registration: {exc}") from exc
    if not voice_files and not registration:
        return stats

    # A process/power interruption during replacement needs explicit recovery;
    # never silently accept a half-committed baseline as a new pristine state.
    for journal_path in state_dir.glob("transaction-*/transaction.json"):
        try:
            old_journal = json.loads(journal_path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            raise SteamAudioError(f"Unreadable Steam audio transaction: {journal_path}")
        if old_journal.get("status") in {"committing", "rollback_failed"}:
            raise SteamAudioError(f"Incomplete Steam audio preparation; recover backups in {journal_path.parent}")

    base_path = streaming_top / "audio_version"
    # Older/custom installations do not expose the game catalogue. They keep
    # the existing launcher-manifest path; absence alone is not Steam detection.
    if not base_path.is_file() and not registration:
        return stats
    original_bytes, base, base_entries = _manifest(base_path)
    # A launcher-installed language already has base registration.  Only adopt
    # this layout when at least one downloaded voice is absent from that base,
    # or when this installation was prepared previously and needs refreshing.
    prefix = "Audio/Windows/"
    if not registration and all(prefix + rel in base_entries for rel in voice_files):
        return stats
    manifest_path = persistent_top / "audio_version_persist"
    if not manifest_path.is_file():
        manifest_path = persistent_top / "audio_version_remote"
    _, _, installed_entries = _manifest(manifest_path)
    names = set(voice_files)
    for name in registration.get("entries", {}):
        rel = PurePosixPath(name)
        if (rel.is_absolute() or ".." in rel.parts or "\\" in name
                or len(rel.parts) != 3 or rel.parts[0] != "Full"
                or rel.parts[1] not in languages or rel.suffix != ".pck"
                or game.is_protected_pck(rel.name)):
            raise SteamAudioError("Invalid path in Steam audio registration")
        names.add(name)

    planned = []
    registered = {}
    for rel in sorted(names):
        remote_name = prefix + rel
        entry = installed_entries.get(remote_name)
        if entry is None:
            raise SteamAudioError(f"No game manifest entry for downloaded voice pack {rel}")
        _expected(entry)
        destination = streaming / rel
        original = persistent / rel
        if not destination.parent.resolve().is_relative_to(streaming):
            raise SteamAudioError(f"Steam voice destination escapes the audio directory: {rel}")
        # A previously built Persistent overlay must never become a baseline.
        if _matches(destination, entry):
            source = destination
        elif _matches(original, entry):
            source = original
        else:
            raise SteamAudioError(
                f"No verified original for {rel}. Restore/download the original voice pack before applying mods."
            )
        registered[rel] = copy.deepcopy(entry)
        changed = source != destination
        if changed:
            planned.append((rel, source, destination, entry))
        if base_entries.get(remote_name) != entry:
            stats["registered"] += 1

    # Preserve every unrelated entry and unknown top-level/entry field.
    replacement = {entry["remoteName"]: entry for entry in registered.values()}
    base["files"] = [copy.deepcopy(replacement.pop(entry["remoteName"], entry)) for entry in base["files"]]
    base["files"].extend(copy.deepcopy(list(replacement.values())))
    manifest_bytes = json.dumps(base, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    manifest_changed = stats["registered"] > 0
    stats["prepared"] = True
    stats["verified_rels"] = sorted(registered)
    if not planned and not manifest_changed and registration.get("entries") == registered:
        return stats

    state_dir.mkdir(parents=True, exist_ok=True)
    transaction = Path(tempfile.mkdtemp(prefix="transaction-", dir=state_dir))
    (transaction / "audio_version.before").write_bytes(original_bytes)
    journal = {"streaming_root": str(streaming), "status": "staging", "files": []}
    # Stage and revalidate every source before the first write to the game.
    for rel, source, destination, entry in planned:
        staged = transaction / "prepared" / rel
        staged.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, staged)
        if not _matches(staged, entry):
            raise SteamAudioError(f"Voice original changed while preparing {rel}")
        existed = destination.exists()
        if existed:
            before = transaction / "before" / rel
            before.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(destination, before)
        journal["files"].append({"relative_path": rel, "existed": existed})
    journal["status"] = "committing"
    (transaction / "transaction.json").write_text(json.dumps(journal, indent=2), encoding="utf-8")
    committed = []
    try:
        for rel, _, destination, entry in planned:
            existed = destination.exists()
            committed.append((rel, destination, existed))
            _atomic_copy(transaction / "prepared" / rel, destination)
            if not _matches(destination, entry):
                raise SteamAudioError(f"Could not verify prepared voice pack {rel}")
            stats["updated" if existed else "promoted"] += 1
            if progress_cb:
                progress_cb(f"Secured Steam voice original: {rel}")
        if manifest_changed:
            _atomic_bytes(manifest_bytes, base_path)
        _atomic_bytes(json.dumps({"streaming_root": str(streaming), "entries": registered}, indent=2).encode(), state_path)
    except BaseException as exc:
        rollback_errors = []
        for rel, destination, existed in reversed(committed):
            try:
                if existed:
                    _atomic_copy(transaction / "before" / rel, destination)
                else:
                    destination.unlink(missing_ok=True)
            except OSError as rollback_exc:
                rollback_errors.append(str(rollback_exc))
        try:
            _atomic_bytes(original_bytes, base_path)
        except OSError as rollback_exc:
            rollback_errors.append(str(rollback_exc))
        journal["status"] = "rollback_failed" if rollback_errors else "rolled_back"
        journal["errors"] = rollback_errors
        (transaction / "transaction.json").write_text(json.dumps(journal, indent=2), encoding="utf-8")
        raise SteamAudioError(f"Steam audio preparation failed; backups are in {transaction}: {exc}") from exc
    journal["status"] = "complete"
    (transaction / "transaction.json").write_text(json.dumps(journal, indent=2), encoding="utf-8")
    return stats
