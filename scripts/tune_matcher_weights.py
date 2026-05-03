# Dev-only: tune the mean/std re-rank weights on a benchmark set.

# Usage:
#     python scripts/tune_matcher_weights.py <manifest.json> <audio_dir> [options]

# Options:
#     --game-id ID       Default: zzz
#     --samples N        Random simplex samples to evaluate (default 200)
#     --reset-index      Wipe constellation index before running
#     --top K            Report top K weight vectors (default 5)
#     --seed S           RNG seed (default 0)

# Reuses the benchmark harness to populate constellation + fingerprint caches
# once, then performs random-simplex sampling over the 9 scorer weights. The
# default weights are evaluated first as baseline. Output is a list of the best
# weight dicts by median rank (found cases only), ties broken by recall@20 and
# mean rank.

# The script does NOT modify matcher.py. Copy the chosen weights into
# DEFAULT_WEIGHTS at the top of src/audio/matcher.py manually.


from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
import time
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from src.audio import constellation
from src.audio.converter import AudioConverter
from src.audio.matcher import AudioMatcher, DEFAULT_WEIGHTS
from src.data.constellation_index import ConstellationIndex
from src.data.fingerprint_database import FingerprintDatabase
from src.core.config_manager import (
    get_game_constellation_index_file,
    get_game_fingerprint_database_file,
)

from benchmark_matcher import _collect_candidates, _populate_index, _resolve


def _sample_weights(rng: np.random.Generator, keys: list[str]) -> dict[str, float]:
    raw = rng.dirichlet(np.ones(len(keys)))
    return {k: float(v) for k, v in zip(keys, raw)}


def _rank_target(
    matcher: AudioMatcher,
    query_fp,
    shortlist_fps: list[tuple[str, dict]],
    target_hash: str,
    weights: dict,
    top_n: int = 20,
) -> int:
    scored = [
        (matcher.compare_fingerprints(query_fp, cand_fp, weights=weights), fh)
        for fh, cand_fp in shortlist_fps
    ]
    scored.sort(key=lambda r: r[0], reverse=True)
    for i, (_score, fh) in enumerate(scored[:top_n], start=1):
        if fh == target_hash:
            return i
    return -1


def _evaluate(matcher, cases_ctx, weights):
    ranks = [
        _rank_target(matcher, ctx["query_fp"], ctx["shortlist_fps"], ctx["target_hash"], weights)
        for ctx in cases_ctx
    ]
    found = [r for r in ranks if r > 0]
    if not found:
        return {"median": float("inf"), "mean": float("inf"), "recall": 0, "ranks": ranks}
    return {
        "median": statistics.median(found),
        "mean": statistics.mean(found),
        "recall": len(found) / len(ranks),
        "ranks": ranks,
    }


def _format_weights(w: dict) -> str:
    return "{ " + ", ".join(f"{k}: {v:.3f}" for k, v in w.items()) + " }"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("manifest")
    ap.add_argument("audio_dir")
    ap.add_argument("--game-id", default="zzz")
    ap.add_argument("--samples", type=int, default=200)
    ap.add_argument("--top", type=int, default=5)
    ap.add_argument("--reset-index", action="store_true")
    ap.add_argument("--seed", type=int, default=0)
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

    matcher = AudioMatcher(
        ffmpeg_path=ffmpeg_path,
        vgmstream_path=vgmstream_path,
        fingerprint_db=fp_db,
    )

    print("Prefetching candidate catalog + fingerprints...")
    t0 = time.time()
    all_candidates = list(_collect_candidates(audio_dir))
    fp_by_hash = {}
    for i, (wem_bytes, _meta) in enumerate(all_candidates, start=1):
        h = hashlib.sha256(wem_bytes).hexdigest()
        if h in fp_by_hash:
            continue
        cached = fp_db.get_fingerprint(wem_bytes)
        if cached is None:
            cached = matcher.extract_fingerprint_from_bytes(wem_bytes)
            if cached is not None:
                fp_db.add_fingerprint(wem_bytes, cached)
        if cached is not None:
            fp_by_hash[h] = cached
        if i % 500 == 0:
            print(f"  fingerprinted {i}/{len(all_candidates)} ({time.time()-t0:.1f}s)")
    fp_db.save()
    print(f"Cached {len(fp_by_hash)} candidate fingerprints in {time.time()-t0:.1f}s")

    print("Pre-computing per-case shortlists...")
    cases_ctx = []
    for case in cases:
        name = case.get("name", "?")
        query_path = _resolve(manifest_dir, case["query"])
        target_path = _resolve(manifest_dir, case["target_wem"])
        target_hash = hashlib.sha256(target_path.read_bytes()).hexdigest()

        audio = constellation.decode_file(ffmpeg_path, query_path)
        if audio is None:
            print(f"  SKIP {name}: decode failed")
            continue
        query_fp = matcher._build_fingerprint(audio, constellation.SAMPLE_RATE)
        if query_fp is None:
            print(f"  SKIP {name}: fingerprint failed")
            continue

        query_hashes = constellation.extract_hashes(audio)
        shortlist = idx.query(query_hashes, top_k=200) if query_hashes else []
        shortlist_hashes = [entry[0] for entry in shortlist] if shortlist else list(fp_by_hash.keys())

        shortlist_fps = [(h, fp_by_hash[h]) for h in shortlist_hashes if h in fp_by_hash]
        cases_ctx.append({
            "name": name,
            "query_fp": query_fp,
            "shortlist_fps": shortlist_fps,
            "target_hash": target_hash,
            "target_in_shortlist": target_hash in {h for h, _ in shortlist_fps},
        })

    print(f"Prepared {len(cases_ctx)} cases")
    oos = [c for c in cases_ctx if not c["target_in_shortlist"]]
    if oos:
        print(f"  WARN: {len(oos)} case(s) have target NOT in constellation shortlist:")
        for c in oos:
            print(f"    - {c['name']}")

    # Baseline evaluation
    baseline = _evaluate(matcher, cases_ctx, DEFAULT_WEIGHTS)
    print("\n=== Baseline (current DEFAULT_WEIGHTS) ===")
    print(f"  median rank: {baseline['median']}  mean: {baseline['mean']:.2f}  recall@20: {baseline['recall']*100:.0f}%")
    print(f"  weights: {_format_weights(DEFAULT_WEIGHTS)}")

    # Random simplex search
    keys = list(DEFAULT_WEIGHTS.keys())
    rng = np.random.default_rng(args.seed)
    trials = [(DEFAULT_WEIGHTS, baseline)]

    print(f"\nSampling {args.samples} random simplex weight vectors...")
    t0 = time.time()
    for i in range(args.samples):
        w = _sample_weights(rng, keys)
        metrics = _evaluate(matcher, cases_ctx, w)
        trials.append((w, metrics))
        if (i + 1) % 50 == 0:
            print(f"  {i+1}/{args.samples} trials in {time.time()-t0:.1f}s")

    # Sort: lower median is better, tie-break by higher recall then lower mean
    trials.sort(key=lambda t: (t[1]["median"], -t[1]["recall"], t[1]["mean"]))

    print(f"\n=== Top {args.top} weight vectors ===")
    for rank, (w, m) in enumerate(trials[:args.top], start=1):
        tag = " (BASELINE)" if w is DEFAULT_WEIGHTS else ""
        print(f"\n#{rank}{tag}")
        print(f"  median: {m['median']}  mean: {m['mean']:.2f}  recall@20: {m['recall']*100:.0f}%")
        print(f"  weights: {_format_weights(w)}")

    best_w, best_m = trials[0]
    improvement = baseline["median"] - best_m["median"]
    print(f"\n=== Summary ===")
    print(f"  baseline median: {baseline['median']}")
    print(f"  best median:     {best_m['median']}  ({'improvement' if improvement > 0 else 'no improvement or equal'})")
    if best_w is not DEFAULT_WEIGHTS:
        print(f"  best weights (copy into DEFAULT_WEIGHTS in src/audio/matcher.py):")
        print(f"    " + _format_weights(best_w))

    idx.close()


if __name__ == "__main__":
    main()
