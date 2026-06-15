# Apply offset-free HIRC track patches (by pck/bnk/track id) carried by add-based mods.
# Size-preserving edits patch in place; a volume insert grows a BNK and triggers a pck repack.

import os
import shutil
import tempfile
from collections import defaultdict
from pathlib import Path

import src.core.app_config as app_config
from src.core.logger import get_logger
from src.wwise.hirc_music import apply_track_patches_to_bnk
from src.wwise.pck_indexer import PCKIndexer
from src.wwise.pck_packer import PCKPacker

logger = get_logger(__name__)


def _repack_overlay(overlay_pck, modified):
    # Rebuild the pck, swapping in patched bnk bytes when a volume insert grew a bnk.
    # An in-place write would overrun the next entry, so write a temp file and replace atomically.
    fd, tmp_name = tempfile.mkstemp(suffix=".pck", dir=str(overlay_pck.parent))
    os.close(fd)
    tmp_path = Path(tmp_name)
    packer = None
    packed = False
    try:
        packer = PCKPacker(str(overlay_pck), str(tmp_path))
        packer.load_original_pck()
        for bnk_id, (lang_id, new_bytes) in modified.items():
            packer.replace_bnk_raw(bnk_id, new_bytes, lang_id)
        packer.pack(use_patching=False)
        packed = True
    finally:
        if packer is not None:
            packer.close()
    if not packed:
        tmp_path.unlink(missing_ok=True)
        raise RuntimeError("pck repack failed")
    os.replace(str(tmp_path), str(overlay_pck))


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
            # Patch each matched bnk in memory, since a volume insert can grow it.
            # Then write size-preserving edits in place, or repack the whole pck if any bnk grew.
            modified = {}  # bnk_id -> (lang_id, new_bytes)
            grew = False
            with open(overlay_pck, "rb") as overlay_file:
                for bnk_id in matched_bnk_ids:
                    bank_info = bank_info_by_id.get(bnk_id)
                    if bank_info is None:
                        continue
                    overlay_file.seek(bank_info["offset"])
                    bnk_bytes = bytearray(overlay_file.read(bank_info["size"]))
                    patch_counts = apply_track_patches_to_bnk(bnk_bytes, patches_by_bnk_id[bnk_id])
                    if patch_counts["remaps"] + patch_counts["loops"] + patch_counts["volumes"] <= 0:
                        continue
                    modified[bnk_id] = (bank_info["lang_id"], bytes(bnk_bytes))
                    if len(bnk_bytes) != bank_info["size"]:
                        grew = True
                    logger.info(
                        f"[HIRC mod] {soundbank_pck.name}:{bnk_id} -> "
                        f"{patch_counts['remaps']} remap(s), {patch_counts['loops']} loop(s), "
                        f"{patch_counts['volumes']} volume(s)"
                    )

            if not modified:
                continue

            if grew:
                _repack_overlay(overlay_pck, modified)
            else:
                with open(overlay_pck, "r+b") as overlay_file:
                    for bnk_id, (lang_id, new_bytes) in modified.items():
                        overlay_file.seek(bank_info_by_id[bnk_id]["offset"])
                        overlay_file.write(new_bytes)
            apply_summary["patched_bnks"] += len(modified)
            apply_summary["patched_files"] += 1
        except Exception as e:
            logger.error(f"[HIRC mod] Failed to patch {soundbank_pck.name}: {e}")
            continue

    if unresolved_bnk_ids:
        logger.warning(f"[HIRC mod] bnk(s) not found in any pck, skipped: {sorted(unresolved_bnk_ids)}")
    if status_cb and apply_summary["patched_files"]:
        status_cb(f"HIRC track patches applied in {apply_summary['patched_files']} bank file(s).")
    return apply_summary
