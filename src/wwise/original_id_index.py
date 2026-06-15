# Index of WEM/sound ids already present in a game's original StreamingAssets PCKs.
# An add mod must use a new id, so the app rejects a collision at creation and reallocates one at apply.
# The index is built once per StreamingAssets root and cached.

import threading
from pathlib import Path

from src.core.logger import get_logger
from src.wwise.pck_indexer import PCKIndexer

logger = get_logger(__name__)

_cache = {}
_lock = threading.Lock()

# Reallocations start at a high range unlikely to clash with real ids.
# We verify against the used set regardless.
_REALLOC_BASE = 0xF0000000


def build_original_id_index(streaming_root) -> set:
    # Every bank/sound/external id across the StreamingAssets PCKs (index tables only — no WEM data).
    ids = set()
    root = Path(streaming_root) if streaming_root else None
    if root is None or not root.exists():
        return ids
    for pck in root.rglob("*.pck"):
        try:
            data = PCKIndexer(str(pck)).build_index()
        except Exception as e:
            logger.warning(f"[OrigIndex] Skipping {pck.name}: {e}")
            continue
        for section in ("sounds", "externals", "banks"):
            for entry in (data.get(section) or []):
                try:
                    ids.add(int(entry["id"]))
                except (KeyError, TypeError, ValueError):
                    pass
    return ids


def get_original_id_index(streaming_root, refresh=False) -> set:
    # Cached per StreamingAssets root. Safe to call from any thread.
    if not streaming_root:
        return set()
    key = str(Path(streaming_root))
    if not refresh:
        with _lock:
            cached = _cache.get(key)
        if cached is not None:
            # Copy so a caller mutating the result can't corrupt the shared cache.
            return set(cached)
    built = build_original_id_index(streaming_root)
    with _lock:
        _cache[key] = built
    logger.info(f"[OrigIndex] Indexed {len(built)} original ids under {key}")
    return set(built)


def clear_cache(streaming_root=None):
    with _lock:
        if streaming_root is None:
            _cache.clear()
        else:
            _cache.pop(str(Path(streaming_root)), None)


def allocate_free_ids(colliding_ids, used_ids) -> dict:
    # Map each colliding id -> a fresh id present neither in `used_ids` nor in the new allocations.
    rename = {}
    used = {int(x) for x in used_ids}
    candidate = _REALLOC_BASE
    for old in colliding_ids:
        while candidate in used:
            candidate += 1
            if candidate > 0xFFFFFFFF:
                candidate = 1
        rename[int(old)] = candidate
        used.add(candidate)
        candidate += 1
    return rename
