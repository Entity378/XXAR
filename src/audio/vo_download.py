# Download original HSR voice-over audio from the official HoYoverse API.

# Queries the ``getGamePackages`` endpoint to obtain per-language 7z archive
# URLs, downloads them, extracts the PCK files, and caches the result so that
# subsequent restores are instant

import hashlib
import json
import shutil
import subprocess
import tempfile
import urllib.request
import urllib.error
import ssl
import py7zr
from datetime import datetime, timezone
from pathlib import Path

from src.core.subprocess_utils import BASE_DIR, IS_WINDOWS, SUBPROCESS_KWARGS

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


def get_hdiff_audio_pkg(
    api_response: dict, from_version: str, folder_name: str
) -> dict | None:
    # Find an hdiff audio patch for transitioning from "from_version" to
    # the current API version, for the given language folder
    api_lang = _FOLDER_TO_API_LANG.get(folder_name)
    if not api_lang:
        return None
    try:
        patches = (
            api_response["data"]["game_packages"][0]["main"]["major"][
                "patches"
            ]
        )
    except (KeyError, IndexError, TypeError):
        return None
    for patch in patches:
        if patch.get("version") != from_version:
            continue
        for audio_pkg in patch.get("audio_pkgs", []):
            if audio_pkg.get("language") == api_lang:
                return audio_pkg
    return None


# HDiff patching utilities

def _find_hpatchz() -> str | None:
    # Locate the hpatchz binary: bundled tool dir first, then PATH
    exe_name = "hpatchz.exe" if IS_WINDOWS else "hpatchz"
    local_path = BASE_DIR / "tools" / "audio" / "hpatchz" / exe_name
    if local_path.is_file():
        return str(local_path.resolve())
    return shutil.which("hpatchz")


def _download_hdiff_archive(
    url: str,
    expected_md5: str,
    folder_name: str,
    progress_cb=None,
) -> Path | None:
    # Download an hdiff 7z archive to a temp file.
    # Returns the Path on success; caller is responsible for cleanup.
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
                            f"Downloading {folder_name} VO patch "
                            f"({_format_size(downloaded)} / "
                            f"{_format_size(total)} — {pct}%)"
                        )

        if progress_cb:
            progress_cb(f"Verifying {folder_name} patch integrity...")

        actual_md5 = md5.hexdigest()
        if expected_md5 and actual_md5.lower() != expected_md5.lower():
            print(
                f"[VO Download] HDiff MD5 mismatch for {folder_name}: "
                f"expected {expected_md5}, got {actual_md5}"
            )
            tmp_path.unlink(missing_ok=True)
            return None
        return tmp_path

    except Exception as e:
        print(f"[VO Download] Error downloading hdiff for {folder_name}: {e}")
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass
        return None


def _extract_hdiff_archive(archive_path: Path, dest_dir: Path) -> bool:
    # Extract all files from an hdiff 7z (.hdiff files + deletefiles.txt)
    # into dest_dir, flattening directory structure
    dest_dir.mkdir(parents=True, exist_ok=True)
    try:
        with py7zr.SevenZipFile(str(archive_path), mode="r") as z:
            with tempfile.TemporaryDirectory() as tmp_extract:
                z.extractall(path=tmp_extract)
                tmp_path = Path(tmp_extract)
                for f in tmp_path.rglob("*"):
                    if f.is_file():
                        shutil.move(str(f), str(dest_dir / f.name))
        return True
    except Exception as e:
        print(f"[VO Download] Failed to extract hdiff archive: {e}")
        return False


def _apply_hdiff_patches(
    working_dir: Path,
    hdiff_dir: Path,
    folder_name: str,
    progress_cb=None,
) -> bool:
    # Apply hdiff patches to PCK files in working_dir.
    # working_dir contains copies of the old cached PCKs.
    # hdiff_dir contains .hdiff files and optionally deletefiles.txt.
    # Returns True if all patches applied successfully.
    hpatchz = _find_hpatchz()
    if not hpatchz:
        print("[VO Download] hpatchz binary not found, cannot apply hdiff")
        return False

    # 1. Handle deletefiles.txt
    delete_list = hdiff_dir / "deletefiles.txt"
    if delete_list.is_file():
        for line in delete_list.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            # Flatten: take only the filename from possible path
            target = working_dir / Path(line).name
            if target.is_file():
                target.unlink()
                print(f"[VO Download] Deleted obsolete file: {target.name}")

    # 2. Apply .hdiff patches
    hdiff_files = sorted(hdiff_dir.glob("*.hdiff"))
    if not hdiff_files:
        print("[VO Download] No .hdiff files found in patch archive")
        return False

    total = len(hdiff_files)
    for i, hdiff_file in enumerate(hdiff_files, 1):
        # e.g. "SomeFile.pck.hdiff" patches "SomeFile.pck"
        target_name = hdiff_file.stem  # removes .hdiff
        old_file = working_dir / target_name
        new_file = working_dir / (target_name + ".patched")

        if progress_cb:
            progress_cb(
                f"Applying {folder_name} VO patch ({i}/{total})..."
            )

        cmd = [hpatchz]
        if old_file.is_file():
            cmd.append(str(old_file))
        else:
            # New file that didn't exist in the old version
            cmd.append("")
        cmd.extend([str(hdiff_file), str(new_file)])

        try:
            subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                **SUBPROCESS_KWARGS,
            )
        except subprocess.CalledProcessError as e:
            stderr = (
                e.stderr.decode("utf-8", errors="replace")
                if e.stderr
                else ""
            )
            print(
                f"[VO Download] hpatchz failed for {target_name}: "
                f"exit {e.returncode} — {stderr}"
            )
            new_file.unlink(missing_ok=True)
            return False
        except FileNotFoundError:
            print(f"[VO Download] hpatchz binary not executable: {hpatchz}")
            return False

        # Replace old file with patched file
        if old_file.is_file():
            old_file.unlink()
        new_file.rename(working_dir / target_name)

    return True


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
    cached_version: str | None = None,
    progress_cb=None,
) -> bool:
    # Ensure *persistent_path/folder_name* contains original PCK files.
    # Uses the local cache when available; attempts hdiff patching when
    # cached_version is provided; otherwise downloads from the API.
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

    # 2.5. Try hdiff patching if we have a stale cache
    if (
        cached_version is not None
        and cache_lang_dir.is_dir()
        and any(cache_lang_dir.glob("*.pck"))
        and _find_hpatchz() is not None
    ):
        hdiff_pkg = get_hdiff_audio_pkg(
            api_data, cached_version, folder_name
        )
        if hdiff_pkg is not None:
            patched = _try_hdiff_patch(
                app_game_dir=app_game_dir,
                cache_lang_dir=cache_lang_dir,
                hdiff_pkg=hdiff_pkg,
                folder_name=folder_name,
                version=version,
                progress_cb=progress_cb,
            )
            if patched:
                if progress_cb:
                    progress_cb(
                        f"Restoring {folder_name} VO originals..."
                    )
                _copy_to_persistent(
                    cache_lang_dir, persistent_path / folder_name
                )
                print(
                    f"[VO Download] Restored {folder_name} from "
                    f"hdiff patch ({cached_version} → {version})"
                )
                return True
            # hdiff failed — clean up stale cache before full download
            print(
                f"[VO Download] HDiff patch failed for {folder_name}, "
                f"falling back to full download"
            )

    # Clean up stale cache before full download
    _purge_language_cache(app_game_dir, folder_name)

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


def _try_hdiff_patch(
    app_game_dir: Path,
    cache_lang_dir: Path,
    hdiff_pkg: dict,
    folder_name: str,
    version: str,
    progress_cb=None,
) -> bool:
    # Attempt to apply an hdiff patch to update cached PCK files in-place.
    # Works on a copy of the cache so that failure is safe.
    # Returns True on success (cache_lang_dir is updated + meta written).
    archive_size = int(hdiff_pkg.get("size", 0))
    decompressed = int(hdiff_pkg.get("decompressed_size", 0))
    needed = archive_size + decompressed
    if needed > 0:
        free = shutil.disk_usage(str(app_game_dir)).free
        if free < needed:
            print(
                f"[VO Download] Not enough space for hdiff "
                f"({_format_size(needed)} needed, "
                f"{_format_size(free)} free)"
            )
            return False

    # Download the hdiff archive
    archive_path = _download_hdiff_archive(
        url=hdiff_pkg["url"],
        expected_md5=hdiff_pkg.get("md5", ""),
        folder_name=folder_name,
        progress_cb=progress_cb,
    )
    if archive_path is None:
        return False

    try:
        # Extract hdiff files to a temp dir
        with tempfile.TemporaryDirectory() as hdiff_tmp:
            hdiff_dir = Path(hdiff_tmp)
            if not _extract_hdiff_archive(archive_path, hdiff_dir):
                return False

            # Copy current cache to a working directory
            with tempfile.TemporaryDirectory() as work_tmp:
                working_dir = Path(work_tmp) / folder_name
                shutil.copytree(cache_lang_dir, working_dir)

                if progress_cb:
                    progress_cb(
                        f"Applying {folder_name} VO patches..."
                    )

                ok = _apply_hdiff_patches(
                    working_dir, hdiff_dir, folder_name, progress_cb
                )
                if not ok:
                    return False

                # Success — replace cache with patched copy
                shutil.rmtree(cache_lang_dir)
                shutil.copytree(working_dir, cache_lang_dir)

        # Update cache metadata
        meta = _load_cache_meta(app_game_dir)
        meta["version"] = version
        langs = meta.setdefault("languages", {})
        langs[folder_name] = {
            "md5": "",
            "cached_at": datetime.now(timezone.utc).isoformat(),
            "patched_from": hdiff_pkg.get("version", ""),
        }
        _save_cache_meta(app_game_dir, meta)
        return True

    finally:
        try:
            archive_path.unlink(missing_ok=True)
        except Exception:
            pass


def _copy_to_persistent(src_dir: Path, dest_dir: Path):
    # Replace "dest_dir" with a copy of "src_dir"
    if dest_dir.exists():
        shutil.rmtree(dest_dir)
    shutil.copytree(src_dir, dest_dir)


def cleanup_stale_cache(
    app_game_dir: Path, current_version: str
) -> str | None:
    # Check if the cache version differs from "current_version".
    # Returns the old cached version string if stale (for hdiff patching),
    # or None if the cache is already current or empty.
    # Does NOT delete old cache — the caller decides whether to hdiff-patch
    # or fall back to full download.
    meta = _load_cache_meta(app_game_dir)
    if not meta:
        return None
    cached_version = meta.get("version")
    if cached_version == current_version:
        return None
    return cached_version


def _purge_language_cache(app_game_dir: Path, folder_name: str):
    # Delete the cached language directory and remove it from metadata
    cache_root = _cache_dir(app_game_dir)
    lang_dir = cache_root / folder_name
    if lang_dir.is_dir():
        shutil.rmtree(lang_dir, ignore_errors=True)
        print(f"[VO Download] Cleaned stale cache: {folder_name}")
