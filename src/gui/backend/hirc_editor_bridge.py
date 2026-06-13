import json
import os
import re
import shutil
import struct
from fnmatch import fnmatch
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def _natural_pck_key(name: str) -> list:
    # Natural sort key so 'Music10.pck' comes after 'Music2.pck'.
    return [
        int(chunk) if chunk.isdigit() else chunk.lower()
        for chunk in re.split(r"(\d+)", name)
    ]


from PyQt6.QtCore import (
    QObject,
    QThread,
    pyqtSignal,
    pyqtSlot,
)

import src.core.app_config as app_config
from src.audio.converter import AudioConverter
from src.core.config_manager import (
    get_game_hirc_draft_file,
    get_game_hirc_draft_wem_dir,
    get_game_sound_database_file,
    get_settings_file,
)
from src.core.game_registry import (
    DEFAULT_GAME_ID,
    get_audio_settings_keys,
    get_game,
)
from src.core.logger import get_logger
from src.data.sound_database import SoundDatabase
from src.gui.utils.native_dialogs import NativeDialogs
from src.mods.hirc_mod_apply import apply_hirc_track_patches
from src.wwise.hirc_music import (
    _collect_bnk_music_index,
    _extract_track_source_ids,
    _scan_bnk_music_objects,
    apply_track_patches_to_bnk,
)
from src.wwise.hirc_patcher import (
    apply_duration_patches,
    scan_bank_for_patch_targets,
)
from src.wwise.pck_indexer import PCKIndexer
from src.wwise.pck_packer import PCKPacker

logger = get_logger(__name__)


# ── Background loader (QThread) ──────────────────────────────────────────────

# Walks every .pck under the active game's audio roots.
# Lists bnks that contain at least one music HIRC object.
# Cancellable from the bridge.
class BnkListLoaderWorker(QThread):

    progress = pyqtSignal(str)
    finished_ok = pyqtSignal("QVariant")
    failed = pyqtSignal(str)

    def __init__(self, audio_root: Path, persistent_audio_root: Optional[Path]):
        super().__init__()
        self._audio_root = audio_root
        self._persistent_audio_root = persistent_audio_root
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            result = self._scan()
            if not self._cancel:
                self.finished_ok.emit(result)
        except Exception as e:
            logger.exception("[HIRC Editor] Bnk list scan failed")
            if not self._cancel:
                self.failed.emit(str(e))

    def _scan(self) -> List[dict]:
        # Dedupe by pck_name across StreamingAssets and Persistent.
        # When the same file exists in both roots, Persistent wins (it's the live override the game actually loads).
        # Tag override entries so the UI can flag them.
        pck_map: Dict[str, Tuple[Path, bool]] = {}
        if self._audio_root is not None and self._audio_root.exists():
            for p in self._audio_root.rglob("*.pck"):
                pck_map[p.name] = (p, False)
        if self._persistent_audio_root is not None and self._persistent_audio_root.exists():
            for p in self._persistent_audio_root.rglob("*.pck"):
                pck_map[p.name] = (p, True)  # override

        all_pcks = sorted(pck_map.values(), key=lambda t: t[0].name)

        result: List[dict] = []
        total = len(all_pcks)
        for i, (pck_path, is_override) in enumerate(all_pcks, 1):
            if self._cancel:
                return []
            try:
                indexer = PCKIndexer(str(pck_path))
                indexer.build_index()
            except Exception as e:
                logger.warning(f"[HIRC Editor] Skipping {pck_path.name}: {e}")
                continue
            banks = indexer.index_data["banks"]
            if not banks:
                continue
            with open(pck_path, "rb") as f:
                for binfo in banks:
                    if self._cancel:
                        return []
                    f.seek(binfo["offset"])
                    content = f.read(binfo["size"])
                    n_music, src_ids = _collect_bnk_music_index(content)
                    if n_music == 0:
                        continue
                    result.append({
                        "pck_name": pck_path.name,
                        "pck_path": str(pck_path),
                        "bnk_id": binfo["id"],
                        "bnk_size": binfo["size"],
                        "music_object_count": n_music,
                        "is_override": is_override,
                        "source_ids": sorted(src_ids),
                    })
            if i % 8 == 0 or i == total:
                self.progress.emit(
                    f"Scanned {i}/{total} pcks, {len(result)} bnks with music HIRC..."
                )
        result.sort(key=lambda r: (_natural_pck_key(r["pck_name"]), r["bnk_id"]))
        return result


class WemConvertWorker(QThread):
    # Convert an arbitrary audio file to .wem off the UI thread (Wwise shellout is slow).
    # .wem inputs are copied as-is.
    finished_ok = pyqtSignal(str, str)  # (wem_path, source_name)
    failed = pyqtSignal(str)

    def __init__(self, audio_path: Path, dest_wem: Path, normalize: bool = False,
                 streaming_root=None, wem_id=None):
        super().__init__()
        self._audio_path = Path(audio_path)
        self._dest_wem = Path(dest_wem)
        self._normalize = normalize
        self._streaming_root = streaming_root
        self._wem_id = wem_id

    def run(self):
        try:
            # An add must use a new id, so reject one that already exists in the originals.
            # Building the index here keeps it off the UI thread.
            if self._streaming_root is not None and self._wem_id is not None:
                from src.wwise.original_id_index import get_original_id_index
                if int(self._wem_id) in get_original_id_index(self._streaming_root):
                    self.failed.emit(
                        f"WEM id {self._wem_id} already exists in the game's original files. "
                        f"Choose a different (unused) id."
                    )
                    return
            self._dest_wem.parent.mkdir(parents=True, exist_ok=True)
            if self._audio_path.suffix.lower() == ".wem":
                shutil.copy2(self._audio_path, self._dest_wem)
            else:
                converter = AudioConverter()
                out = Path(converter.any_to_wem(
                    str(self._audio_path),
                    output_file=str(self._dest_wem),
                    normalize=self._normalize,
                ))
                if out != self._dest_wem and out.exists():
                    shutil.move(str(out), str(self._dest_wem))
            self.finished_ok.emit(str(self._dest_wem), self._audio_path.name)
        except Exception as e:
            logger.exception("[HIRC Editor] WEM conversion failed")
            self.failed.emit(str(e))


class ApplyDraftWorker(QThread):
    # Replay a HIRC draft onto the live game (Persistent): media WEM adds + track patches.
    progress = pyqtSignal(str)
    finished_ok = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, media_adds, track_patches, add_fn, streaming_root, persistent_root):
        super().__init__()
        self._media_adds = list(media_adds)
        self._track_patches = list(track_patches)
        self._add_fn = add_fn  # bound HircEditorBridge._add_wem_to_pck
        self._streaming_root = streaming_root
        self._persistent_root = persistent_root

    def run(self):
        try:
            for item in self._media_adds:
                self.progress.emit(
                    f"Adding WEM {item['wem_id']} to {item['pck_name']}..."
                )
                self._add_fn(
                    item["pck_name"], int(item["wem_id"]), Path(item["wem_path"])
                )
            if self._track_patches:
                self.progress.emit("Applying track patches...")
                apply_hirc_track_patches(
                    self._track_patches,
                    self._streaming_root,
                    self._persistent_root,
                    fresh_clone=True,
                    status_cb=lambda m: self.progress.emit(str(m)),
                )
            self.finished_ok.emit("Draft applied to the live game.")
        except Exception as e:
            logger.exception("[HIRC Editor] Apply draft failed")
            self.failed.emit(str(e))


# ── Bridge ──────────────────────────────────────────────────────────────────

class HircEditorBridge(QObject):

    bnkListReady = pyqtSignal("QVariant")
    bnkHircReady = pyqtSignal(str, "qint64", "QVariant")
    statusUpdate = pyqtSignal(str)
    errorOccurred = pyqtSignal(str, str)
    patchApplied = pyqtSignal(str, "qint64", "qint64", "qint64")
    loopPatchApplied = pyqtSignal(str, "qint64", "qint64", float)
    volumePatchApplied = pyqtSignal(str, "qint64", float)
    wemAdded = pyqtSignal(str, "qint64", str)
    musicPckListReady = pyqtSignal("QVariant")
    inspectorCleared = pyqtSignal()

    # Mod-draft staging (Browser-style): stage edits, then Apply All / Export / Reset.
    draftChangesCount = pyqtSignal(int)
    draftChangesReady = pyqtSignal("QVariant")
    exportMetadataDialogReady = pyqtSignal("QVariant")
    thumbnailPathSelected = pyqtSignal(str)
    draftApplied = pyqtSignal(bool, str)
    modExported = pyqtSignal(bool, str)
    wemStaged = pyqtSignal(str, "qint64", str)

    def __init__(self):
        super().__init__()
        self._loader: Optional[BnkListLoaderWorker] = None
        self._draft = {"media_adds": [], "track_patches": []}
        self._draft_game_id: Optional[str] = None
        self._convert_worker: Optional[WemConvertWorker] = None
        self._apply_worker: Optional[ApplyDraftWorker] = None
        # Reverse index {wem_id: name} from the per-game sound database.
        # It is built lazily and refreshed on game switch to label HIRC sources.
        self._id_name_map: Optional[Dict[int, str]] = None
        self._id_name_game_id: Optional[str] = None

    # ── Settings + active-game lifecycle ────────────────────────────────

    @pyqtSlot()
    def loadFromSettings(self):
        # Called on bridge init / game switch to refresh bnk list for the currently-active game.
        # Equivalent to refreshBnkList for now.
        logger.info("[HIRC Editor] Loading from settings (active-game refresh)")
        self.refreshBnkList()

    @pyqtSlot()
    def refreshBnkList(self):
        self._cancel_loader()
        # Re-read tagged names on an explicit refresh (e.g. after tagging in the Browser).
        self._id_name_game_id = None
        audio_root = self._game_audio_dir()
        persistent_root = self._game_persistent_audio_dir()
        if audio_root is None:
            logger.info("[HIRC Editor] No game audio dir configured; emitting empty list")
            self.statusUpdate.emit(
                "No game audio directory configured for the active game."
            )
            self.bnkListReady.emit([])
            return
        logger.info(f"[HIRC Editor] Scanning {audio_root} (background)")
        self.statusUpdate.emit(f"Scanning {audio_root}...")
        worker = BnkListLoaderWorker(audio_root, persistent_root)
        worker.progress.connect(self._onLoaderProgress)
        worker.finished_ok.connect(self._onLoaderFinished)
        worker.failed.connect(self._onLoaderFailed)
        worker.finished.connect(self._onLoaderThreadDone)
        # Let Qt destroy the QThread on its own once run() has returned.
        # Without this, a stale worker's `finished` slot could null `self._loader` after we've already replaced it.
        # The live worker would lose its Python reference, then get GC'd mid-run, causing a segfault.
        worker.finished.connect(worker.deleteLater)
        self._loader = worker
        worker.start()

    @pyqtSlot()
    def unloadAll(self):
        # Drop the bnk list and the open inspector on game switch.
        logger.info("[HIRC Editor] Unloading all bnks (active-game change)")
        self._cancel_loader()
        self.bnkListReady.emit([])
        self.inspectorCleared.emit()
        self.statusUpdate.emit("Bnks unloaded (active game changed).")

    # ── Per-bnk HIRC inspection ─────────────────────────────────────────

    @pyqtSlot(str, "QVariant")
    def loadBnkHirc(self, pck_name, bnk_id):
        bnk_id_int = int(bnk_id)
        pck = str(pck_name)
        logger.info(f"[HIRC Editor] Loading HIRC for {pck}:{bnk_id_int}")
        try:
            objs = self._load_bnk_objects(pck, bnk_id_int)
        except Exception as e:
            logger.exception(f"[HIRC Editor] Failed to load HIRC for {pck}:{bnk_id_int}")
            self.errorOccurred.emit(
                "HIRC Load Error",
                f"Failed to load HIRC for {pck}:{bnk_id_int}\n{e}",
            )
            return
        self.bnkHircReady.emit(pck, bnk_id_int, objs)

    # ── Patch slots ─────────────────────────────────────────────────────

    @pyqtSlot(str, "QVariant", "QVariant", "QVariant")
    def patchSourceId(self, pck_name, abs_offset_in_pck, old_wem, new_wem):
        pck = str(pck_name)
        off = int(abs_offset_in_pck)
        old = int(old_wem)
        new = int(new_wem)
        logger.info(f"[HIRC Editor] Patch sourceID {pck}@{off}: {old} -> {new}")
        try:
            self._patch_source_id(pck, off, old, new)
        except Exception as e:
            logger.exception("[HIRC Editor] sourceID patch failed")
            self.errorOccurred.emit("Patch Error", f"Source ID patch failed:\n{e}")
            return
        self.patchApplied.emit(pck, off, old, new)

    @pyqtSlot(str, "QVariant", "QVariant", "QVariant")
    def patchLoopMs(self, pck_name, bnk_id, track_obj_id, loop_ms):
        pck = str(pck_name)
        bnk = int(bnk_id)
        tid = int(track_obj_id)
        ms = float(loop_ms)
        logger.info(f"[HIRC Editor] Patch loop {pck}:{bnk} track {tid} -> {ms} ms")
        try:
            self._patch_loop_ms(pck, bnk, tid, ms)
        except Exception as e:
            logger.exception("[HIRC Editor] Loop patch failed")
            self.errorOccurred.emit("Patch Error", f"Loop patch failed:\n{e}")
            return
        self.loopPatchApplied.emit(pck, bnk, tid, ms)

    @pyqtSlot()
    def listMusicPcks(self):
        # Emit a list of media pcks (Music*, Streamed*, Minimum) the user can target for wem insertion.
        # Persistent overrides shadow StreamingAssets copies.
        try:
            data = self._list_music_pcks()
        except Exception as e:
            logger.exception("[HIRC Editor] listMusicPcks failed")
            self.errorOccurred.emit(
                "List Pcks Error", f"Failed to list pcks: {e}"
            )
            return
        self.musicPckListReady.emit(data)

    def _list_music_pcks(self) -> List[dict]:
        game = get_game(self._current_game_id())
        music_globs = game.music_pck_globs
        soundbank_glob = game.soundbank_pck_glob
        protected = game.protected_pcks

        roots = []
        a = self._game_audio_dir()
        if a is not None and a.exists():
            roots.append((a, False))
        p = self._game_persistent_audio_dir()
        if p is not None and p.exists():
            roots.append((p, True))

        seen: Dict[str, dict] = {}
        for root, is_override in roots:
            for pck in sorted(root.rglob("*.pck")):
                name = pck.name
                # Always exclude SoundBank/Banks pcks (they hold bnks, not stream wems).
                # Also exclude protected pcks (Patch.pck/Hotfix.pck).
                if fnmatch(name, soundbank_glob):
                    continue
                if name in protected:
                    continue
                if music_globs:
                    # Game declares specific music pck patterns — must match.
                    if not any(fnmatch(name, g) for g in music_globs):
                        continue
                # else: permissive fallback (= every non-soundbank pck).
                seen[name] = {
                    "pck_name": name,
                    "pck_path": str(pck),
                    "size_bytes": pck.stat().st_size,
                    "is_override": is_override,
                }
        return sorted(seen.values(), key=lambda r: _natural_pck_key(r["pck_name"]))

    @pyqtSlot(str, "QVariant", str)
    def addWemToPck(self, pck_name, wem_id, wem_file_path):
        # Insert (or replace) a WEM with the given id into the named media pck.
        # Operates on the Persistent override.
        # Clones the original from StreamingAssets first if the override doesn't exist yet.
        pck = str(pck_name)
        wid = int(wem_id)
        src_path = Path(str(wem_file_path))
        logger.info(f"[HIRC Editor] Add WEM {wid} -> {pck} from {src_path}")
        try:
            self._add_wem_to_pck(pck, wid, src_path)
        except Exception as e:
            logger.exception("[HIRC Editor] Add WEM failed")
            self.errorOccurred.emit(
                "Add WEM Error", f"Failed to add WEM {wid} to {pck}:\n{e}"
            )
            return
        self.wemAdded.emit(pck, wid, str(src_path))

    def _add_wem_to_pck(self, pck_name: str, wem_id: int, src_wem: Path):
        if not src_wem.exists():
            raise FileNotFoundError(f"WEM file not found: {src_wem}")
        if not (0 <= wem_id <= 0xFFFFFFFF):
            raise ValueError(f"wem_id {wem_id} out of u32 range")

        target_pck = self._ensure_persistent_copy(pck_name)
        # PCKPacker keeps the original file open while writing.
        # Using target_pck as both source and destination would corrupt the file.
        # Write to a sibling temp file then atomic-replace.
        tmp_pck = target_pck.with_name(target_pck.name + ".new")
        if tmp_pck.exists():
            tmp_pck.unlink()

        self.statusUpdate.emit(
            f"Repacking {pck_name} with new WEM id {wem_id}..."
        )
        packer = PCKPacker(str(target_pck), str(tmp_pck))
        packer.load_original_pck()
        # PCKPacker section mapping.
        # soundbank_titles -> sec2 (.bnk archives, u32 IDs).
        # soundbank_files -> sec3 (sounds with u32 IDs); Genshin's Music*.pck and Streamed*.pck store wems here.
        # stream_files -> sec4 (externals with u64 IDs); usually unused.
        # bnks reference wems by u32 source_id.
        # We must add the new wem to sec3 (soundbank_files) for Wwise to resolve it from a bnk patch.
        packer.replace_file(
            wem_id, str(src_wem), lang_id=0, target_section="soundbank_files",
        )
        # Adding a NEW wem_id (not just replacing) requires a full rebuild.
        # Patching mode skips files whose id isn't already in the original.
        packer.pack(use_patching=False)
        packer.close()

        os.replace(str(tmp_pck), str(target_pck))
        size = src_wem.stat().st_size
        self.statusUpdate.emit(
            f"Added WEM {wem_id} to {pck_name} ({size:,} B from {src_wem.name})"
        )

    @pyqtSlot(str, "QVariant", "QVariant")
    def patchVolumeDb(self, pck_name, abs_offset_in_pck, db_value):
        pck = str(pck_name)
        off = int(abs_offset_in_pck)
        db = float(db_value)
        logger.info(f"[HIRC Editor] Patch volume {pck}@{off} -> {db} dB")
        try:
            self._patch_volume_db(pck, off, db)
        except Exception as e:
            logger.exception("[HIRC Editor] Volume patch failed")
            self.errorOccurred.emit("Patch Error", f"Volume patch failed:\n{e}")
            return
        self.volumePatchApplied.emit(pck, off, db)

    # ── Internal: loader callbacks ──────────────────────────────────────

    def _onLoaderProgress(self, msg):
        if self.sender() is not self._loader:
            return
        self.statusUpdate.emit(msg)

    def _onLoaderFinished(self, data):
        if self.sender() is not self._loader:
            return
        n = len(data) if data is not None else 0
        logger.info(f"[HIRC Editor] Bnk scan finished: {n} bnks")
        self._build_bnk_search_blobs(data)
        self.bnkListReady.emit(data)

    def _build_bnk_search_blobs(self, data):
        # Turn each bnk's source ids into a lowercase "id name" search blob.
        # The bnk-list filter uses it to search all banks by source id or tagged name.
        name_map = self._get_id_name_map()
        for entry in (data or []):
            ids = entry.pop("source_ids", []) or []
            parts = [str(i) for i in ids]
            for i in ids:
                nm = name_map.get(int(i))
                if nm:
                    parts.append(nm.lower())
            entry["search"] = " ".join(parts)

    def _onLoaderFailed(self, msg):
        if self.sender() is not self._loader:
            return
        logger.error(f"[HIRC Editor] Bnk scan failed: {msg}")
        self.errorOccurred.emit("Scan Error", f"Bnk scan failed:\n{msg}")

    def _onLoaderThreadDone(self):
        # Only drop the reference if the worker that just finished is the one we still hold.
        # A stale (cancelled-but-late) worker firing this slot must NOT clear the pointer to the active worker.
        if self.sender() is self._loader:
            self._loader = None

    def _cancel_loader(self):
        if self._loader is not None and self._loader.isRunning():
            self._loader.cancel()
            self._loader.wait(2000)
        self._loader = None

    # ── Internal: HIRC loading ──────────────────────────────────────────

    def _load_bnk_objects(self, pck_name: str, bnk_id: int) -> List[dict]:
        pck_path = self._resolve_pck_path(pck_name)
        if pck_path is None:
            raise FileNotFoundError(f"PCK not found: {pck_name}")
        indexer = PCKIndexer(str(pck_path))
        indexer.build_index()
        for binfo in indexer.index_data["banks"]:
            if binfo["id"] == bnk_id:
                with open(pck_path, "rb") as f:
                    f.seek(binfo["offset"])
                    content = f.read(binfo["size"])
                objs = _scan_bnk_music_objects(content, binfo["offset"])
                self._annotate_source_names(objs)
                return objs
        raise KeyError(f"bnk_id {bnk_id} not in {pck_name}")

    def _get_id_name_map(self) -> Dict[int, str]:
        # Map wem ids to names from the active game's sound database, cached per game.
        gid = self._current_game_id()
        if self._id_name_game_id != gid:
            mapping: Dict[int, str] = {}
            try:
                db = SoundDatabase(db_path=get_game_sound_database_file(gid))
                db.ensure_loaded()
                for info in db.database.values():
                    name = info.get("name")
                    if not name:
                        continue
                    for fid in (info.get("file_ids") or []):
                        try:
                            mapping[int(fid)] = name
                        except (TypeError, ValueError):
                            continue
            except Exception as e:
                logger.warning(f"[HIRC Editor] Failed to load sound names: {e}")
            self._id_name_map = mapping
            self._id_name_game_id = gid
        return self._id_name_map

    def _annotate_source_names(self, objs):
        # Tag each AkBankSourceData / TrackSrcInfo entry with its DB name (when known).
        name_map = self._get_id_name_map()
        if not name_map:
            return
        for o in objs:
            for entry in (o.get("sources") or []):
                nm = name_map.get(int(entry.get("source_id", -1)))
                if nm:
                    entry["name"] = nm
            for entry in (o.get("playlist") or []):
                nm = name_map.get(int(entry.get("source_id", -1)))
                if nm:
                    entry["name"] = nm

    @pyqtSlot()
    def refreshSoundNames(self):
        # Invalidate the name cache (e.g. after the user tags sounds in the Browser).
        self._id_name_game_id = None

    # ── Internal: patching ──────────────────────────────────────────────

    def _patch_source_id(self, pck_name: str, abs_offset: int,
                         old_wem: int, new_wem: int):
        target_pck = self._ensure_persistent_copy(pck_name)
        with open(target_pck, "r+b") as f:
            f.seek(abs_offset)
            cur = f.read(4)
            if struct.unpack("<I", cur)[0] != old_wem:
                raise ValueError(
                    f"Expected {old_wem} at offset {abs_offset}, "
                    f"found {struct.unpack('<I', cur)[0]}"
                )
            f.seek(abs_offset)
            f.write(struct.pack("<I", new_wem))
        self.statusUpdate.emit(
            f"Patched {pck_name} @{abs_offset}: {old_wem} -> {new_wem}"
        )

    def _patch_loop_ms(self, pck_name: str, bnk_id: int,
                       track_obj_id: int, loop_ms: float):
        target_pck = self._ensure_persistent_copy(pck_name)
        indexer = PCKIndexer(str(target_pck))
        indexer.build_index()
        bnk_info = next(
            (b for b in indexer.index_data["banks"] if b["id"] == bnk_id), None
        )
        if bnk_info is None:
            raise KeyError(f"bnk_id {bnk_id} not in {pck_name}")

        with open(target_pck, "rb") as f:
            f.seek(bnk_info["offset"])
            bnk_content = bytearray(f.read(bnk_info["size"]))

        track_source_ids = _extract_track_source_ids(bnk_content, track_obj_id)
        if not track_source_ids:
            raise ValueError(
                f"Track {track_obj_id} has no AkBankSourceData with sources"
            )

        targets = scan_bank_for_patch_targets(bnk_content, track_source_ids)
        duration_map = {sid: loop_ms for sid in track_source_ids}

        result = apply_duration_patches(bnk_content, targets, duration_map)

        with open(target_pck, "r+b") as f:
            f.seek(bnk_info["offset"])
            f.write(bytes(bnk_content))

        self.statusUpdate.emit(
            f"Loop patched: {pck_name}:{bnk_id} track {track_obj_id} -> "
            f"{loop_ms} ms ({result['patched_offsets']} fields)"
        )

    def _patch_volume_db(self, pck_name: str, abs_offset: int, db_value: float):
        target_pck = self._ensure_persistent_copy(pck_name)
        with open(target_pck, "r+b") as f:
            f.seek(abs_offset)
            f.write(struct.pack("<f", db_value))
        self.statusUpdate.emit(
            f"Volume patched: {pck_name} @{abs_offset} -> {db_value} dB"
        )

    def _ensure_persistent_copy(self, pck_name: str) -> Path:
        audio_dir = self._game_audio_dir()
        streaming_pck = audio_dir / pck_name if audio_dir else None
        persistent_dir = self._game_persistent_audio_dir()
        if persistent_dir is None or streaming_pck is None or not streaming_pck.exists():
            raise FileNotFoundError(
                "StreamingAssets pck or Persistent dir unavailable"
            )
        persistent_dir.mkdir(parents=True, exist_ok=True)
        target_pck = persistent_dir / pck_name
        if not target_pck.exists():
            logger.info(f"[HIRC Editor] Cloning {streaming_pck} -> {target_pck}")
            self.statusUpdate.emit(f"Cloning {pck_name} to Persistent...")
            shutil.copy2(streaming_pck, target_pck)
        return target_pck

    # ── Internal: path resolution ───────────────────────────────────────

    def _resolve_pck_path(self, pck_name: str) -> Optional[Path]:
        for root in self._candidate_audio_roots():
            for p in root.rglob(pck_name):
                if p.is_file():
                    return p
        return None

    def _candidate_audio_roots(self) -> List[Path]:
        # Persistent first: it overrides StreamingAssets at runtime.
        # We want the live version when showing HIRC (the bytes the game actually loads).
        # The StreamingAssets original would be misleading.
        roots: List[Path] = []
        p = self._game_persistent_audio_dir()
        if p is not None and p.exists():
            roots.append(p)
        a = self._game_audio_dir()
        if a is not None:
            roots.append(a)
        return roots

    def _load_settings(self) -> dict:
        settings_file = get_settings_file()
        if not settings_file.exists():
            return {}
        try:
            return json.loads(settings_file.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _audio_settings_keys(self) -> Tuple[str, str]:
        return get_audio_settings_keys(self._current_game_id())

    def _current_game_id(self) -> str:
        if hasattr(app_config, "_active_game") and app_config._active_game:
            return app_config._active_game.id
        return DEFAULT_GAME_ID

    def _game_audio_dir(self) -> Optional[Path]:
        settings = self._load_settings()
        audio_key, _ = self._audio_settings_keys()
        candidate = settings.get(audio_key) or settings.get("game_audio_dir")
        if not candidate:
            return None
        return self._walk_to_audioassets(Path(candidate))

    def _game_persistent_audio_dir(self) -> Optional[Path]:
        settings = self._load_settings()
        _, persist_key = self._audio_settings_keys()
        candidate = settings.get(persist_key) or settings.get("persistent_audio_dir")
        if not candidate:
            return None
        return self._walk_to_audioassets(Path(candidate))

    @staticmethod
    def _walk_to_audioassets(path: Path) -> Optional[Path]:
        # Settings often points to a sub-folder (e.g. .../AudioAssets/Music).
        # Walk up to AudioAssets so we can recurse over every .pck.
        cur = path
        for _ in range(4):
            if cur.name == "AudioAssets" and cur.exists():
                return cur
            if (cur / "AudioAssets").exists():
                return cur / "AudioAssets"
            cur = cur.parent
        return path if path.exists() else None

    # The draft holds media adds and track patches, persisted per game so it survives restarts.
    # Apply All replays it onto the live game and Export packages it as a .xxar.

    def _get_draft(self) -> dict:
        gid = self._current_game_id()
        if self._draft_game_id != gid:
            self._draft = self._load_draft(gid)
            self._draft_game_id = gid
        return self._draft

    def _load_draft(self, game_id: str) -> dict:
        try:
            f = get_game_hirc_draft_file(game_id)
            if f.exists():
                data = json.loads(f.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    data.setdefault("media_adds", [])
                    data.setdefault("track_patches", [])
                    return data
        except Exception as e:
            logger.warning(f"[HIRC Editor] Failed to load draft: {e}")
        return {"media_adds": [], "track_patches": []}

    def _save_draft(self):
        gid = self._draft_game_id or self._current_game_id()
        try:
            f = get_game_hirc_draft_file(gid)
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(json.dumps(self._draft, indent=2), encoding="utf-8")
        except Exception as e:
            logger.warning(f"[HIRC Editor] Failed to save draft: {e}")

    def _draft_count(self) -> int:
        d = self._get_draft()
        return len(d.get("media_adds", [])) + len(d.get("track_patches", []))

    def _emit_draft_count(self):
        self.draftChangesCount.emit(self._draft_count())

    @pyqtSlot()
    def refreshDraft(self):
        # Reload the draft for the active game and push the count to the UI.
        self._draft_game_id = None
        self._get_draft()
        self._emit_draft_count()

    @pyqtSlot(str, "QVariant", str, "QVariant")
    def stageAddWem(self, pck_name, wem_id, audio_file_path, lang_id):
        # Convert (if needed) then stage a new WEM add into the named media pck.
        pck = str(pck_name)
        try:
            wid = int(wem_id)
        except (TypeError, ValueError):
            self.errorOccurred.emit("Add WEM", "Invalid WEM id.")
            return
        if not (0 <= wid <= 0xFFFFFFFF):
            self.errorOccurred.emit("Add WEM", f"WEM id {wid} out of u32 range.")
            return
        src = Path(str(audio_file_path))
        if not src.exists():
            self.errorOccurred.emit("Add WEM", f"Audio file not found:\n{src}")
            return
        try:
            lid = int(lang_id)
        except (TypeError, ValueError):
            lid = 0

        gid = self._current_game_id()
        dest = get_game_hirc_draft_wem_dir(gid) / f"{wid}.wem"
        self.statusUpdate.emit(f"Converting {src.name} to WEM...")
        # Validate the id against the originals inside the worker (off the UI thread).
        worker = WemConvertWorker(src, dest, streaming_root=self._game_audio_dir(), wem_id=wid)
        worker.finished_ok.connect(
            lambda wem_path, sname, p=pck, w=wid, l=lid:
            self._on_wem_converted(p, w, l, wem_path, sname)
        )
        worker.failed.connect(
            lambda msg: self.errorOccurred.emit("Add WEM", f"Conversion failed:\n{msg}")
        )
        worker.finished.connect(worker.deleteLater)
        self._convert_worker = worker
        worker.start()

    def _on_wem_converted(self, pck, wem_id, lang_id, wem_path, source_name):
        d = self._get_draft()
        wid = int(wem_id)
        # One media add per (pck, wem_id): a re-add replaces the previous staging.
        d["media_adds"] = [
            m for m in d["media_adds"]
            if not (m.get("pck_name") == pck and int(m.get("wem_id")) == wid)
        ]
        d["media_adds"].append({
            "pck_name": pck,
            "wem_id": wid,
            "wem_path": str(wem_path),
            "lang_id": int(lang_id),
            "source_name": source_name,
        })
        self._save_draft()
        self._emit_draft_count()
        self.statusUpdate.emit(f"Staged WEM {wid} -> {pck} ({source_name})")
        self.wemStaged.emit(pck, wid, source_name)

    @pyqtSlot(str, "QVariant", "QVariant", str, str, str)
    def stageTrackEdits(self, pck_name, bnk_id, track_obj_id,
                        remaps_json, loop_ms, volume_db):
        # Stage one MusicTrack's edits: source remaps (JSON list) + optional loop/volume.
        pck = str(pck_name)
        try:
            bnk = int(bnk_id)
            tid = int(track_obj_id)
        except (TypeError, ValueError):
            self.errorOccurred.emit("Stage", "Invalid bnk/track id.")
            return
        try:
            remaps = json.loads(remaps_json) if remaps_json else []
        except Exception:
            remaps = []

        loop_val = None
        if str(loop_ms).strip() != "":
            try:
                loop_val = float(loop_ms)
            except ValueError:
                loop_val = None
        vol_val = None
        if str(volume_db).strip() != "":
            try:
                vol_val = float(volume_db)
            except ValueError:
                vol_val = None

        if not remaps and loop_val is None and vol_val is None:
            return

        self._merge_track_patch(pck, bnk, tid, remaps, loop_val, vol_val)
        self._save_draft()
        self._emit_draft_count()
        self.statusUpdate.emit(f"Staged track {tid} edits in {pck}:{bnk}")

    def _merge_track_patch(self, pck, bnk, tid, remaps, loop_val, vol_val):
        d = self._get_draft()
        entry = None
        for tp in d["track_patches"]:
            if (tp.get("pck_name") == pck
                    and int(tp.get("bnk_id")) == bnk
                    and int(tp.get("track_obj_id")) == tid):
                entry = tp
                break
        if entry is None:
            entry = {
                "pck_name": pck, "bnk_id": bnk, "track_obj_id": tid,
                "source_remaps": [], "loop_ms": None, "volume_db": None,
            }
            d["track_patches"].append(entry)

        by_slot = {
            (r.get("slot"), int(r.get("index", 0))): r
            for r in entry["source_remaps"]
        }
        for r in remaps:
            try:
                slot = str(r.get("slot", "src"))
                idx = int(r.get("index", 0))
                new_id = int(r.get("new_source_id"))
            except (TypeError, ValueError):
                continue
            old_raw = r.get("old_source_id")
            by_slot[(slot, idx)] = {
                "slot": slot,
                "index": idx,
                "old_source_id": int(old_raw) if old_raw is not None else None,
                "new_source_id": new_id,
            }
        entry["source_remaps"] = list(by_slot.values())
        if loop_val is not None:
            entry["loop_ms"] = loop_val
        if vol_val is not None:
            entry["volume_db"] = vol_val

    @staticmethod
    def _num_str(v):
        # Compact numeric string for the editable fields ("" when unset).
        if v is None:
            return ""
        f = float(v)
        return str(int(f)) if f == int(f) else f"{f:g}"

    @pyqtSlot()
    def showDraftChanges(self):
        # Each change carries its editable parts as separate fields (Source, Loop, Volume).
        # The QML renders an input per part.
        # Track rows are editable; add rows show a read-only source.
        d = self._get_draft()
        changes = []
        for m in d.get("media_adds", []):
            wid = int(m.get("wem_id"))
            sname = m.get("source_name", "")
            changes.append({
                "kind": "add_wem",
                "pck_name": m.get("pck_name"),
                "wem_id": wid,
                "bnk_id": 0,
                "track_obj_id": 0,
                "remaps": [],
                "source_display": f"+ {wid}" + (f" ({sname})" if sname else ""),
                "loop_ms": "",
                "volume_db": "",
            })
        for tp in d.get("track_patches", []):
            remaps = [{
                "slot": str(r.get("slot", "src")),
                "index": int(r.get("index", 0)),
                "old_source_id": r.get("old_source_id"),
                "new_source_id": r.get("new_source_id"),
            } for r in (tp.get("source_remaps") or [])]
            changes.append({
                "kind": "track",
                "pck_name": tp.get("pck_name"),
                "wem_id": 0,
                "bnk_id": int(tp.get("bnk_id")),
                "track_obj_id": int(tp.get("track_obj_id")),
                "remaps": remaps,
                "source_display": "",
                "loop_ms": self._num_str(tp.get("loop_ms")),
                "volume_db": self._num_str(tp.get("volume_db")),
            })
        self.draftChangesReady.emit(changes)

    def _find_track_patch(self, pck, bnk_id, track_obj_id):
        d = self._get_draft()
        for tp in d.get("track_patches", []):
            if (tp.get("pck_name") == str(pck)
                    and int(tp.get("bnk_id")) == int(bnk_id)
                    and int(tp.get("track_obj_id")) == int(track_obj_id)):
                return tp
        return None

    def _track_patch_is_empty(self, tp):
        return (not tp.get("source_remaps")
                and tp.get("loop_ms") is None
                and tp.get("volume_db") is None)

    def _after_track_edit(self, tp, structural=False):
        # Persist, and drop the patch if it no longer changes anything.
        # Re-emit the list only on a structural change (row added or removed).
        # A value-only edit must not rebuild the model, or the edited field loses focus.
        d = self._get_draft()
        if self._track_patch_is_empty(tp):
            d["track_patches"] = [x for x in d.get("track_patches", []) if x is not tp]
            self._save_draft()
            self._emit_draft_count()
            self.showDraftChanges()
            return
        self._save_draft()
        if structural:
            self.showDraftChanges()

    @pyqtSlot(str, "QVariant", "QVariant", str)
    def setDraftTrackLoop(self, pck, bnk_id, track_obj_id, value):
        tp = self._find_track_patch(pck, bnk_id, track_obj_id)
        if tp is None:
            return
        v = str(value).strip()
        if v == "":
            tp["loop_ms"] = None
        else:
            try:
                tp["loop_ms"] = max(0.0, float(v))
            except ValueError:
                return
        self._after_track_edit(tp)

    @pyqtSlot(str, "QVariant", "QVariant", str)
    def setDraftTrackVolume(self, pck, bnk_id, track_obj_id, value):
        tp = self._find_track_patch(pck, bnk_id, track_obj_id)
        if tp is None:
            return
        v = str(value).strip()
        if v == "":
            tp["volume_db"] = None
        else:
            try:
                tp["volume_db"] = max(-96.0, min(24.0, float(v)))
            except ValueError:
                return
        self._after_track_edit(tp)

    @pyqtSlot(str, "QVariant", "QVariant", str, "QVariant", str)
    def setDraftRemapTarget(self, pck, bnk_id, track_obj_id, slot, index, value):
        tp = self._find_track_patch(pck, bnk_id, track_obj_id)
        if tp is None:
            return
        slot = str(slot)
        idx = int(index)
        remaps = tp.get("source_remaps") or []
        v = str(value).strip()
        if v == "":
            # Clearing a remap's target removes that remap (structural — refresh the dialog).
            tp["source_remaps"] = [
                r for r in remaps
                if not (str(r.get("slot")) == slot and int(r.get("index", 0)) == idx)
            ]
            self._after_track_edit(tp, structural=True)
            return
        try:
            nid = int(v)
        except ValueError:
            return
        if not (0 <= nid <= 0xFFFFFFFF):
            return
        for r in remaps:
            if str(r.get("slot")) == slot and int(r.get("index", 0)) == idx:
                r["new_source_id"] = nid
                break
        self._after_track_edit(tp)

    @pyqtSlot(str, "QVariant")
    def removeDraftMediaAdd(self, pck_name, wem_id):
        d = self._get_draft()
        wid = int(wem_id)
        before = len(d["media_adds"])
        d["media_adds"] = [
            m for m in d["media_adds"]
            if not (m.get("pck_name") == str(pck_name) and int(m.get("wem_id")) == wid)
        ]
        if len(d["media_adds"]) != before:
            self._save_draft()
            self._emit_draft_count()
            self.showDraftChanges()

    @pyqtSlot(str, "QVariant", "QVariant")
    def removeDraftTrackPatch(self, pck_name, bnk_id, track_obj_id):
        d = self._get_draft()
        bnk = int(bnk_id)
        tid = int(track_obj_id)
        before = len(d["track_patches"])
        d["track_patches"] = [
            tp for tp in d["track_patches"]
            if not (tp.get("pck_name") == str(pck_name)
                    and int(tp.get("bnk_id")) == bnk
                    and int(tp.get("track_obj_id")) == tid)
        ]
        if len(d["track_patches"]) != before:
            self._save_draft()
            self._emit_draft_count()
            self.showDraftChanges()

    @pyqtSlot()
    def resetDraft(self):
        d = self._get_draft()
        try:
            wem_dir = get_game_hirc_draft_wem_dir(self._draft_game_id or self._current_game_id())
            for m in d.get("media_adds", []):
                wp = Path(str(m.get("wem_path", "")))
                try:
                    if wp.exists() and wem_dir in wp.parents:
                        wp.unlink()
                except Exception:
                    pass
        except Exception:
            pass
        self._draft = {"media_adds": [], "track_patches": []}
        self._save_draft()
        self._emit_draft_count()
        self.statusUpdate.emit("Draft cleared.")

    def _reallocate_collisions(self, media_adds, track_patches, streaming_root):
        # Any staged add whose id already exists in the originals is moved to a free id.
        # The matching remaps follow, and copies are returned so the draft keeps the user's ids.
        from src.wwise.original_id_index import allocate_free_ids, get_original_id_index
        orig_ids = get_original_id_index(streaming_root)
        colliding = [int(m["wem_id"]) for m in media_adds
                     if int(m.get("wem_id", -1)) in orig_ids]
        if not colliding:
            return media_adds, track_patches
        used = set(orig_ids) | {int(m.get("wem_id", -1)) for m in media_adds}
        for tp in track_patches:
            for r in (tp.get("source_remaps") or []):
                try:
                    used.add(int(r.get("new_source_id")))
                except (TypeError, ValueError):
                    pass
        rename = allocate_free_ids(colliding, used)
        new_media = []
        for m in media_adds:
            wid = int(m.get("wem_id", -1))
            if wid in rename:
                m = dict(m)
                m["wem_id"] = rename[wid]
            new_media.append(m)
        new_patches = []
        for tp in track_patches:
            remaps = []
            for r in (tp.get("source_remaps") or []):
                try:
                    nid = int(r.get("new_source_id"))
                except (TypeError, ValueError):
                    remaps.append(r)
                    continue
                if nid in rename:
                    r = dict(r)
                    r["new_source_id"] = rename[nid]
                remaps.append(r)
            tp = dict(tp)
            tp["source_remaps"] = remaps
            new_patches.append(tp)
        logger.warning(f"[HIRC Editor] Live apply reallocated colliding ids: {rename}")
        self.statusUpdate.emit(f"Reallocated {len(rename)} colliding WEM id(s) to free ids.")
        return new_media, new_patches

    @pyqtSlot()
    def applyDraftLive(self):
        if self._draft_count() == 0:
            self.errorOccurred.emit("Apply", "Nothing staged to apply.")
            return
        if self._apply_worker is not None and self._apply_worker.isRunning():
            self.statusUpdate.emit("Apply already in progress...")
            return
        streaming = self._game_audio_dir()
        persistent = self._game_persistent_audio_dir()
        if streaming is None or persistent is None:
            self.errorOccurred.emit("Apply", "Game audio directories are not configured.")
            return
        d = self._get_draft()
        media_adds, track_patches = self._reallocate_collisions(
            list(d.get("media_adds", [])), list(d.get("track_patches", [])), streaming
        )
        self.statusUpdate.emit("Applying draft to the live game...")
        worker = ApplyDraftWorker(
            media_adds, track_patches,
            self._add_wem_to_pck, streaming, persistent,
        )
        worker.progress.connect(lambda m: self.statusUpdate.emit(m))
        worker.finished_ok.connect(lambda m: self.statusUpdate.emit(m))
        worker.finished_ok.connect(lambda m: self.draftApplied.emit(True, m))
        worker.failed.connect(lambda m: self.errorOccurred.emit("Apply Error", m))
        worker.failed.connect(lambda m: self.draftApplied.emit(False, m))
        worker.finished.connect(worker.deleteLater)
        self._apply_worker = worker
        worker.start()

    @pyqtSlot()
    def exportDraftAsMod(self):
        if self._draft_count() == 0:
            self.errorOccurred.emit("Export", "Nothing staged to export.")
            return
        self.exportMetadataDialogReady.emit({})

    @pyqtSlot()
    def browseThumbnail(self):
        filename = NativeDialogs.get_open_file(
            "Select Thumbnail Image",
            filter_str="Images (*.png *.jpg *.jpeg *.bmp);;All Files (*)",
            remember_key="thumbnail",
        )
        if filename:
            self.thumbnailPathSelected.emit(filename)

    @pyqtSlot(str, str, str, str, str)
    def createModPackage(self, name, author, version, description, thumbnail_path):
        d = self._get_draft()
        if self._draft_count() == 0:
            self.errorOccurred.emit("Export", "Nothing staged to export.")
            return

        replacements = {}
        for m in d.get("media_adds", []):
            wp = Path(str(m.get("wem_path", "")))
            if not wp.exists():
                self.errorOccurred.emit(
                    "Export", f"Staged WEM missing on disk:\n{wp}"
                )
                return
            pck = m.get("pck_name")
            replacements.setdefault(pck, {})[str(int(m.get("wem_id")))] = {
                "wem_path": str(wp),
                "file_type": "wem",
                "lang_id": int(m.get("lang_id", 0)),
                "bnk_id": None,
                "sound_name": m.get("source_name", ""),
                "is_add": True,  # new id, not a replacement -> apply guards against id collisions
            }
        hirc_patches = d.get("track_patches", [])

        version = version or "1.0.0"
        default_name = f"{(name or 'mod').replace(' ', '_')}_v{version}{app_config.MOD_FILE_EXT}"
        filename = NativeDialogs.get_save_file(
            "Save Mod Package",
            filter_str=f"{app_config.MOD_FILE_EXT_UPPER} Mod Packages (*{app_config.MOD_FILE_EXT});;All Files (*)",
            remember_key="save_mod",
            default_filename=default_name,
        )
        if not filename:
            return
        if not filename.lower().endswith(app_config.MOD_FILE_EXT.lower()):
            filename += app_config.MOD_FILE_EXT

        try:
            from src.mods.package_manager import ModPackageManager
            mod_pkg = ModPackageManager(game_id=self._current_game_id())
            metadata = {
                "name": name or "Untitled",
                "author": author or "",
                "version": version,
                "description": description or "",
            }
            thumb = thumbnail_path if (thumbnail_path and thumbnail_path.strip()) else None
            mod_pkg.create_mod_package(
                filename, metadata, replacements, thumb, hirc_patches=hirc_patches
            )
            self.statusUpdate.emit(f"Mod package created: {Path(filename).name}")
            self.modExported.emit(True, Path(filename).name)
        except Exception as e:
            logger.exception("[HIRC Editor] Export failed")
            self.errorOccurred.emit(
                "Export Error", f"Failed to create mod package:\n{e}"
            )
            self.modExported.emit(False, str(e))
