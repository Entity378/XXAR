# Hash-based local VO backup for HSR.
#
# Uses the game's own .hash files (e.g. External0_<md5>.hash) to identify
# which PCK files in Persistent are original (unmodded).  Originals are
# backed up to a local cache; modded files are restored from that cache
# before new mods are applied.

import hashlib
import shutil
from datetime import datetime, timezone
from pathlib import Path

from src.audio.vo_download import _cache_dir, _load_cache_meta, _save_cache_meta

_CHUNK_SIZE = 1 << 20  # 1 MB


# .hash file parsing

def _parse_hash_filename(name: str) -> tuple[str, str] | None:
    # Parse ``External0_826a01d1af49b7fac662ed39219be7da.hash``.
    # Returns ``("External0.pck", "826a...")`` or ``None`` if the pattern
    # does not match.
    if not name.endswith(".hash"):
        return None
    stem = name[:-5]  # strip ".hash"
    parts = stem.rsplit("_", 1)
    if len(parts) != 2:
        return None
    pck_stem, md5_part = parts
    md5_part = md5_part.lower()
    if len(md5_part) != 32:
        return None
    try:
        int(md5_part, 16)
    except ValueError:
        return None
    return (f"{pck_stem}.pck", md5_part)


def _compute_file_md5(filepath: Path) -> str:
    h = hashlib.md5()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(_CHUNK_SIZE), b""):
            h.update(chunk)
    return h.hexdigest()


def _scan_hash_files(lang_dir: Path) -> dict[str, str]:
    # Return ``{pck_filename: expected_md5}`` for all ``.hash`` files.
    result = {}
    for hash_file in lang_dir.glob("*.hash"):
        parsed = _parse_hash_filename(hash_file.name)
        if parsed:
            result[parsed[0]] = parsed[1]
    return result


# High-level restore

def restore_language_from_hashes(
    app_game_dir: Path,
    persistent_path: Path,
    folder_name: str,
    progress_cb=None,
) -> bool:
    # Ensure ``persistent_path/folder_name`` contains original PCK files.
    # Compares each PCK's actual MD5 against the expected value from its
    # companion ``.hash`` file:
    # * **Match** -- file is original -> copy to backup cache.
    # * **Mismatch** -- file was modded -> overwrite with cached backup.
    # Returns ``True`` if at least one file was processed successfully.
    lang_dir = persistent_path / folder_name
    if not lang_dir.is_dir():
        return False

    hash_map = _scan_hash_files(lang_dir)
    if not hash_map:
        print(f"[VO Local Backup] No .hash files found in {folder_name}")
        return False

    cache_lang_dir = _cache_dir(app_game_dir) / folder_name
    cache_lang_dir.mkdir(parents=True, exist_ok=True)

    backed_up = 0
    restored = 0
    missing = 0
    total = len(hash_map)

    for i, (pck_name, expected_md5) in enumerate(sorted(hash_map.items()), 1):
        if progress_cb:
            progress_cb(
                f"Checking {folder_name} VO ({i}/{total}): {pck_name}"
            )

        pck_path = lang_dir / pck_name
        cached_pck = cache_lang_dir / pck_name

        if not pck_path.is_file():
            continue

        actual_md5 = _compute_file_md5(pck_path)

        if actual_md5 == expected_md5:
            # File is original -- back it up if not already cached.
            if not cached_pck.is_file() or _compute_file_md5(cached_pck) != expected_md5:
                shutil.copy2(pck_path, cached_pck)
                backed_up += 1
        else:
            # File is modded -- restore from cache.
            if cached_pck.is_file():
                shutil.copy2(cached_pck, pck_path)
                restored += 1
            else:
                missing += 1

    # Update shared cache metadata.
    meta = _load_cache_meta(app_game_dir)
    langs = meta.setdefault("languages", {})
    langs[folder_name] = {
        "method": "hash_backup",
        "cached_at": datetime.now(timezone.utc).isoformat(),
        "file_count": len(list(cache_lang_dir.glob("*.pck"))),
    }
    _save_cache_meta(app_game_dir, meta)

    if backed_up or restored:
        print(
            f"[VO Local Backup] {folder_name}: "
            f"backed up {backed_up}, restored {restored}"
        )
    if missing:
        msg = (
            f"[VO Local Backup] {folder_name}: {missing} modded file(s) "
            f"could not be restored (no backup available)"
        )
        print(msg)
        if progress_cb:
            progress_cb(msg)

    return missing == 0 or restored > 0
