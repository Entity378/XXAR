import re
import shutil
import struct
from pathlib import Path

from PyQt5.QtCore import QCoreApplication

from src.core.game_registry import get_game
from src.wwise.hirc_patcher import (
    apply_duration_patches,
    apply_volume_patches,
    scan_bank_for_patch_targets,
)
from src.core.logger import get_logger
logger = get_logger(__name__)



def _natural_sort_key(value):
    text = str(value or "")
    parts = re.split(r"(\d+)", text.lower())
    return [int(part) if part.isdigit() else part for part in parts]


TITLESCREEN_FOLDER_KEY = "__Titlescreen__"
TITLESCREEN_FOLDER_LABEL = "Title Screen"


class BaseBrowserHandler:
    game_id = "zzz"
    LOOP_POINT_MODES = {"auto", "manual", "disabled"}
    loop_point_patching_supported = None

    def __init__(self, bridge, game_id=None, status_callback=None):
        self.bridge = bridge
        self.game_id = game_id or self.game_id
        self.game = get_game(self.game_id)
        self._status_callback = status_callback

    def _reset_bridge_state(self, data_folder):
        b = self.bridge
        b.game_mode = self.game.id
        b.game_data_name = self.game.data_dir_name
        b._set_active_pck_filter(None, "")
        b._invalidate_caches()
        b._item_data.clear()
        b._pck_loaded.clear()
        b._bnk_loaded.clear()
        b.game_root_dir = data_folder

    def _emit_missing_audio_folder_error(self, folder):
        self.bridge.errorOccurred.emit(
            QCoreApplication.translate("Application", "Invalid Directory"),
            QCoreApplication.translate(
                "Application", "Could not find audio folder at:\n%1"
            ).replace("%1", str(folder)),
        )

    def _emit_no_pck_error(self, folder):
        self.bridge.errorOccurred.emit(
            QCoreApplication.translate("Application", "No Audio Files"),
            QCoreApplication.translate(
                "Application", "No PCK files found in:\n%1"
            ).replace("%1", str(folder)),
        )

    def scan_language_folders(self, data_folder):
        b = self.bridge
        self._reset_bridge_state(data_folder)

        audio_root = data_folder.joinpath(*self.game.game_audio_subpath)
        if not audio_root.exists():
            self._emit_missing_audio_folder_error(audio_root)
            return

        b._audio_root = audio_root
        b.language_folders = {}
        language_mapping = dict(self.game.language_folders)
        special_dirs = set(self.game.special_audio_dirs or ())
        known_dirs = set(language_mapping) | special_dirs
        include_all_subdirs = not known_dirs

        pck_files = list(audio_root.glob("*.pck"))
        if pck_files:
            b.language_folders["Full"] = {
                "path": audio_root,
                "friendly_name": self.game.audio_root_friendly_name,
                "pck_count": len(pck_files),
            }

        for subfolder in audio_root.iterdir():
            if not subfolder.is_dir():
                continue
            if not include_all_subdirs and subfolder.name not in known_dirs:
                continue
            pck_files = list(subfolder.glob("*.pck"))
            if not pck_files:
                continue
            b.language_folders[subfolder.name] = {
                "path": subfolder,
                "friendly_name": language_mapping.get(subfolder.name, subfolder.name),
                "pck_count": len(pck_files),
            }

        persistent_root = data_folder.joinpath(*self.game.persistent_audio_subpath)
        if persistent_root.exists():
            for subfolder in persistent_root.iterdir():
                if not subfolder.is_dir():
                    continue
                if not include_all_subdirs and subfolder.name not in known_dirs:
                    continue
                if subfolder.name in b.language_folders:
                    continue
                pck_files = list(subfolder.glob("*.pck"))
                if not pck_files:
                    continue
                b.language_folders[subfolder.name] = {
                    "path": subfolder,
                    "friendly_name": language_mapping.get(subfolder.name, subfolder.name),
                    "pck_count": len(pck_files),
                }

        titlescreen_pcks = self._find_titlescreen_pcks(audio_root)
        if titlescreen_pcks:
            b.language_folders[TITLESCREEN_FOLDER_KEY] = {
                "path": audio_root / TITLESCREEN_FOLDER_KEY,
                "friendly_name": TITLESCREEN_FOLDER_LABEL,
                "pck_count": len(titlescreen_pcks),
                "pck_files": list(titlescreen_pcks),
            }

        if not b.language_folders:
            self._emit_no_pck_error(audio_root)
            return

        tabs = []
        for folder_name in self._ordered_folder_keys():
            info = b.language_folders[folder_name]
            tabs.append(f"{info['friendly_name']} ({info['pck_count']})")

        b.languageTabsReady.emit(tabs)
        if self.game.check_streaming_pairing:
            b._check_missing_streaming_pcks(audio_root)
        self.load_language_tab(0)

    def load_language_tab(self, index):
        b = self.bridge
        ordered = self._ordered_folder_keys()
        if index < 0 or index >= len(ordered):
            return

        folder_name = ordered[index]
        b.current_language_folder = folder_name
        folder_path = b.language_folders[folder_name]["path"]
        b._set_active_pck_filter(None, "")
        b._load_pck_files(folder_path)

    def _ordered_folder_keys(self):
        priority = dict(self.game.subfolder_sort_priority)

        def sort_key(name):
            if name == TITLESCREEN_FOLDER_KEY:
                return (2, 999, str(name).lower())
            if name == "Full":
                return (0, 0, str(name).lower())
            return (1, priority.get(name, 99), str(name).lower())

        return sorted(self.bridge.language_folders.keys(), key=sort_key)

    def collect_pck_files(self, directory):
        if self.bridge:
            current = getattr(self.bridge, "current_language_folder", None)
            info = (getattr(self.bridge, "language_folders", None) or {}).get(current) or {}
            explicit = info.get("pck_files")
            if explicit:
                return list(explicit)
        return sorted(Path(directory).glob("*.pck"), key=lambda p: _natural_sort_key(p.name))

    def include_pck_file(
        self,
        pck_file,
        current_language_folder,
        merge_wem_enabled,
        hide_useless_pck_enabled,
    ):
        if current_language_folder == TITLESCREEN_FOLDER_KEY:
            return True

        if pck_file.name in self.game.protected_pcks:
            return False

        if merge_wem_enabled and str(pck_file.name).startswith(
            self.game.streamed_pck_prefix
        ):
            return False

        non_language_tabs = set(self.game.non_language_tabs or ("Full", "Common"))
        is_language_folder = current_language_folder not in non_language_tabs
        if hide_useless_pck_enabled and is_language_folder:
            if not str(pck_file.name).startswith(self.game.soundbank_pck_filter_prefix):
                return False
        return True

    @staticmethod
    def format_pck_display_name(pck_file, directory):
        return pck_file.name

    @staticmethod
    def should_list_direct_wem(merge_wem_enabled):
        return not merge_wem_enabled

    @staticmethod
    def should_skip_persistent_cleanup_folder(lang_folder, pck_count):
        return False

    @staticmethod
    def restore_persistent_originals(persistent_path, progress_callback=None, vo_backup_mode="local"):
        # Subclass hook for games with VO restoration (currently HSR only).
        return False

    def _emit_status(self, message):
        if not message:
            return
        if callable(self._status_callback):
            try:
                self._status_callback(str(message))
            except Exception:
                pass
            return
        if self.bridge and hasattr(self.bridge, "statusUpdate"):
            try:
                self.bridge.statusUpdate.emit(str(message))
            except Exception:
                pass

    def _loop_point_supported(self):
        if self.loop_point_patching_supported is not None:
            return bool(self.loop_point_patching_supported)
        return bool(getattr(self.game, "loop_point_patching_supported", False))

    def enrich_change_entry(self, pck_filename, tracker_key, repl_info, entry):
        if not self._loop_point_supported():
            return
        if not self.is_loop_entry_applicable(pck_filename, repl_info):
            return

        suggested_ms = self._get_suggested_manual_ms(repl_info)
        entry["loopPointEditable"] = True
        entry["loopPointMode"] = self.normalize_loop_mode(
            repl_info.get("loop_point_mode", "auto")
        )
        entry["loopPointManualMs"] = self.normalize_loop_manual_ms(
            repl_info.get("loop_point_manual_ms", 0)
        )
        entry["loopPointSuggestedMs"] = suggested_ms
        entry["volumeEditable"] = True
        entry["volumeEnabled"] = bool(repl_info.get("volume_enabled", True))
        entry["volumeDb"] = self.normalize_volume_db(
            repl_info.get("volume_db", 0.0)
        )

    @classmethod
    def is_loop_entry_applicable(cls, pck_filename, repl_info):
        file_type = str((repl_info or {}).get("file_type", "")).lower()
        return file_type in ("wem", "bnk")

    @classmethod
    def normalize_loop_mode(cls, mode):
        normalized = str(mode or "").strip().lower()
        if normalized not in cls.LOOP_POINT_MODES:
            return "auto"
        return normalized

    @staticmethod
    def normalize_loop_manual_ms(duration_ms):
        try:
            value = int(duration_ms)
        except Exception:
            value = 0
        return max(0, value)

    @staticmethod
    def normalize_volume_db(volume_db):
        try:
            value = round(float(volume_db), 1)
        except Exception:
            value = 0.0
        return max(-96.0, min(24.0, value))

    @staticmethod
    def _extract_tracker_file_id(tracker_key):
        key_text = str(tracker_key or "").strip()
        if "|" in key_text:
            key_text = key_text.split("|")[-1]
        try:
            return int(key_text)
        except Exception:
            return None

    def _get_suggested_manual_ms(self, repl_info):
        wem_path = Path(str((repl_info or {}).get("wem_path", "")))
        if not wem_path.exists():
            return 0
        duration_ms = self._get_wem_duration_ms(wem_path)
        if duration_ms is None:
            return 0
        return self.normalize_loop_manual_ms(round(duration_ms))

    @staticmethod
    def _get_wem_duration_ms(wem_path):
        try:
            wem_bytes = Path(wem_path).read_bytes()
            if len(wem_bytes) < 12:
                return None
            if wem_bytes[:4] != b"RIFF" or wem_bytes[8:12] != b"WAVE":
                return None

            pos = 12
            fmt_tag = 0
            sample_rate = 0
            avg_bytes = 0
            channels = 0
            bits = 0
            total_samples = 0
            data_size = 0

            while pos <= len(wem_bytes) - 8:
                chunk_id = wem_bytes[pos : pos + 4]
                chunk_size = struct.unpack_from("<I", wem_bytes, pos + 4)[0]
                chunk_data = pos + 8
                chunk_end = min(chunk_data + chunk_size, len(wem_bytes))

                if (
                    chunk_id == b"fmt "
                    and chunk_size >= 16
                    and chunk_end >= chunk_data + 16
                ):
                    fmt_tag = struct.unpack_from("<H", wem_bytes, chunk_data)[0]
                    channels = struct.unpack_from("<H", wem_bytes, chunk_data + 2)[0]
                    sample_rate = struct.unpack_from("<I", wem_bytes, chunk_data + 4)[0]
                    avg_bytes = struct.unpack_from("<I", wem_bytes, chunk_data + 8)[0]
                    bits = struct.unpack_from("<H", wem_bytes, chunk_data + 14)[0]
                    if (
                        fmt_tag == 0xFFFF
                        and chunk_size >= 0x1C
                        and chunk_end >= chunk_data + 0x1C + 4
                    ):
                        total_samples = struct.unpack_from(
                            "<I", wem_bytes, chunk_data + 0x18
                        )[0]

                elif (
                    chunk_id == b"fact"
                    and chunk_size >= 4
                    and chunk_end >= chunk_data + 4
                ):
                    if total_samples <= 0:
                        total_samples = struct.unpack_from("<I", wem_bytes, chunk_data)[0]

                elif (
                    chunk_id == b"vorb"
                    and chunk_size >= 4
                    and chunk_end >= chunk_data + 4
                ):
                    if total_samples <= 0:
                        total_samples = struct.unpack_from("<I", wem_bytes, chunk_data)[0]

                elif chunk_id == b"data":
                    data_size = max(data_size, max(chunk_end - chunk_data, 0))
                    if fmt_tag == 1 and sample_rate > 0 and total_samples <= 0:
                        frame_size = max(bits // 8, 1) * max(channels, 1)
                        if frame_size > 0:
                            total_samples = data_size // frame_size

                pos = chunk_data + chunk_size
                if chunk_size % 2:
                    pos += 1

            if sample_rate > 0 and total_samples > 0:
                return (float(total_samples) / float(sample_rate)) * 1000.0

            if sample_rate > 0 and avg_bytes > 0:
                size_for_avg = data_size if data_size > 0 else len(wem_bytes)
                return (float(size_for_avg) / float(avg_bytes)) * 1000.0
        except Exception:
            return None
        return None

    def apply_post_pack_steps(self, replacements):
        if not self.game.loop_point_patching_supported:
            return {"patched_files": 0, "patched_ids": 0}

        duration_ms_by_track = self._collect_loop_patch_targets(replacements)
        volume_db_by_track = self._collect_volume_patch_targets(replacements)
        if not duration_ms_by_track and not volume_db_by_track:
            return {"patched_files": 0, "patched_ids": 0}

        game_root = (
            Path(self.bridge.game_root_dir)
            if self.bridge and self.bridge.game_root_dir
            else None
        )

        streaming_root = game_root.joinpath(*self.game.game_audio_subpath) if game_root else None
        persistent_root = game_root.joinpath(*self.game.persistent_audio_subpath) if game_root else None

        if not streaming_root or not streaming_root.exists():
            raise FileNotFoundError(
                QCoreApplication.translate(
                    "Application",
                    "Could not locate Streaming AudioAssets folder.",
                )
            )
        
        if not persistent_root or not persistent_root.exists():
            raise FileNotFoundError(
                QCoreApplication.translate(
                    "Application",
                    "Could not locate Persistent AudioAssets folder.",
                )
            )

        bank_files = self._find_bank_pck_files(streaming_root)
        titlescreen_pcks = self._find_titlescreen_pcks(streaming_root)
        if not bank_files and not titlescreen_pcks:
            return {"patched_files": 0, "patched_ids": 0}

        source_ids = set(duration_ms_by_track.keys()) | set(volume_db_by_track.keys())
        patched_file_count = 0
        patched_track_ids = set()

        for bank_source in bank_files:
            rel_parent = bank_source.parent.relative_to(streaming_root)
            bank_target_dir = persistent_root / rel_parent
            bank_target_dir.mkdir(parents=True, exist_ok=True)
            bank_target = bank_target_dir / bank_source.name

            scan_source = bank_target if bank_target.exists() else bank_source
            try:
                raw = scan_source.read_bytes()
            except Exception:
                continue

            did_patch = self._patch_bank_content(
                raw, bank_target, scan_source, source_ids,
                duration_ms_by_track, volume_db_by_track,
                patched_track_ids,
            )
            if did_patch:
                patched_file_count += 1


        for titlescreen_pck in titlescreen_pcks:
            titlescreen_target = self._persistent_overlay_path(
                titlescreen_pck, streaming_root, persistent_root
            )
            titlescreen_target.parent.mkdir(parents=True, exist_ok=True)

            scan_source = titlescreen_target if titlescreen_target.exists() else titlescreen_pck
            try:
                raw = scan_source.read_bytes()
            except Exception:
                continue

            did_patch = self._patch_bank_content(
                raw, titlescreen_target, scan_source, source_ids,
                duration_ms_by_track, volume_db_by_track,
                patched_track_ids,
            )
            if did_patch:
                patched_file_count += 1

        # Scan override PCKs for HIRC patching too
        for override_pck in self._find_override_pcks(persistent_root):
            try:
                override_pck.chmod(0o644)
                raw = override_pck.read_bytes()
            except Exception:
                continue
            did_patch = self._patch_bank_content(
                raw, override_pck, override_pck, source_ids,
                duration_ms_by_track, volume_db_by_track,
                patched_track_ids,
            )
            if did_patch:
                patched_file_count += 1

        result = {
            "patched_files": patched_file_count,
            "patched_ids": len(patched_track_ids),
        }
        if result["patched_files"] > 0:
            label = self.game.short_label
            self._emit_status(
                QCoreApplication.translate(
                    "Application",
                    "%3 loop points patched in %1 bank file(s) for %2 track ID(s).",
                )
                .replace("%1", str(result["patched_files"]))
                .replace("%2", str(result["patched_ids"]))
                .replace("%3", label)
            )
        return result

    @classmethod
    def apply_post_mod_manager_steps(
        cls,
        replacements,
        streaming_root,
        persistent_root,
        resolved_pck_names=None,
        status_callback=None,
    ):
        handler = cls(bridge=None, status_callback=status_callback)
        if not handler.game.loop_point_patching_supported:
            return {"patched_files": 0, "patched_ids": 0}

        duration_ms_by_track = handler._collect_loop_patch_targets(replacements)
        volume_db_by_track = handler._collect_volume_patch_targets(replacements)
        if not duration_ms_by_track and not volume_db_by_track:
            return {"patched_files": 0, "patched_ids": 0}

        streaming_root = Path(streaming_root) if streaming_root else None
        persistent_root = Path(persistent_root) if persistent_root else None
        if not streaming_root or not streaming_root.exists():
            raise FileNotFoundError(
                QCoreApplication.translate(
                    "Application",
                    "Could not locate Streaming AudioAssets folder.",
                )
            )
        if not persistent_root:
            raise FileNotFoundError(
                QCoreApplication.translate(
                    "Application",
                    "Could not locate Persistent AudioAssets folder.",
                )
            )

        resolved_names = {
            str(Path(name).name).lower()
            for name in (resolved_pck_names or [])
            if str(name).strip()
        }

        bank_files = handler._find_bank_pck_files(streaming_root)
        titlescreen_pcks = handler._find_titlescreen_pcks(streaming_root)
        if not bank_files and not titlescreen_pcks:
            return {"patched_files": 0, "patched_ids": 0}

        source_ids = set(duration_ms_by_track.keys()) | set(volume_db_by_track.keys())
        patched_file_count = 0
        patched_track_ids = set()
        volume_patched_count = 0

        for bank_source in bank_files:
            try:
                rel_parent = bank_source.parent.relative_to(streaming_root)
            except Exception:
                rel_parent = Path()

            bank_target_dir = persistent_root / rel_parent
            bank_target_dir.mkdir(parents=True, exist_ok=True)
            bank_target = bank_target_dir / bank_source.name

            if bank_target.exists() and bank_source.name.lower() in resolved_names:
                base_file = bank_target
            else:
                base_file = bank_source

            try:
                raw = base_file.read_bytes()
            except Exception:
                continue

            did_patch = handler._patch_bank_content(
                raw, bank_target, base_file, source_ids,
                duration_ms_by_track, volume_db_by_track,
                patched_track_ids,
            )
            if did_patch:
                patched_file_count += 1

        for titlescreen_pck in titlescreen_pcks:
            titlescreen_target = handler._persistent_overlay_path(
                titlescreen_pck, streaming_root, persistent_root
            )
            titlescreen_target.parent.mkdir(parents=True, exist_ok=True)

            if titlescreen_target.exists() and titlescreen_pck.name.lower() in resolved_names:
                base_file = titlescreen_target
            else:
                base_file = titlescreen_pck

            try:
                raw = base_file.read_bytes()
            except Exception:
                continue

            did_patch = handler._patch_bank_content(
                raw, titlescreen_target, base_file, source_ids,
                duration_ms_by_track, volume_db_by_track,
                patched_track_ids,
            )
            if did_patch:
                patched_file_count += 1

        # Scan override PCKs for HIRC patching too
        for override_pck in handler._find_override_pcks(persistent_root):
            try:
                override_pck.chmod(0o644)
                raw = override_pck.read_bytes()
            except Exception:
                continue

            did_patch = handler._patch_bank_content(
                raw, override_pck, override_pck, source_ids,
                duration_ms_by_track, volume_db_by_track,
                patched_track_ids,
            )
            if did_patch:
                patched_file_count += 1

        result = {
            "patched_files": patched_file_count,
            "patched_ids": len(patched_track_ids),
        }
        if result["patched_files"] > 0:
            label = handler.game.short_label
            handler._emit_status(
                QCoreApplication.translate(
                    "Application",
                    "%3 HIRC patched in %1 bank file(s) for %2 track ID(s).",
                )
                .replace("%1", str(result["patched_files"]))
                .replace("%2", str(result["patched_ids"]))
                .replace("%3", label)
            )
        return result

    @staticmethod
    def _patch_bank_content(
        raw, target_path, base_file, source_ids,
        duration_ms_by_track, volume_db_by_track,
        patched_track_ids,
    ):
        # Patch in-memory on a bytearray so volume insertions don't shift
        # duration offsets mid-pass; single write at the end.
        targets = scan_bank_for_patch_targets(raw, source_ids)
        has_duration = targets.tracks or targets.segments
        has_volume = targets.volume_patches and volume_db_by_track
        if not has_duration and not has_volume:
            return False

        logger.info(f"[HIRC Patch] {target_path.name}: {len(targets.tracks)} track(s), {len(targets.segments)} seg(s), {len(targets.volume_patches)} vol target(s), has_volume={has_volume}")

        content = bytearray(raw)
        original_size = len(content)

        # Volume patches first (may insert bytes and shift offsets).
        vol_result = {"patched": 0, "inserted": 0, "total_shift": 0}
        if has_volume:
            vol_result = apply_volume_patches(
                content, targets.volume_patches, volume_db_by_track,
            )
            logger.info(f"[HIRC Patch] Volume: {vol_result['patched']} in-place, {vol_result['inserted']} inserted, size {original_size} -> {len(content)}")

        # If volume insertions shifted bytes, re-scan for duration offsets.
        if vol_result["inserted"] > 0 and has_duration:
            targets = scan_bank_for_patch_targets(bytes(content), source_ids)

        dur_result = {"patched_offsets": 0, "patched_source_ids": set()}
        if has_duration and duration_ms_by_track:
            dur_result = apply_duration_patches(
                content, targets, duration_ms_by_track,
            )
            logger.info(f"[HIRC Patch] Duration: {dur_result['patched_offsets']} offset(s), {len(dur_result['patched_source_ids'])} source(s)")

        if vol_result["patched"] + vol_result["inserted"] + dur_result["patched_offsets"] <= 0:
            return False

        if base_file != target_path:
            import shutil
            shutil.copy2(base_file, target_path)

        # Some source PCKs (notably Minimum.pck) are delivered with the
        # read-only attribute set; shutil.copy2 preserves it and write_bytes
        # would then raise PermissionError.
        try:
            target_path.chmod(0o644)
        except Exception:
            pass

        target_path.write_bytes(content)
        patched_track_ids.update(dur_result["patched_source_ids"])
        logger.info(f"[HIRC Patch] Written {len(content)} bytes to {target_path}")
        return True

    def _find_bank_pck_files(self, audio_root):
        prefix = self.game.soundbank_pck_prefix.lower()
        return [
            p
            for p in sorted(
                audio_root.rglob("*.pck"), key=lambda p: _natural_sort_key(p.name)
            )
            if p.name.lower().startswith(prefix)
        ]

    def _find_titlescreen_pcks(self, audio_root):
        # Some games keep the title-screen PCK in a sibling folder of streaming_root
        # (e.g. ZZZ stores Minimum.pck under Audio/Windows/Min/ while streaming_root is Full/).
        # Scan streaming_root + its siblings to cover both layouts.
        names = getattr(self.game, "titlescreen_pcks", ())
        if not names or not audio_root:
            return []
        name_set = {n.lower() for n in names}
        audio_root = Path(audio_root)

        search_roots = [audio_root]
        parent = audio_root.parent
        if parent.exists() and parent != audio_root:
            for sibling in parent.iterdir():
                if sibling.is_dir() and sibling.resolve() != audio_root.resolve():
                    search_roots.append(sibling)

        found = []
        seen = set()
        for root in search_roots:
            for p in root.rglob("*.pck"):
                if p.name.lower() not in name_set:
                    continue
                key = str(p.resolve()).lower()
                if key in seen:
                    continue
                seen.add(key)
                found.append(p)
        return sorted(found, key=lambda p: _natural_sort_key(p.name))

    @staticmethod
    def _persistent_overlay_path(src_pck, streaming_root, persistent_root):
        # Mirror a source PCK path into the persistent overlay tree.
        # Works whether src_pck is under streaming_root or in a sibling folder
        # (e.g. ZZZ's Min/Minimum.pck vs Full/ streaming_root) by swapping
        # the StreamingAssets segment with the Persistent equivalent.
        src_pck = Path(src_pck)
        streaming_root = Path(streaming_root)
        persistent_root = Path(persistent_root)
        try:
            rel = src_pck.relative_to(streaming_root)
            return persistent_root / rel
        except Exception:
            pass
        src_parts = src_pck.parts
        for i, part in enumerate(src_parts):
            if part == "StreamingAssets":
                return Path(*src_parts[:i], "Persistent", *src_parts[i + 1:])
        return persistent_root / src_pck.name

    def _find_override_pcks(self, persistent_root):
        if not persistent_root or not Path(persistent_root).exists():
            return []
        return [
            p
            for p in Path(persistent_root).rglob("*.pck")
            if p.name in self.game.protected_pcks
        ]

    def _collect_loop_patch_targets(self, replacements):
        duration_ms_by_track = {}
        missing_durations = []
        invalid_manual = []

        for pck_filename, files in (replacements or {}).items():
            for tracker_key, repl_info in (files or {}).items():
                if not self.is_loop_entry_applicable(pck_filename, repl_info):
                    continue

                track_id = self._extract_tracker_file_id(tracker_key)
                if track_id is None:
                    continue

                loop_mode = self.normalize_loop_mode(
                    repl_info.get("loop_point_mode", "auto")
                )
                if loop_mode == "disabled":
                    continue

                if loop_mode == "manual":
                    manual_ms = self.normalize_loop_manual_ms(
                        repl_info.get("loop_point_manual_ms", 0)
                    )
                    if manual_ms <= 0:
                        manual_ms = self._get_suggested_manual_ms(repl_info)
                        if manual_ms <= 0:
                            invalid_manual.append(str(track_id))
                            continue
                    duration_ms_by_track[track_id] = float(manual_ms)
                    continue

                wem_path = Path(str(repl_info.get("wem_path", "")))
                if not wem_path.exists():
                    missing_durations.append(str(track_id))
                    continue

                duration_ms = self._get_wem_duration_ms(wem_path)
                if duration_ms is None:
                    missing_durations.append(str(track_id))
                    continue
                duration_ms_by_track[track_id] = float(duration_ms)

        if invalid_manual:
            self._emit_status(
                QCoreApplication.translate(
                    "Application",
                    "Loop point Manual mode ignored for %1 track(s) with invalid manual duration.",
                ).replace("%1", str(len(invalid_manual)))
            )

        if missing_durations:
            unique_missing = list(dict.fromkeys(missing_durations))
            self._emit_status(
                QCoreApplication.translate(
                    "Application",
                    "Could not determine duration for %1 track(s): %2",
                )
                .replace("%1", str(len(unique_missing)))
                .replace("%2", ", ".join(unique_missing[:8]))
            )
        return duration_ms_by_track

    def _collect_volume_patch_targets(self, replacements):
        volume_db_by_track = {}

        for pck_filename, files in (replacements or {}).items():
            for tracker_key, repl_info in (files or {}).items():
                if not self.is_loop_entry_applicable(pck_filename, repl_info):
                    continue

                track_id = self._extract_tracker_file_id(tracker_key)
                if track_id is None:
                    continue

                if not repl_info.get("volume_enabled", True):
                    continue

                volume_db_by_track[track_id] = self.normalize_volume_db(
                    repl_info.get("volume_db", 0.0)
                )

        return volume_db_by_track
