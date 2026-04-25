# Hash-based VO backup for HSR: uses External0_<md5>.hash sidecars to detect
# original PCKs, backs them up locally, restores modded files from that cache.

import hashlib
import shutil
from datetime import datetime, timezone
from pathlib import Path

from src.audio.vo_download import _load_cache_meta, _save_cache_meta

from src.core.logger import get_logger
logger = get_logger(__name__)

_CHUNK_SIZE = 1 << 20  # 1 MB


def _parse_hash_filename(name: str) -> tuple[str, str] | None:
    # External0_826a01d1af49b7fac662ed39219be7da.hash -> ("External0.pck", "826a...").
    if not name.endswith(".hash"):
        return None
    stem = name[:-5]
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
    result = {}
    for hash_file in lang_dir.glob("*.hash"):
        parsed = _parse_hash_filename(hash_file.name)
        if parsed:
            result[parsed[0]] = parsed[1]
    return result


def restore_language_from_hashes(
    game_cache_root: Path,
    persistent_path: Path,
    folder_name: str,
    progress_cb=None,
) -> bool:
    # Compare each PCK's MD5 to its .hash sidecar: match -> back up; mismatch -> restore.
    lang_dir = persistent_path / folder_name
    if not lang_dir.is_dir():
        return False

    hash_map = _scan_hash_files(lang_dir)
    if not hash_map:
        logger.info(f"[VO Local Backup] No .hash files found in {folder_name}")
        return False

    cache_lang_dir = game_cache_root / folder_name
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
            if not cached_pck.is_file() or _compute_file_md5(cached_pck) != expected_md5:
                shutil.copy2(pck_path, cached_pck)
                backed_up += 1
        else:
            if cached_pck.is_file():
                shutil.copy2(cached_pck, pck_path)
                restored += 1
            else:
                missing += 1

    meta = _load_cache_meta(game_cache_root)
    langs = meta.setdefault("languages", {})
    langs[folder_name] = {
        "method": "hash_backup",
        "cached_at": datetime.now(timezone.utc).isoformat(),
        "file_count": len(list(cache_lang_dir.glob("*.pck"))),
    }
    _save_cache_meta(game_cache_root, meta)

    if backed_up or restored:
        logger.info(f"[VO Local Backup] {folder_name}: "
            f"backed up {backed_up}, restored {restored}")
    if missing:
        msg = (
            f"[VO Local Backup] {folder_name}: {missing} modded file(s) "
            f"could not be restored (no backup available)"
        )
        logger.info(msg)
        if progress_cb:
            progress_cb(msg)

    return missing == 0 or restored > 0
