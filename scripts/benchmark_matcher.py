"""
Dev-only benchmark harness for the audio matcher.

Usage:
    python scripts/benchmark_matcher.py <manifest.json> <audio_dir> [--game-id zzz] [--reset-index]

Manifest format (JSON array):
    [
        {"name": "music_verse", "query": "path/to/query.wav", "target_wem": "path/to/target.wem"},
        {"name": "vo_short",    "query": "...",               "target_wem": "..."},
        ...
    ]

Paths in the manifest can be absolute or relative to the manifest's directory.

audio_dir is the game-audio folder containing .pck files (what the
AudioBrowser's "_current_directory" points at at runtime).

The script populates the constellation index lazily — first run on a game is
slow (every .pck is decoded), subsequent runs reuse the cached index.

Output:
    per-case rank of the target inside top-20
    median / mean rank, recall@20, mean time per query
"""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.audio import constellation
from src.audio.converter import AudioConverter
from src.audio.matcher import AudioMatcher
from src.data.constellation_index import ConstellationIndex
from src.data.fingerprint_database import FingerprintDatabase
from src.core.config_manager import (
    get_game_constellation_index_file,
    get_game_fingerprint_database_file,
)
from src.wwise.pck_indexer import PCKIndexer
from src.wwise.bnk_indexer import BNKIndexer


def _resolve(manifest_dir: Path, p: str) -> Path:
    path = Path(p)
    return path if path.is_absolute() else manifest_dir / path


def _collect_candidates(audio_dir: Path):
    pck_files = sorted(audio_dir.glob("**/*.pck"), key=lambda p: p.name.lower())
    for pck_path in pck_files:
        try:
            indexer = PCKIndexer(str(pck_path))
            indexer.build_index()
        except Exception as e:
            print(f"  skip {pck_path.name}: {e}")
            continue

        for wem_info in indexer.index_data["sounds"] + indexer.index_data["externals"]:
            try:
                wem_bytes = indexer.extract_single_file(
                    wem_info["id"], "wem", wem_info["lang_id"]
                )
                yield wem_bytes, {
                    "id": wem_info["id"],
                    "pck": pck_path.name,
                    "lang_id": wem_info["lang_id"],
                }
            except Exception:
                continue

        for bnk_info in indexer.index_data["banks"]:
            try:
                bnk_bytes = indexer.extract_single_file(
                    bnk_info["id"], "bnk", bnk_info["lang_id"]
                )
                bnk_indexer = BNKIndexer(bnk_bytes)
                bnk_indexer.parse_didx()
                for wem in bnk_indexer.wem_list:
                    try:
                        wem_bytes = bnk_indexer.extract_wem(wem["wem_id"])
                        yield wem_bytes, {
                            "id": wem["wem_id"],
                            "pck": pck_path.name,
                            "bnk_id": bnk_info["id"],
                            "lang_id": bnk_info["lang_id"],
                        }
                    except Exception:
                        continue
            except Exception:
                continue


def _populate_index(audio_dir: Path, idx: ConstellationIndex, ffmpeg_path: str, vgmstream_path: str):
    print(f"Populating constellation index from {audio_dir} (cold cache is slow)...")
    count = 0
    t0 = time.time()
    for wem_bytes, _meta in _collect_candidates(audio_dir):
        count += 1
        if idx.has_file(wem_bytes):
            continue
        audio = constellation.decode_wem_bytes(ffmpeg_path, wem_bytes, vgmstream_path)
        if audio is None or len(audio) == 0:
            continue
        idx.add_file(wem_bytes, constellation.extract_hashes(audio))
        if count % 500 == 0:
            elapsed = time.time() - t0
            print(f"  {count} wems processed ({elapsed:.1f}s, {count/elapsed:.1f}/s)")
    elapsed = time.time() - t0
    print(f"Indexed {count} wems in {elapsed:.1f}s ({idx.stats()})")


def run_one(
    case: dict,
    manifest_dir: Path,
    audio_dir: Path,
    matcher: AudioMatcher,
    idx: ConstellationIndex,
    ffmpeg_path: str,
    all_candidates_cache: list | None = None,
) -> tuple[int, float]:
    query_path = _resolve(manifest_dir, case["query"])
    target_path = _resolve(manifest_dir, case["target_wem"])

    target_bytes = target_path.read_bytes()
    target_hash = hashlib.sha256(target_bytes).hexdigest()

    t0 = time.time()

    recording_audio = constellation.decode_file(ffmpeg_path, query_path)
    if recording_audio is None:
        return -1, 0.0

    recording_hashes = constellation.extract_hashes(recording_audio)
    recording_fp = matcher._build_fingerprint(recording_audio, constellation.SAMPLE_RATE)
    if recording_fp is None:
        return -1, 0.0

    if all_candidates_cache is None:
        all_candidates = list(_collect_candidates(audio_dir))
    else:
        all_candidates = all_candidates_cache

    shortlist_hashes = set()
    if recording_hashes:
        shortlist = idx.query(recording_hashes, top_k=200)
        shortlist_hashes = {entry[0] for entry in shortlist}

    filtered = [
        (wb, info) for wb, info in all_candidates
        if hashlib.sha256(wb).hexdigest() in shortlist_hashes
    ] if shortlist_hashes else all_candidates

    results = matcher.find_matches(recording_fp, filtered, top_n=20)

    elapsed = time.time() - t0

    rank = -1
    for i, (_score, _info) in enumerate(results, start=1):
        wb_idx = next(
            (wb for wb, info in filtered if info["id"] == _info["id"]),
            None,
        )
        if wb_idx is None:
            continue
        if hashlib.sha256(wb_idx).hexdigest() == target_hash:
            rank = i
            break

    return rank, elapsed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("manifest", help="Path to benchmark manifest JSON")
    ap.add_argument("audio_dir", help="Path to game audio directory containing .pck files")
    ap.add_argument("--game-id", default="zzz")
    ap.add_argument("--reset-index", action="store_true", help="Delete the constellation index before running")
    args = ap.parse_args()

    manifest_path = Path(args.manifest).resolve()
    manifest_dir = manifest_path.parent
    audio_dir = Path(args.audio_dir).resolve()

    with open(manifest_path, "r", encoding="utf-8") as f:
        cases = json.load(f)
    print(f"Loaded {len(cases)} cases from {manifest_path}")

    converter = AudioConverter()
    ffmpeg_path = converter._find_ffmpeg()
    vgmstream_path = converter._find_vgmstream()

    fp_db = FingerprintDatabase(db_path=get_game_fingerprint_database_file(args.game_id))
    idx_path = get_game_constellation_index_file(args.game_id)
    if args.reset_index and idx_path.exists():
        print(f"Deleting {idx_path}")
        idx_path.unlink()
    idx = ConstellationIndex(sqlite_path=idx_path)

    if idx.stats()["files"] == 0:
        _populate_index(audio_dir, idx, ffmpeg_path, vgmstream_path)

    # Prefetch candidates once (shared across cases) to avoid re-extracting per case
    print("Loading candidate catalog into memory...")
    t0 = time.time()
    all_candidates = list(_collect_candidates(audio_dir))
    print(f"  {len(all_candidates)} candidates in {time.time()-t0:.1f}s")

    matcher = AudioMatcher(ffmpeg_path=ffmpeg_path, fingerprint_db=fp_db, vgmstream_path=vgmstream_path)

    ranks = []
    times = []
    for i, case in enumerate(cases, start=1):
        name = case.get("name", f"case{i}")
        rank, elapsed = run_one(case, manifest_dir, audio_dir, matcher, idx, ffmpeg_path, all_candidates)
        ranks.append(rank)
        times.append(elapsed)
        rank_str = f"{rank:>2}/20" if rank > 0 else "  -   "
        print(f"[{i:>2}/{len(cases)}] {name:<30} target rank {rank_str} in {elapsed:5.1f}s")

    fp_db.save()

    found = [r for r in ranks if r > 0]
    print("---")
    print(f"Median rank (found only): {statistics.median(found) if found else 'n/a'}")
    print(f"Mean rank (found only):   {statistics.mean(found):.2f}" if found else "Mean rank: n/a")
    print(f"Recall@20: {len(found)}/{len(ranks)}")
    print(f"Mean time per query: {statistics.mean(times):.1f}s")

    idx.close()


if __name__ == "__main__":
    main()
