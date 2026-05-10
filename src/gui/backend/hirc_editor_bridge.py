import json
import re
import shutil
import struct
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
from src.core.logger import get_logger
from src.wwise.pck_indexer import PCKIndexer
from src.wwise.pck_packer import PCKPacker
from src.wwise.hirc_patcher import (
    scan_bank_for_patch_targets,
    apply_duration_patches,
)

logger = get_logger(__name__)


# ── HIRC parsing constants ───────────────────────────────────────────────────

HIRC_TYPE_NAMES = {
    0x0A: "MusicSegment",
    0x0B: "MusicTrack",
    0x0C: "MusicSwitchCntr",
    0x0D: "MusicRanSeqCntr",
}
MUSIC_HIRC_TYPES = set(HIRC_TYPE_NAMES.keys())
HIRC_TYPE_MUSIC_TRACK = 0x0B

# AkBankSourceData layout (14 bytes per source).
# pluginID(4) + streamType(1) + sourceID(4) + mediaSize(4) + sourceBits(1).
_SOURCE_DATA_SIZE = 14
_SOURCE_ID_OFFSET_IN_SOURCE = 5

# TrackSrcInfo (44 bytes per playlist item).
# trackID(4) + sourceID(4) + eventID(4) + fPlayAt(8) + fBeginTrim(8) + fEndTrim(8) + fSrcDuration(8).
_TRACK_SRC_INFO_SIZE = 44


# ── Pure HIRC helpers (module-level, easier to unit-test) ────────────────────

def _find_hirc_sections(content: bytes):
    # Yield (data_start, data_size) for each HIRC chunk in a bnk.
    flen = len(content)
    pos = -1
    while True:
        pos = content.find(b"HIRC", pos + 1)
        if pos == -1:
            break
        if pos + 12 > flen:
            break
        section_size = struct.unpack_from("<I", content, pos + 4)[0]
        if section_size < 4 or pos + 8 + section_size > flen:
            continue
        yield (pos + 8, section_size)


def _iter_music_types_in_content(content: bytes):
    for hs, hsz in _find_hirc_sections(content):
        se = hs + hsz
        if hs + 4 > se:
            continue
        n_obj = struct.unpack_from("<I", content, hs)[0]
        op = hs + 4
        for _ in range(n_obj):
            if op + 5 > se:
                break
            ot = content[op]
            osz = struct.unpack_from("<I", content, op + 1)[0]
            if ot in MUSIC_HIRC_TYPES:
                yield ot
            op = op + 5 + osz


def _parse_music_track_fields(
    content: bytes, ds: int, de: int, abs_off_base: int
) -> Optional[dict]:
    # Extract MusicTrack obj_id + AkBankSourceData/TrackSrcInfo entries with absolute pck offsets.
    # Also returns the current loop_ms (TrackSrcInfo[0].fSrcDuration).
    if ds + 9 > de:
        return None
    obj_id = struct.unpack_from("<I", content, ds)[0]
    num_sources = struct.unpack_from("<I", content, ds + 5)[0]
    if num_sources < 0 or num_sources > 100:
        return None

    sources: List[dict] = []
    p = ds + 9
    for k in range(num_sources):
        if p + _SOURCE_DATA_SIZE > de:
            break
        sid_off = p + _SOURCE_ID_OFFSET_IN_SOURCE
        sid = struct.unpack_from("<I", content, sid_off)[0]
        sources.append({
            "index": k,
            "source_id": sid,
            "abs_offset_in_pck": abs_off_base + sid_off,
        })
        p += _SOURCE_DATA_SIZE

    playlist: List[dict] = []
    if p + 4 <= de:
        num_pl = struct.unpack_from("<I", content, p)[0]
        p += 4
        if 0 <= num_pl <= 200:
            for j in range(num_pl):
                if p + _TRACK_SRC_INFO_SIZE > de:
                    break
                ts_sid_off = p + 4
                ts_sid = struct.unpack_from("<I", content, ts_sid_off)[0]
                playlist.append({
                    "index": j,
                    "source_id": ts_sid,
                    "abs_offset_in_pck": abs_off_base + ts_sid_off,
                })
                p += _TRACK_SRC_INFO_SIZE

    loop_ms: Optional[float] = None
    loop_clear_offset_abs: Optional[int] = None
    loop_duration_offset_abs: Optional[int] = None
    if playlist:
        first_ts_sid_off = playlist[0]["abs_offset_in_pck"] - abs_off_base
        ts_struct_start = first_ts_sid_off - 4  # back up to trackID
        clear_off = ts_struct_start + 8
        dur_off = ts_struct_start + 36
        if 0 <= dur_off + 8 <= len(content):
            try:
                loop_ms = struct.unpack_from("<d", content, dur_off)[0]
                loop_clear_offset_abs = abs_off_base + clear_off
                loop_duration_offset_abs = abs_off_base + dur_off
            except Exception:
                loop_ms = None

    return {
        "obj_id": obj_id,
        "type": "MusicTrack",
        "type_hex": "0x0B",
        "body_size": de - ds,
        "sources": sources,
        "playlist": playlist,
        "loop_ms": loop_ms,
        "loop_clear_offset_abs": loop_clear_offset_abs,
        "loop_duration_offset_abs": loop_duration_offset_abs,
        "volume_db": None,
        "volume_offset_abs": None,
        "has_volume": False,
        # Internal: bnk-relative bounds used to disambiguate per-track volumes.
        # They matter when multiple tracks share the same source_id.
        # Stripped before leaving the bridge.
        "_ds_local": ds,
        "_de_local": de,
    }


def _parse_music_object_basic(
    obj_type: int, content: bytes, ds: int, de: int
) -> Optional[dict]:
    if ds + 4 > de:
        return None
    obj_id = struct.unpack_from("<I", content, ds)[0]
    out: dict = {
        "obj_id": obj_id,
        "type": HIRC_TYPE_NAMES.get(obj_type, f"0x{obj_type:02X}"),
        "type_hex": f"0x{obj_type:02X}",
        "body_size": de - ds,
        "sources": [],
        "playlist": [],
        "loop_ms": None,
        "loop_clear_offset_abs": None,
        "loop_duration_offset_abs": None,
        "volume_db": None,
        "volume_offset_abs": None,
        "has_volume": False,
    }
    # NOTE: container-type AkPropBundle parsing is unreliable for Genshin's Wwise variant.
    # Both alignments (with/without bOverrideAttachmentParams) produce garbage prop_ids/values.
    # This affects MusicSegment, MusicRanSeqCntr and MusicSwitchCntr.
    # The Volume offset for these nodes most likely lives elsewhere.
    # Candidates: StateGroup attenuations, RTPC bindings or CAkBus volumes.
    # None of those are reachable from a simple AkPropBundle scan.
    # We deliberately do NOT expose volume editing for these types to avoid corrupting the bnk.
    return out


def _scan_bnk_music_objects(
    content: bytes, bnk_abs_offset_in_pck: int
) -> List[dict]:
    out: List[dict] = []
    for hs, hsz in _find_hirc_sections(content):
        se = hs + hsz
        if hs + 4 > se:
            continue
        n_obj = struct.unpack_from("<I", content, hs)[0]
        op = hs + 4
        for _ in range(n_obj):
            if op + 5 > se:
                break
            ot = content[op]
            osz = struct.unpack_from("<I", content, op + 1)[0]
            ds = op + 5
            de = ds + osz
            if de > len(content):
                break
            if ot in MUSIC_HIRC_TYPES:
                if ot == HIRC_TYPE_MUSIC_TRACK:
                    parsed = _parse_music_track_fields(
                        content, ds, de, bnk_abs_offset_in_pck
                    )
                else:
                    parsed = _parse_music_object_basic(ot, content, ds, de)
                if parsed is not None:
                    out.append(parsed)
            op = de

    # Second pass: lift AkPropBundle Volume offsets via XXAR's HIRC patcher.
    # Single call with all source_ids.
    # Then attribute each VolumePatchInfo to its owning MusicTrack.
    # Match is done by checking which track's body range contains volume_value_offset.
    # Multiple tracks can share the same source_id but each carries its own AkPropBundle.
    # Per-source dict-mapping was wrong.
    all_source_ids: set = set()
    for o in out:
        if o.get("type") == "MusicTrack":
            for s in o.get("sources", []):
                all_source_ids.add(s["source_id"])
    if not all_source_ids:
        for o in out:
            o.pop("_ds_local", None)
            o.pop("_de_local", None)
        return out
    try:
        targets = scan_bank_for_patch_targets(content, all_source_ids)
    except Exception:
        for o in out:
            o.pop("_ds_local", None)
            o.pop("_de_local", None)
        return out

    # Build a sorted index of (ds_local, de_local, track_dict) tuples.
    # Used for O(log N) lookup of the owning track per volume_value_offset.
    track_ranges = []
    for o in out:
        if o.get("type") != "MusicTrack":
            continue
        ds_l = o.get("_ds_local")
        de_l = o.get("_de_local")
        if ds_l is not None and de_l is not None:
            track_ranges.append((ds_l, de_l, o))
    track_ranges.sort(key=lambda t: t[0])

    def _find_owner(off):
        # Linear-ish scan; ranges are non-overlapping and sorted by start.
        # For typical bnks (hundreds of tracks) this is plenty fast.
        for ds_l, de_l, owner in track_ranges:
            if ds_l <= off < de_l:
                return owner
            if ds_l > off:
                return None
        return None

    seen_track_ids = set()
    for vp in targets.volume_patches:
        if not vp.has_existing_volume:
            continue
        owner = _find_owner(vp.volume_value_offset)
        if owner is None:
            continue
        if owner["obj_id"] in seen_track_ids:
            continue  # one volume per track
        seen_track_ids.add(owner["obj_id"])
        vof = vp.volume_value_offset
        if 0 <= vof + 4 <= len(content):
            try:
                owner["volume_db"] = float(
                    struct.unpack_from("<f", content, vof)[0]
                )
                owner["volume_offset_abs"] = bnk_abs_offset_in_pck + vof
                owner["has_volume"] = True
            except Exception:
                pass

    # Strip internal-only fields from the returned dicts.
    for o in out:
        o.pop("_ds_local", None)
        o.pop("_de_local", None)
    return out


def _extract_track_source_ids(content, track_obj_id: int) -> set:
    # Walk HIRC, find MusicTrack with given obj_id, return set of its AkBankSourceData sourceIDs.
    out: set = set()
    for hs, hsz in _find_hirc_sections(content):
        se = hs + hsz
        if hs + 4 > se:
            continue
        n_obj = struct.unpack_from("<I", content, hs)[0]
        op = hs + 4
        for _ in range(n_obj):
            if op + 5 > se:
                break
            ot = content[op]
            osz = struct.unpack_from("<I", content, op + 1)[0]
            ds = op + 5
            de = ds + osz
            if de > len(content):
                break
            if ot == HIRC_TYPE_MUSIC_TRACK and ds + 9 <= de:
                obj_id = struct.unpack_from("<I", content, ds)[0]
                if obj_id == track_obj_id:
                    num_sources = struct.unpack_from("<I", content, ds + 5)[0]
                    if 0 <= num_sources <= 100:
                        p = ds + 9
                        for _ in range(num_sources):
                            if p + _SOURCE_DATA_SIZE > de:
                                break
                            out.add(struct.unpack_from(
                                "<I", content, p + _SOURCE_ID_OFFSET_IN_SOURCE
                            )[0])
                            p += _SOURCE_DATA_SIZE
                    return out
            op = de
    return out


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
                    n_music = sum(1 for _ in _iter_music_types_in_content(content))
                    if n_music == 0:
                        continue
                    result.append({
                        "pck_name": pck_path.name,
                        "pck_path": str(pck_path),
                        "bnk_id": binfo["id"],
                        "bnk_size": binfo["size"],
                        "music_object_count": n_music,
                        "is_override": is_override,
                    })
            if i % 8 == 0 or i == total:
                self.progress.emit(
                    f"Scanned {i}/{total} pcks, {len(result)} bnks with music HIRC..."
                )
        result.sort(key=lambda r: (_natural_pck_key(r["pck_name"]), r["bnk_id"]))
        return result


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

    def __init__(self):
        super().__init__()
        self._loader: Optional[BnkListLoaderWorker] = None

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
        # Drop bnk list state. Called on game switch.
        logger.info("[HIRC Editor] Unloading all bnks (active-game change)")
        self._cancel_loader()
        self.bnkListReady.emit([])
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
        from fnmatch import fnmatch
        from src.core.game_registry import get_game
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

        import os as _os
        _os.replace(str(tmp_pck), str(target_pck))
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
        self.bnkListReady.emit(data)

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
                return _scan_bnk_music_objects(content, binfo["offset"])
        raise KeyError(f"bnk_id {bnk_id} not in {pck_name}")

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
        # Diagnostic: dump volume bytes for every track in the touched bnk.
        # Used to correlate any volume drift with this source patch.
        self._dump_volume_diag(target_pck, "after source_id patch")
        self.statusUpdate.emit(
            f"Patched {pck_name} @{abs_offset}: {old_wem} -> {new_wem}"
        )

    def _dump_volume_diag(self, pck_path: Path, tag: str):
        # For each MusicTrack in each bnk of the pck, log obj_id + volume_value_offset + raw bytes + parsed dB.
        # Use to track unexpected volume drift across patches.
        try:
            indexer = PCKIndexer(str(pck_path))
            indexer.build_index()
        except Exception as e:
            logger.warning(f"[HIRC Editor-diag] index failed: {e}")
            return
        with open(pck_path, "rb") as f:
            for binfo in indexer.index_data["banks"]:
                f.seek(binfo["offset"])
                content = f.read(binfo["size"])
                # Collect all music track source ids.
                sids: set = set()
                for hs, hsz in _find_hirc_sections(content):
                    se = hs + hsz
                    n_obj = struct.unpack_from("<I", content, hs)[0]
                    op = hs + 4
                    for _ in range(n_obj):
                        if op + 5 > se:
                            break
                        ot = content[op]
                        osz = struct.unpack_from("<I", content, op + 1)[0]
                        ds = op + 5
                        de = ds + osz
                        if de > len(content):
                            break
                        if ot == HIRC_TYPE_MUSIC_TRACK and ds + 9 <= de:
                            ns = struct.unpack_from("<I", content, ds + 5)[0]
                            if 0 <= ns <= 100:
                                p = ds + 9
                                for _ in range(ns):
                                    if p + _SOURCE_DATA_SIZE > de:
                                        break
                                    sids.add(struct.unpack_from(
                                        "<I", content,
                                        p + _SOURCE_ID_OFFSET_IN_SOURCE)[0])
                                    p += _SOURCE_DATA_SIZE
                        op = de
                if not sids:
                    continue
                try:
                    targets = scan_bank_for_patch_targets(content, sids)
                except Exception:
                    continue
                # Group volume patches per (obj_id ~ source_id since ours mirrors).
                seen_offsets = set()
                for vp in targets.volume_patches:
                    if not vp.has_existing_volume:
                        continue
                    if vp.volume_value_offset in seen_offsets:
                        continue
                    seen_offsets.add(vp.volume_value_offset)
                    if 0 <= vp.volume_value_offset + 4 <= len(content):
                        bts = bytes(content[vp.volume_value_offset:
                                            vp.volume_value_offset + 4])
                        try:
                            val = struct.unpack("<f", bts)[0]
                        except Exception:
                            val = float("nan")
                        logger.info(
                            f"[HIRC Editor-diag {tag}] bnk={binfo['id']} "
                            f"src={vp.source_id} vol_off={vp.volume_value_offset} "
                            f"bytes={bts.hex(' ')} dB={val:.4f}"
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

        # ── diagnostic: snapshot volume bytes for ALL music tracks ──
        all_sids = set()
        for hs, hsz in _find_hirc_sections(bnk_content):
            se = hs + hsz
            n_obj = struct.unpack_from("<I", bnk_content, hs)[0]
            op = hs + 4
            for _ in range(n_obj):
                if op + 5 > se:
                    break
                ot = bnk_content[op]
                osz = struct.unpack_from("<I", bnk_content, op + 1)[0]
                ds = op + 5
                de = ds + osz
                if de > len(bnk_content):
                    break
                if ot == HIRC_TYPE_MUSIC_TRACK and ds + 9 <= de:
                    n_src = struct.unpack_from("<I", bnk_content, ds + 5)[0]
                    if 0 <= n_src <= 100:
                        psid = ds + 9
                        for _ in range(n_src):
                            if psid + _SOURCE_DATA_SIZE > de:
                                break
                            all_sids.add(struct.unpack_from(
                                "<I", bnk_content, psid + _SOURCE_ID_OFFSET_IN_SOURCE)[0])
                            psid += _SOURCE_DATA_SIZE
                op = de
        try:
            full_targets = scan_bank_for_patch_targets(bnk_content, all_sids)
            before_vols = {}
            for vp in full_targets.volume_patches:
                if vp.has_existing_volume:
                    bts = bytes(bnk_content[vp.volume_value_offset:
                                            vp.volume_value_offset + 4])
                    before_vols[vp.source_id] = (vp.volume_value_offset, bts)
        except Exception:
            before_vols = {}

        result = apply_duration_patches(bnk_content, targets, duration_map)

        # Diff after patch.
        try:
            full_targets2 = scan_bank_for_patch_targets(bnk_content, all_sids)
            for vp in full_targets2.volume_patches:
                if not vp.has_existing_volume:
                    continue
                aft = bytes(bnk_content[vp.volume_value_offset:
                                        vp.volume_value_offset + 4])
                bef = before_vols.get(vp.source_id)
                if bef is not None and bef[1] != aft:
                    logger.warning(
                        f"[HIRC Editor] VOLUME DRIFT for source {vp.source_id} "
                        f"@offset {vp.volume_value_offset}: "
                        f"before={bef[1].hex(' ')} after={aft.hex(' ')}"
                    )
        except Exception:
            pass
        # ── end diagnostic ──

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
        from src.core.config_manager import get_settings_file
        settings_file = get_settings_file()
        if not settings_file.exists():
            return {}
        try:
            return json.loads(settings_file.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _audio_settings_keys(self) -> Tuple[str, str]:
        from src.core.game_registry import get_audio_settings_keys
        return get_audio_settings_keys(self._current_game_id())

    def _current_game_id(self) -> str:
        from src.core.game_registry import DEFAULT_GAME_ID
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
