# Promotes pristine originals from Persistent into StreamingAssets and wipes Persistent
# Pristine = md5 match vs the launcher pkg_version manifests or the game's .hash sidecars.

import hashlib
import json
import shutil
from pathlib import Path

from src.core.config_manager import get_game_state_dir
from src.core.game_registry import get_game
from src.core.logger import get_logger
from src.wwise.override_pck_patcher import restore_override_pck_backups
from src.wwise.patch_target_resolver import plain_wem_id
from src.wwise.pck_indexer import PCKIndexer

logger = get_logger(__name__)

_INDEX_FILE = "originals_index.json"
_CHUNK = 1 << 20  # 1 MB
_MANIFEST_GLOB = "*pkg_version"
_MANIFEST_WALK_UP = 8


def _md5(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def _parse_hash_sidecar(name):
    # "External0_826a...da.hash" -> ("External0.pck", "826a...da").
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


def _scan_sidecars(folder):
    # {pck_name: original_md5} from the *.hash sidecars in a single folder.
    out = {}
    try:
        for h in folder.glob("*.hash"):
            parsed = _parse_hash_sidecar(h.name)
            if parsed:
                out[parsed[0]] = parsed[1]
    except OSError:
        pass
    return out


def _sidecars_for_pck(folder, pck_name):
    # The <stem>_<md5>.hash files describing pck_name inside folder.
    out = []
    try:
        for h in folder.glob(f"{Path(pck_name).stem}_*.hash"):
            parsed = _parse_hash_sidecar(h.name)
            if parsed and parsed[0] == pck_name:
                out.append(h)
    except OSError:
        pass
    return out


def _promote_sidecars(pck, s_path):
    # The .hash travels with its pck, replacing any stale one next to the streaming copy.
    sidecars = _sidecars_for_pck(pck.parent, pck.name)
    if not sidecars:
        return
    names = {h.name for h in sidecars}
    for stale in _sidecars_for_pck(s_path.parent, s_path.name):
        if stale.name not in names:
            stale.unlink(missing_ok=True)
    for h in sidecars:
        shutil.copy2(h, s_path.parent / h.name)


def _reunite_sidecars(s_folder, p_folder, pck_name):
    # Move the pck's .hash next to its StreamingAssets copy, or drop it when one is already there.
    moved = 0
    for h in _sidecars_for_pck(p_folder, pck_name):
        try:
            if _sidecars_for_pck(s_folder, pck_name):
                h.unlink()
            else:
                shutil.move(str(h), str(s_folder / h.name))
            moved += 1
        except OSError as e:
            logger.error(f"[Persistent Originals] Failed to relocate sidecar {h.name}: {e}")
    return moved


def relocate_orphan_sidecars(game, streaming_root, persistent_root):
    # Earlier promotions moved the pck but stranded its .hash in Persistent; reunite them.
    moved = 0
    for h in persistent_root.rglob("*.hash"):
        parsed = _parse_hash_sidecar(h.name)
        if not parsed:
            continue
        pck_name = parsed[0]
        if game.is_protected_pck(pck_name) or (h.parent / pck_name).exists():
            continue
        try:
            rel_folder = h.parent.relative_to(persistent_root)
        except ValueError:
            continue
        s_folder = streaming_root / rel_folder
        if not (s_folder / pck_name).is_file():
            continue
        moved += _reunite_sidecars(s_folder, h.parent, pck_name)
    return moved


def load_manifest_md5s(streaming_root):
    # {rel_pck_path: (md5, size)} from the manifests found walking up to the game root.
    streaming_root = Path(streaming_root)
    d = streaming_root
    for _ in range(_MANIFEST_WALK_UP):
        if d.parent == d:
            break
        d = d.parent
        manifests = sorted(d.glob(_MANIFEST_GLOB))
        if not manifests:
            continue
        try:
            prefix = streaming_root.relative_to(d).as_posix() + "/"
        except ValueError:
            return {}
        entries = {}
        for mf in manifests:
            try:
                lines = mf.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue
                name = str(obj.get("remoteName", ""))
                if not name.lower().endswith(".pck") or not name.startswith(prefix):
                    continue
                md5_val = str(obj.get("md5", "")).lower()
                if len(md5_val) != 32:
                    continue
                try:
                    size_val = int(obj.get("fileSize", -1))
                except (TypeError, ValueError):
                    size_val = -1
                entries[name[len(prefix):]] = (md5_val, size_val)
        if entries:
            logger.info(f"[Persistent Originals] Loaded {len(entries)} pck hash(es) "
                f"from {len(manifests)} manifest(s) in {d}")
        return entries
    return {}


def _entry_target_ids(entries):
    # The integer ids a set of tracker entries targets, for candidate disambiguation.
    ids = {plain_wem_id(info, key) for key, info in (entries or {}).items()}
    ids.discard(None)
    return ids


def _candidate_contains(candidate, target_ids):
    try:
        indexer = PCKIndexer(str(candidate))
        indexer.build_index()
        return any(entry["id"] in target_ids for entry in indexer.get_file_list())
    except Exception:
        return False


def locate_pck_paths(streaming_root, persistent_root, pck_name, entries=None):
    # Every rebuild resolves here: source under StreamingAssets, output mirroring its subpath under Persistent.
    # pck_name may be a bare name or a folder-qualified key; (None, None) when no source exists.
    streaming_root = Path(streaming_root)
    persistent_root = Path(persistent_root)
    direct = streaming_root / pck_name
    if direct.exists():
        return direct, persistent_root / pck_name
    candidates = []
    try:
        for subdir in sorted(streaming_root.iterdir()):
            if subdir.is_dir() and (subdir / pck_name).exists():
                candidates.append(subdir / pck_name)
    except OSError:
        return None, None
    if not candidates:
        return None, None
    chosen = candidates[0]
    if len(candidates) > 1:
        target_ids = _entry_target_ids(entries)
        if target_ids:
            for candidate in candidates:
                if _candidate_contains(candidate, target_ids):
                    chosen = candidate
                    break
    rel = chosen.relative_to(streaming_root)
    return chosen, persistent_root / rel


class _Md5Cache:
    # size+mtime keyed md5 cache; losing it only costs rehashing.

    def __init__(self, backup_root):
        self.backup_root = Path(backup_root)
        self.path = self.backup_root / _INDEX_FILE
        self.files = {}
        self.dirty = False
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if data.get("schema") == 2:
                self.files = data.get("files", {})
        except Exception:
            pass

    def md5(self, path, key, st=None):
        st = st or path.stat()
        entry = self.files.get(key)
        if entry and entry.get("size") == st.st_size and entry.get("mtime") == int(st.st_mtime):
            return entry["md5"]
        digest = _md5(path)
        self.files[key] = {"size": st.st_size, "mtime": int(st.st_mtime), "md5": digest}
        self.dirty = True
        return digest

    def seed(self, path, key, digest):
        # Records a known digest for a file just written, skipping the rehash.
        try:
            st = path.stat()
        except OSError:
            return
        self.files[key] = {"size": st.st_size, "mtime": int(st.st_mtime), "md5": digest}
        self.dirty = True

    def save(self):
        if not self.dirty:
            return
        try:
            self.backup_root.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps({"schema": 2, "files": self.files}, indent=2),
                encoding="utf-8",
            )
            self.dirty = False
        except Exception as e:
            logger.error(f"[Persistent Originals] Failed to save md5 cache: {e}")


def _copy_original(src, dst):
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        dst.chmod(0o644)
    shutil.copy2(src, dst)
    dst.chmod(0o644)


def has_streaming_original(streaming_root, rel_path):
    return (Path(streaming_root) / rel_path).is_file()


def _ground_truth(manifest, sidecar_cache, pck, rel):
    # (original_md5, expected_size); size < 0 = unknown (sidecars carry no size).
    entry = manifest.get(rel)
    if entry:
        return entry
    folder = pck.parent
    if folder not in sidecar_cache:
        sidecar_cache[folder] = _scan_sidecars(folder)
    md5_val = sidecar_cache[folder].get(pck.name)
    if md5_val:
        return (md5_val, -1)
    return (None, -1)


def promote_originals(game_id, streaming_root, persistent_root, modded_keys, progress_cb=None, manifest=None):
    # Returns (stats, keep); rels in keep must never be deleted by cleanup.
    streaming_root = Path(streaming_root)
    persistent_root = Path(persistent_root)
    stats = {"promoted": 0, "updated": 0, "kept_mod": 0, "orphan": 0, "conflict": 0}
    keep = set()
    if not persistent_root.is_dir():
        return stats, keep

    game = get_game(game_id)
    # Tracker keys come in both shapes: folder-qualified keys match the rel, bare keys match the name.
    modded_rels = set()
    modded_basenames = set()
    for key in (modded_keys or ()):
        key = str(key)
        (modded_rels if "/" in key else modded_basenames).add(key)
    cache = _Md5Cache(get_game_state_dir(game_id))
    if manifest is None:
        manifest = load_manifest_md5s(streaming_root)
    sidecar_cache = {}

    for pck in persistent_root.rglob("*.pck"):
        if game.is_protected_pck(pck.name):
            continue
        try:
            rel = pck.relative_to(persistent_root).as_posix()
            st = pck.stat()
        except (ValueError, OSError):
            continue
        s_path = streaming_root / rel
        original_md5, expected_size = _ground_truth(manifest, sidecar_cache, pck, rel)

        if original_md5:
            if expected_size >= 0 and st.st_size != expected_size:
                matches = False
            else:
                matches = cache.md5(pck, f"persistent/{rel}", st) == original_md5
            if not matches:
                stats["kept_mod"] += 1
                if not s_path.is_file():
                    stats["orphan"] += 1
                    if progress_cb:
                        progress_cb(f"Warning: no original for modded {rel}")
                continue
            try:
                if not s_path.is_file():
                    _copy_original(pck, s_path)
                    cache.seed(s_path, f"streaming/{rel}", original_md5)
                    stats["promoted"] += 1
                    logger.info(f"[Persistent Originals] Promoted {rel} into StreamingAssets")
                    if progress_cb:
                        progress_cb(f"Secured original: {rel}")
                else:
                    s_st = s_path.stat()
                    if (s_st.st_size != st.st_size
                            or cache.md5(s_path, f"streaming/{rel}", s_st) != original_md5):
                        _copy_original(pck, s_path)
                        cache.seed(s_path, f"streaming/{rel}", original_md5)
                        stats["updated"] += 1
                        logger.info(f"[Persistent Originals] Updated original {rel} in StreamingAssets")
                _promote_sidecars(pck, s_path)
            except Exception as e:
                keep.add(rel)  # securing failed: never delete the only good copy
                logger.error(f"[Persistent Originals] Failed to promote {rel}: {e}")
            continue

        if rel in modded_rels or pck.name in modded_basenames:
            stats["kept_mod"] += 1
            if not s_path.is_file():
                stats["orphan"] += 1
                if progress_cb:
                    progress_cb(f"Warning: no original for modded {rel}")
            continue
        if manifest:
            # A non-empty manifest lists every original under this root: an unlisted pck is not game data.
            # Never adopt it into StreamingAssets; the misplaced-copy sweep handles our own leftovers.
            keep.add(rel)
            stats["conflict"] += 1
            logger.warning(f"[Persistent Originals] {rel} has no manifest entry; not promoting")
            continue
        if not s_path.is_file():
            try:
                p_md5 = cache.md5(pck, f"persistent/{rel}", st)
                _copy_original(pck, s_path)
                cache.seed(s_path, f"streaming/{rel}", p_md5)
                stats["promoted"] += 1
                logger.info(f"[Persistent Originals] Promoted {rel} into StreamingAssets (no ground truth)")
                if progress_cb:
                    progress_cb(f"Secured original: {rel}")
            except Exception as e:
                keep.add(rel)
                logger.error(f"[Persistent Originals] Failed to promote {rel}: {e}")
            continue
        try:
            s_st = s_path.stat()
            same = (s_st.st_size == st.st_size
                    and cache.md5(s_path, f"streaming/{rel}", s_st)
                    == cache.md5(pck, f"persistent/{rel}", st))
        except OSError:
            same = False
        if not same:
            stats["conflict"] += 1
            keep.add(rel)
            logger.warning(f"[Persistent Originals] {rel} differs from StreamingAssets "
                f"and has no ground truth; leaving both in place")

    cache.save()
    return stats, keep


def remove_misplaced_copies(game_id, streaming_root, persistent_root, manifest=None):
    # Old builds wrote resolver targets at the audio-root level and promotion then adopted them.
    # Deletes a root-level pck only when the manifest skips it there, lists its name under a subfolder, and that original exists on disk.
    streaming_root = Path(streaming_root)
    persistent_root = Path(persistent_root)
    if manifest is None:
        manifest = load_manifest_md5s(streaming_root)
    if not manifest:
        return 0
    game = get_game(game_id)
    subfolder_rels = {}
    for rel_key in manifest:
        if "/" in rel_key:
            subfolder_rels.setdefault(Path(rel_key).name, []).append(rel_key)
    removed = 0
    for root in (streaming_root, persistent_root):
        if not root.is_dir():
            continue
        for pck in root.glob("*.pck"):
            if game.is_protected_pck(pck.name) or pck.name in manifest:
                continue
            true_rels = subfolder_rels.get(pck.name, [])
            if not any((streaming_root / r).is_file() for r in true_rels):
                continue
            try:
                pck.chmod(0o644)
                pck.unlink()
                removed += 1
                logger.info(f"[Persistent Originals] Removed misplaced {pck} (original lives at {true_rels[0]})")
            except Exception as e:
                logger.error(f"[Persistent Originals] Failed to remove misplaced {pck.name}: {e}")
    return removed


def cleanup_persistent_overlay(game_id, streaming_root, persistent_root, modded_keys, progress_cb=None):
    # Sweep misplaced copies -> promote -> wipe overlay where the fallback exists -> restore protected backups.
    streaming_root = Path(streaming_root)
    persistent_root = Path(persistent_root)
    result = {"promoted": 0, "updated": 0, "kept_mod": 0, "orphan": 0, "conflict": 0,
              "deleted": 0, "kept": 0, "sidecars_moved": 0, "override_restored": 0, "misplaced_removed": 0}
    if not persistent_root.is_dir():
        return result

    manifest = load_manifest_md5s(streaming_root)
    try:
        result["misplaced_removed"] = remove_misplaced_copies(game_id, streaming_root, persistent_root, manifest)
    except Exception as e:
        logger.error(f"[Persistent Originals] Misplaced-copy sweep failed: {e}")

    stats, keep = promote_originals(
        game_id, streaming_root, persistent_root, modded_keys, progress_cb, manifest
    )
    result.update(stats)

    game = get_game(game_id)
    for pck in persistent_root.rglob("*.pck"):
        if game.is_protected_pck(pck.name):
            continue
        try:
            rel = pck.relative_to(persistent_root).as_posix()
        except ValueError:
            continue
        if rel in keep or not has_streaming_original(streaming_root, rel):
            result["kept"] += 1
            continue
        try:
            pck.chmod(0o644)
            pck.unlink()
            result["deleted"] += 1
        except Exception as e:
            logger.error(f"[Persistent Originals] Failed to delete {rel}: {e}")
            continue
        result["sidecars_moved"] += _reunite_sidecars((streaming_root / rel).parent, pck.parent, pck.name)

    try:
        result["sidecars_moved"] += relocate_orphan_sidecars(game, streaming_root, persistent_root)
    except Exception as e:
        logger.error(f"[Persistent Originals] Sidecar relocation failed: {e}")

    try:
        result["override_restored"] = restore_override_pck_backups(persistent_root, get_game(game_id))
    except Exception as e:
        logger.error(f"[Persistent Originals] Failed to restore override backups: {e}")

    return result
