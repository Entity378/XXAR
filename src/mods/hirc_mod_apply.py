# Apply offset-free HIRC track patches carried by add-based mods.
# Each patch targets a MusicTrack by pck/bnk/track id, so it survives game updates.
# The edits are size-preserving, so each BNK is patched in place with no repack.

import shutil
from collections import defaultdict
from pathlib import Path

import src.core.app_config as app_config
from src.core.logger import get_logger
from src.wwise.hirc_music import apply_track_patches_to_bnk
from src.wwise.pck_indexer import PCKIndexer

logger = get_logger(__name__)


def _ensure_writable_overlay(source_pck, streaming_root, persistent_root, fresh_clone):
    # Return a writable Persistent overlay for source_pck, mirroring its StreamingAssets location.
    # With fresh_clone the file is re-copied from Streaming so the draft's old_source_id checks match.
    # Otherwise an existing overlay is reused, since this run's cleanup already wiped stale ones.
    try:
        rel_path = source_pck.relative_to(streaming_root)
    except ValueError:
        rel_path = Path(source_pck.name)
    overlay_path = persistent_root / rel_path
    overlay_path.parent.mkdir(parents=True, exist_ok=True)
    if not overlay_path.exists() or fresh_clone:
        if overlay_path.exists():
            try:
                overlay_path.chmod(0o644)
            except Exception:
                pass
        shutil.copy2(source_pck, overlay_path)
    try:
        overlay_path.chmod(0o644)
    except Exception:
        pass
    return overlay_path


def apply_hirc_track_patches(track_patches, streaming_root, persistent_root, fresh_clone=False, status_cb=None):
    # Each patch is {pck_name, bnk_id, track_obj_id, source_remaps, loop_ms?, volume_db?}.
    # The stored pck_name can be stale, so each bnk is found by id in whatever soundbank pck holds it.
    # Return counts of patched bank files and patched bnks.
    apply_summary = {"patched_files": 0, "patched_bnks": 0}
    if not track_patches:
        return apply_summary
    streaming_root = Path(streaming_root) if streaming_root else None
    persistent_root = Path(persistent_root) if persistent_root else None
    if not streaming_root or not streaming_root.exists() or not persistent_root:
        logger.warning("[HIRC mod] Missing streaming/persistent root; skipping HIRC patches")
        return apply_summary

    patches_by_bnk_id = defaultdict(list)
    for patch in track_patches:
        if patch.get("bnk_id") is not None:
            patches_by_bnk_id[int(patch["bnk_id"])].append(patch)
    unresolved_bnk_ids = set(patches_by_bnk_id)

    # Only the soundbank pcks hold bnks, matching how patch_target_resolver locates them.
    # The scan stops once every requested bnk has been found.
    soundbank_glob = app_config.SOUNDBANK_PCK_GLOB or "*.pck"
    for soundbank_pck in sorted(streaming_root.rglob(soundbank_glob)):
        if not unresolved_bnk_ids:
            break
        try:
            bnk_ids_in_pck = {bank["id"] for bank in PCKIndexer(str(soundbank_pck)).build_index().get("banks", [])}
        except Exception:
            continue
        matched_bnk_ids = unresolved_bnk_ids & bnk_ids_in_pck
        if not matched_bnk_ids:
            continue
        unresolved_bnk_ids -= matched_bnk_ids

        overlay_pck = _ensure_writable_overlay(soundbank_pck, streaming_root, persistent_root, fresh_clone)
        try:
            # Re-index the overlay: after a per-pck rebuild its bnk offsets can differ from the source.
            bank_info_by_id = {
                bank["id"]: bank for bank in PCKIndexer(str(overlay_pck)).build_index().get("banks", [])
            }
            pck_was_patched = False
            with open(overlay_pck, "r+b") as overlay_file:
                for bnk_id in matched_bnk_ids:
                    bank_info = bank_info_by_id.get(bnk_id)
                    if bank_info is None:
                        continue
                    overlay_file.seek(bank_info["offset"])
                    bnk_bytes = bytearray(overlay_file.read(bank_info["size"]))
                    patch_counts = apply_track_patches_to_bnk(bnk_bytes, patches_by_bnk_id[bnk_id])
                    if patch_counts["remaps"] + patch_counts["loops"] + patch_counts["volumes"] <= 0:
                        continue
                    if len(bnk_bytes) != bank_info["size"]:
                        logger.error(f"[HIRC mod] bnk {bnk_id} size changed; not writing")
                        continue
                    overlay_file.seek(bank_info["offset"])
                    overlay_file.write(bytes(bnk_bytes))
                    pck_was_patched = True
                    apply_summary["patched_bnks"] += 1
                    logger.info(
                        f"[HIRC mod] {soundbank_pck.name}:{bnk_id} -> "
                        f"{patch_counts['remaps']} remap(s), {patch_counts['loops']} loop(s), "
                        f"{patch_counts['volumes']} volume(s)"
                    )
        except Exception as e:
            logger.error(f"[HIRC mod] Failed to patch {soundbank_pck.name}: {e}")
            continue
        if pck_was_patched:
            apply_summary["patched_files"] += 1

    if unresolved_bnk_ids:
        logger.warning(f"[HIRC mod] bnk(s) not found in any pck, skipped: {sorted(unresolved_bnk_ids)}")
    if status_cb and apply_summary["patched_files"]:
        status_cb(f"HIRC track patches applied in {apply_summary['patched_files']} bank file(s).")
    return apply_summary
