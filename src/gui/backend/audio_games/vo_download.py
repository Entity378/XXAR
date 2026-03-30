# Download original HSR voice-over audio from the official HoYoverse API.

# Queries the ``getGamePackages`` endpoint to obtain per-language 7z archive
# URLs, downloads them, extracts the PCK files, and caches the result so that
# subsequent restores are instant

import hashlib
import json
import shutil
import tempfile
import urllib.request
import urllib.error
import ssl
import py7zr
from datetime import datetime, timezone
from pathlib import Path

# Constants
API_URL = (
    "https://sg-hyp-api.hoyoverse.com/hyp/hyp-connect/api/getGamePackages"
)
HSR_GAME_ID = "4ziysqXOQ8"
HSR_LAUNCHER_ID = "VYTpXlbWo8"

CACHE_DIR_NAME = "original_vo"
CACHE_META_FILE = "cache_meta.json"

# API language code to game folder name
LANGUAGE_MAP: dict[str, str] = {
    "zh-cn": "Chinese(PRC)",
    "en-us": "English",
    "ja-jp": "Japanese",
    "ko-kr": "Korean",
}

# Reverse mapping: folder name to API code
_FOLDER_TO_API_LANG: dict[str, str] = {v: k for k, v in LANGUAGE_MAP.items()}

# Download chunk size (1 MB)
_CHUNK_SIZE = 1 << 20


# HTTP helper  (mirrors update_manager_bridge._urlopen)
def _urlopen(req, timeout=30):
    try:
        return urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.URLError as e:
        if "CERTIFICATE_VERIFY_FAILED" in str(e):
            ctx = ssl._create_unverified_context()
            return urllib.request.urlopen(req, timeout=timeout, context=ctx)
        raise


# API query
def fetch_audio_packages() -> dict | None:
    # Query the HoYoverse API and return the parsed JSON response
    # Returns "None" on any network / parsing error (logged to stdout)
    url = (
        f"{API_URL}"
        f"?game_ids[]={HSR_GAME_ID}"
        f"&launcher_id={HSR_LAUNCHER_ID}"
    )
    try:
        req = urllib.request.Request(url)
        with _urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if data.get("retcode") != 0:
            print(f"[VO Download] API error: {data.get('message')}")
            return None
        return data
    except Exception as e:
        print(f"[VO Download] Failed to fetch audio packages: {e}")
        return None


def get_audio_pkg_for_language(
    api_response: dict, folder_name: str
) -> dict | None:
    # Return the "audio_pkgs" entry matching "folder_name", or "None"
    api_lang = _FOLDER_TO_API_LANG.get(folder_name)
    if not api_lang:
        return None
    try:
        pkgs = (
            api_response["data"]["game_packages"][0]["main"]["major"][
                "audio_pkgs"
            ]
        )
        for pkg in pkgs:
            if pkg.get("language") == api_lang:
                return pkg
    except (KeyError, IndexError, TypeError):
        pass
    return None


def get_api_version(api_response: dict) -> str | None:
    # Extract the game version string from the API response
    try:
        return api_response["data"]["game_packages"][0]["main"]["major"][
            "version"
        ]
    except (KeyError, IndexError, TypeError):
        return None


# Cache metadata
def _cache_dir(app_game_dir: Path) -> Path:
    return app_game_dir / CACHE_DIR_NAME


def _load_cache_meta(app_game_dir: Path) -> dict:
    meta_file = _cache_dir(app_game_dir) / CACHE_META_FILE
    if not meta_file.is_file():
        return {}
    try:
        return json.loads(meta_file.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_cache_meta(app_game_dir: Path, meta: dict):
    cache = _cache_dir(app_game_dir)
    cache.mkdir(parents=True, exist_ok=True)
    (cache / CACHE_META_FILE).write_text(
        json.dumps(meta, indent=2), encoding="utf-8"
    )


def is_language_cached(
    app_game_dir: Path, version: str, folder_name: str
) -> bool:
    # Return "True" if we already have cached originals for this version
    meta = _load_cache_meta(app_game_dir)
    if meta.get("version") != version:
        return False
    lang_entry = meta.get("languages", {}).get(folder_name)
    if not lang_entry:
        return False
    lang_dir = _cache_dir(app_game_dir) / folder_name
    return lang_dir.is_dir() and any(lang_dir.glob("*.pck"))


# Download + extraction
def _format_size(size_bytes: int) -> str:
    if size_bytes >= 1 << 30:
        return f"{size_bytes / (1 << 30):.1f} GB"
    if size_bytes >= 1 << 20:
        return f"{size_bytes / (1 << 20):.1f} MB"
    return f"{size_bytes / (1 << 10):.1f} KB"


def download_and_extract(
    url: str,
    expected_md5: str,
    dest_dir: Path,
    folder_name: str,
    progress_cb=None,
) -> bool:
    # Download a 7z archive and extract PCK files into "dest_dir"
    dest_dir.mkdir(parents=True, exist_ok=True)

    # Download to a temp file
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".7z")
    tmp_path = Path(tmp_path)
    try:
        req = urllib.request.Request(url)
        with _urlopen(req, timeout=60) as resp:
            total = int(resp.headers.get("Content-Length", 0))
            downloaded = 0
            md5 = hashlib.md5()

            with open(tmp_fd, "wb") as f:
                while True:
                    chunk = resp.read(_CHUNK_SIZE)
                    if not chunk:
                        break
                    f.write(chunk)
                    md5.update(chunk)
                    downloaded += len(chunk)

                    if progress_cb and total > 0:
                        pct = int(downloaded * 100 / total)
                        progress_cb(
                            f"Downloading {folder_name} VO "
                            f"({_format_size(downloaded)} / "
                            f"{_format_size(total)} — {pct}%)"
                        )

        # Verify MD5
        if progress_cb:
            progress_cb(f"Verifying {folder_name} download integrity...")

        actual_md5 = md5.hexdigest()
        if expected_md5 and actual_md5.lower() != expected_md5.lower():
            print(
                f"[VO Download] MD5 mismatch for {folder_name}: "
                f"expected {expected_md5}, got {actual_md5}"
            )
            return False

        # Extract PCK files from 7z
        if progress_cb:
            progress_cb(f"Extracting {folder_name} original audio files...")

        _extract_pcks_from_7z(tmp_path, dest_dir)
        return True

    except Exception as e:
        print(f"[VO Download] Error downloading {folder_name}: {e}")
        return False
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass


def _extract_pcks_from_7z(archive_path: Path, dest_dir: Path):
    # Open a 7z archive and extract all ".pck" files into "dest_dir", 
    # flattening any internal directory structure
    with py7zr.SevenZipFile(str(archive_path), mode="r") as z:
        all_names = z.getnames()
        pck_names = [n for n in all_names if n.lower().endswith(".pck")]

        if not pck_names:
            print("[VO Download] Warning: no .pck files found in archive")
            return

        # Extract to a temp directory first, then flatten into "dest_dir"
        with tempfile.TemporaryDirectory() as tmp_extract:
            z.extract(path=tmp_extract, targets=pck_names)

            tmp_extract_path = Path(tmp_extract)
            for pck in tmp_extract_path.rglob("*.pck"):
                shutil.move(str(pck), str(dest_dir / pck.name))

        print(
            f"[VO Download] Extracted {len(pck_names)} PCK file(s) "
            f"into {dest_dir}"
        )


# High-level restore
def restore_language_from_api(
    app_game_dir: Path,
    persistent_path: Path,
    folder_name: str,
    version: str,
    progress_cb=None,
) -> bool:
    # Ensure *persistent_path/folder_name* contains original PCK files
    # Uses the local cache when available; otherwise downloads from the API
    cache_root = _cache_dir(app_game_dir)
    cache_lang_dir = cache_root / folder_name

    # 1. Check cache
    if is_language_cached(app_game_dir, version, folder_name):
        if progress_cb:
            progress_cb(f"Restoring {folder_name} VO from cache...")
        _copy_to_persistent(cache_lang_dir, persistent_path / folder_name)
        print(f"[VO Download] Restored {folder_name} from cache")
        return True

    # 2. Fetch API
    if progress_cb:
        progress_cb("Fetching HSR audio package info...")

    api_data = fetch_audio_packages()
    if api_data is None:
        print(f"[VO Download] Cannot restore {folder_name}: API unavailable")
        return False

    pkg = get_audio_pkg_for_language(api_data, folder_name)
    if pkg is None:
        print(
            f"[VO Download] No download found for language '{folder_name}'"
        )
        return False

    # 3. Check disk space
    decompressed = int(pkg.get("decompressed_size", 0))
    archive_size = int(pkg.get("size", 0))
    needed = archive_size + decompressed
    if needed > 0:
        free = shutil.disk_usage(str(app_game_dir)).free
        if free < needed:
            msg = (
                f"Not enough disk space to download {folder_name} VO. "
                f"Need {_format_size(needed)}, "
                f"have {_format_size(free)}"
            )
            print(f"[VO Download] {msg}")
            if progress_cb:
                progress_cb(msg)
            return False

    # 4. Download + extract into cache
    cache_lang_dir.mkdir(parents=True, exist_ok=True)

    ok = download_and_extract(
        url=pkg["url"],
        expected_md5=pkg.get("md5", ""),
        dest_dir=cache_lang_dir,
        folder_name=folder_name,
        progress_cb=progress_cb,
    )

    if not ok:
        # Clean up partial cache
        shutil.rmtree(cache_lang_dir, ignore_errors=True)
        return False

    # 5. Update cache metadata
    meta = _load_cache_meta(app_game_dir)
    meta["version"] = version
    langs = meta.setdefault("languages", {})
    langs[folder_name] = {
        "md5": pkg.get("md5", ""),
        "cached_at": datetime.now(timezone.utc).isoformat(),
    }
    _save_cache_meta(app_game_dir, meta)

    # 6. Copy to persistent
    if progress_cb:
        progress_cb(f"Restoring {folder_name} VO originals...")
    _copy_to_persistent(cache_lang_dir, persistent_path / folder_name)
    print(f"[VO Download] Restored {folder_name} from download")
    return True


def _copy_to_persistent(src_dir: Path, dest_dir: Path):
    # Replace "dest_dir" with a copy of "src_dir"
    if dest_dir.exists():
        shutil.rmtree(dest_dir)
    shutil.copytree(src_dir, dest_dir)


def cleanup_stale_cache(app_game_dir: Path, current_version: str):
    # Remove cached languages whose version differs from "current_version"
    meta = _load_cache_meta(app_game_dir)
    if not meta:
        return
    if meta.get("version") == current_version:
        return

    cache_root = _cache_dir(app_game_dir)
    old_langs = list(meta.get("languages", {}).keys())
    for lang in old_langs:
        lang_dir = cache_root / lang
        if lang_dir.is_dir():
            shutil.rmtree(lang_dir, ignore_errors=True)
            print(f"[VO Download] Cleaned stale cache: {lang}")

    # Reset metadata for new version
    _save_cache_meta(app_game_dir, {"version": current_version, "languages": {}})
