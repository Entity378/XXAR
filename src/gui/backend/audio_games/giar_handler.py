import re
import shutil
import struct
from pathlib import Path

from PyQt5.QtCore import QCoreApplication

from .base_handler import BaseBrowserHandler


def _natural_sort_key(value):
    text = str(value or "")
    parts = re.split(r"(\d+)", text.lower())
    return [int(part) if part.isdigit() else part for part in parts]


def _natural_sorted(values, key=None):
    key_func = key or (lambda x: x)
    return sorted(values, key=lambda item: _natural_sort_key(key_func(item)))


class GIARBrowserHandler(BaseBrowserHandler):
    game_id = "genshin"
    LOOP_POINT_MODES = {"auto", "manual", "disabled"}

    def __init__(self, bridge, status_callback=None):
        super().__init__(bridge, game_id=self.game_id)
        self._status_callback = status_callback
        self._tab_order = []
        self._music_re = re.compile(self.game.music_pck_regex, re.IGNORECASE)
        self._streamed_re = re.compile(self.game.streamed_pck_regex, re.IGNORECASE)
        self._bank_re = re.compile(self.game.bank_pck_regex, re.IGNORECASE)

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

    def scan_language_folders(self, data_folder):
        b = self.bridge
        self._reset_bridge_state(data_folder)

        audio_assets = data_folder.joinpath(*self.game.game_audio_subpath)
        if not audio_assets.exists():
            self._emit_missing_audio_folder_error(audio_assets)
            return

        b._audio_root = audio_assets
        all_pcks = _natural_sorted(
            audio_assets.rglob("*.pck"),
            key=lambda p: str(p.relative_to(audio_assets)).replace("\\", "/"),
        )
        if not all_pcks:
            self._emit_no_pck_error(audio_assets)
            return

        self._tab_order = []
        b.language_folders = {}

        self._add_tab(
            key="music",
            label=QCoreApplication.translate("Application", "Music PCK"),
            audio_assets=audio_assets,
            all_pcks=all_pcks,
            predicate=self._is_music_pck,
        )
        self._add_tab(
            key="streamed",
            label=QCoreApplication.translate("Application", "Streamed PCK"),
            audio_assets=audio_assets,
            all_pcks=all_pcks,
            predicate=self._is_streamed_pck,
        )
        self._add_tab(
            key="banks",
            label=QCoreApplication.translate("Application", "Bank PCK"),
            audio_assets=audio_assets,
            all_pcks=all_pcks,
            predicate=self._is_bank_pck,
        )

        top_dirs = self._collect_top_level_dirs(audio_assets, all_pcks)
        top_dirs_lower = {d.lower(): d for d in top_dirs}
        special_dirs = self.game.special_audio_dirs or ()

        for special_dir in special_dirs:
            actual_dir = top_dirs_lower.get(special_dir.lower())
            if not actual_dir:
                continue
            self._add_tab(
                key=f"dir:{actual_dir.lower()}",
                label=actual_dir,
                audio_assets=audio_assets,
                all_pcks=all_pcks,
                predicate=lambda p, d=actual_dir: self._is_under_top_dir(
                    audio_assets, p, d
                ),
            )

        special_names = {name.lower() for name in special_dirs}
        language_dirs = [d for d in top_dirs if d.lower() not in special_names]
        for lang_dir in _natural_sorted(language_dirs, key=lambda d: d):
            self._add_tab(
                key=f"lang:{lang_dir.lower()}",
                label=QCoreApplication.translate("Application", "Lang: %1").replace(
                    "%1", lang_dir
                ),
                audio_assets=audio_assets,
                all_pcks=all_pcks,
                predicate=lambda p, d=lang_dir: self._is_under_top_dir(
                    audio_assets, p, d
                ),
            )

        if not b.language_folders:
            self._emit_no_pck_error(audio_assets)
            return

        tabs = []
        for key in self._ordered_folder_keys():
            info = b.language_folders[key]
            tabs.append(f"{info['friendly_name']} ({info['pck_count']})")

        b.languageTabsReady.emit(tabs)
        self.load_language_tab(0)

    def load_language_tab(self, index):
        b = self.bridge
        ordered = self._ordered_folder_keys()
        if index < 0 or index >= len(ordered):
            return

        key = ordered[index]
        folder_info = b.language_folders[key]
        b.current_language_folder = key
        predicate = folder_info.get("filter_predicate")
        filter_tag = folder_info.get("filter_tag", key)

        b._set_active_pck_filter(predicate, filter_tag)
        b._load_pck_files(
            folder_info["path"],
            file_filter=predicate,
            filter_tag=filter_tag,
        )

    def _ordered_folder_keys(self):
        return [key for key in self._tab_order if key in self.bridge.language_folders]

    def _is_music_pck(self, path):
        return self._music_re.match(path.name) is not None

    def _is_streamed_pck(self, path):
        return self._streamed_re.match(path.name) is not None

    def _is_bank_pck(self, path):
        return self._bank_re.match(path.name) is not None

    @staticmethod
    def _collect_top_level_dirs(audio_assets, all_pcks):
        dirs = []
        seen = set()
        for p in all_pcks:
            try:
                rel = p.relative_to(audio_assets)
            except Exception:
                continue
            if len(rel.parts) <= 1:
                continue
            top = rel.parts[0]
            key = top.lower()
            if key in seen:
                continue
            seen.add(key)
            dirs.append(top)
        return dirs

    @staticmethod
    def _is_under_top_dir(audio_assets, pck_path, top_dir):
        try:
            rel = pck_path.relative_to(audio_assets)
        except Exception:
            return False
        return len(rel.parts) > 1 and rel.parts[0].lower() == top_dir.lower()

    def _add_tab(self, key, label, audio_assets, all_pcks, predicate):
        matches = [p for p in all_pcks if predicate(p)]
        if not matches:
            return

        self.bridge.language_folders[key] = {
            "path": audio_assets,
            "friendly_name": label,
            "pck_count": len(matches),
            "filter_predicate": predicate,
            "filter_tag": key,
        }
        self._tab_order.append(key)

    @staticmethod
    def collect_pck_files(directory):
        return _natural_sorted(Path(directory).rglob("*.pck"), key=lambda p: p.as_posix())

    @staticmethod
    def include_pck_file(
        pck_file,
        current_language_folder,
        merge_wem_enabled,
        hide_useless_pck_enabled,
    ):
        return True

    @staticmethod
    def format_pck_display_name(pck_file, directory):
        try:
            return str(pck_file.relative_to(directory)).replace("\\", "/")
        except Exception:
            return pck_file.name

    @staticmethod
    def should_list_direct_wem(merge_wem_enabled):
        return True

    def apply_post_pack_steps(self, replacements):
        if not self.game.loop_point_patching_supported:
            return {"patched_files": 0, "patched_ids": 0}

        duration_ms_by_track = self._collect_loop_patch_targets(replacements)
        if not duration_ms_by_track:
            return {"patched_files": 0, "patched_ids": 0}

        streaming_root = Path(self.bridge._audio_root) if self.bridge and self.bridge._audio_root else None
        if not streaming_root or not streaming_root.exists():
            raise FileNotFoundError(
                QCoreApplication.translate(
                    "Application", "Could not locate GI Streaming AudioAssets folder."
                )
            )

        bank_files = [
            pck_file
            for pck_file in _natural_sorted(streaming_root.rglob("*.pck"), key=lambda p: p.as_posix())
            if self._is_bank_pck(pck_file)
        ]

        if not bank_files:
            self._emit_status(
                QCoreApplication.translate(
                    "Application", "No GI Bank PCK files found for loop point patching."
                )
            )
            return {"patched_files": 0, "patched_ids": 0}

        patched_file_count = 0
        patched_track_ids = set()
        track_ids = sorted(duration_ms_by_track.keys())

        for bank_source in bank_files:
            bank_target_dir = Path(
                str(bank_source.parent).replace("StreamingAssets", "Persistent")
            )
            bank_target_dir.mkdir(parents=True, exist_ok=True)
            bank_target = bank_target_dir / bank_source.name

            scan_source = bank_target if bank_target.exists() else bank_source
            try:
                content = scan_source.read_bytes()
            except Exception:
                continue

            offsets_by_track = self._scan_bank_offsets(content, track_ids)
            if not offsets_by_track:
                continue

            if not bank_target.exists():
                shutil.copy2(bank_source, bank_target)
            elif scan_source != bank_target:
                shutil.copy2(scan_source, bank_target)

            patch_result = self._patch_bank_file(
                bank_target, offsets_by_track, duration_ms_by_track
            )
            if patch_result["patched_offsets"] <= 0:
                continue

            patched_file_count += 1
            patched_track_ids.update(patch_result["patched_track_ids"])

        result = {
            "patched_files": patched_file_count,
            "patched_ids": len(patched_track_ids),
        }
        if result["patched_files"] > 0:
            self._emit_status(
                QCoreApplication.translate(
                    "Application",
                    "GI loop points patched in %1 bank file(s) for %2 track ID(s).",
                )
                .replace("%1", str(result["patched_files"]))
                .replace("%2", str(result["patched_ids"]))
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
        if not duration_ms_by_track:
            return {"patched_files": 0, "patched_ids": 0}

        streaming_root = Path(streaming_root) if streaming_root else None
        persistent_root = Path(persistent_root) if persistent_root else None
        if not streaming_root or not streaming_root.exists():
            raise FileNotFoundError(
                QCoreApplication.translate(
                    "Application", "Could not locate GI Streaming AudioAssets folder."
                )
            )
        if not persistent_root:
            raise FileNotFoundError(
                QCoreApplication.translate(
                    "Application", "Could not locate GI Persistent AudioAssets folder."
                )
            )

        resolved_names = {
            str(Path(name).name).lower()
            for name in (resolved_pck_names or [])
            if str(name).strip()
        }

        bank_files = [
            pck_file
            for pck_file in _natural_sorted(streaming_root.rglob("*.pck"), key=lambda p: p.as_posix())
            if handler._is_bank_pck(pck_file)
        ]

        if not bank_files:
            handler._emit_status(
                QCoreApplication.translate(
                    "Application", "No GI Bank PCK files found for loop point patching."
                )
            )
            return {"patched_files": 0, "patched_ids": 0}

        patched_file_count = 0
        patched_track_ids = set()
        track_ids = sorted(duration_ms_by_track.keys())

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
                content = base_file.read_bytes()
            except Exception:
                continue

            offsets_by_track = handler._scan_bank_offsets(content, track_ids)
            if not offsets_by_track:
                continue

            if base_file != bank_target:
                shutil.copy2(base_file, bank_target)

            patch_result = handler._patch_bank_file(
                bank_target, offsets_by_track, duration_ms_by_track
            )
            if patch_result["patched_offsets"] <= 0:
                continue

            patched_file_count += 1
            patched_track_ids.update(patch_result["patched_track_ids"])

        result = {
            "patched_files": patched_file_count,
            "patched_ids": len(patched_track_ids),
        }
        if result["patched_files"] > 0:
            handler._emit_status(
                QCoreApplication.translate(
                    "Application",
                    "GI loop points patched in %1 bank file(s) for %2 track ID(s).",
                )
                .replace("%1", str(result["patched_files"]))
                .replace("%2", str(result["patched_ids"]))
            )
        return result

    @classmethod
    def is_loop_entry_applicable(cls, pck_filename, repl_info):
        if not re.match(r"^[a-z]*music\d+\.pck$", str(pck_filename or ""), re.IGNORECASE):
            return False
        file_type = str((repl_info or {}).get("file_type", "")).lower()
        return file_type == "wem"

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
    def _extract_tracker_file_id(tracker_key):
        key_text = str(tracker_key or "").strip()
        if "|" in key_text:
            key_text = key_text.split("|")[-1]
        try:
            return int(key_text)
        except Exception:
            return None

    @staticmethod
    def tracker_display_file_id(tracker_key):
        key_text = str(tracker_key or "").strip()
        return key_text.split("|")[-1] if "|" in key_text else key_text

    @staticmethod
    def tracker_plain_file_id(tracker_key):
        key_text = str(tracker_key or "").strip()
        return key_text.split("|")[-1] if "|" in key_text else key_text

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

                if chunk_id == b"fmt " and chunk_size >= 16 and chunk_end >= chunk_data + 16:
                    fmt_tag = struct.unpack_from("<H", wem_bytes, chunk_data)[0]
                    channels = struct.unpack_from("<H", wem_bytes, chunk_data + 2)[0]
                    sample_rate = struct.unpack_from("<I", wem_bytes, chunk_data + 4)[0]
                    avg_bytes = struct.unpack_from("<I", wem_bytes, chunk_data + 8)[0]
                    bits = struct.unpack_from("<H", wem_bytes, chunk_data + 14)[0]
                    if fmt_tag == 0xFFFF and chunk_size >= 0x1C and chunk_end >= chunk_data + 0x1C + 4:
                        total_samples = struct.unpack_from("<I", wem_bytes, chunk_data + 0x18)[0]

                elif chunk_id == b"fact" and chunk_size >= 4 and chunk_end >= chunk_data + 4:
                    if total_samples <= 0:
                        total_samples = struct.unpack_from("<I", wem_bytes, chunk_data)[0]

                elif chunk_id == b"vorb" and chunk_size >= 4 and chunk_end >= chunk_data + 4:
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

    @staticmethod
    def _scan_bank_offsets(content, track_ids):
        offsets_by_track = {}
        for track_id in track_ids:
            id_bytes = struct.pack("<I", int(track_id))
            found = []
            pos = -1
            while True:
                pos = content.find(id_bytes, pos + 1)
                if pos == -1:
                    break
                check_pos = pos + 4 + 13
                if (
                    check_pos + 4 <= len(content)
                    and content[check_pos : check_pos + 4] == id_bytes
                ):
                    found.append(check_pos + 4)
            if found:
                offsets_by_track[int(track_id)] = found
        return offsets_by_track

    @staticmethod
    def _patch_bank_file(bank_file_path, offsets_by_track, duration_ms_by_track):
        zero_bytes = b"\x00" * 28
        hex_pattern = b"\x48\xd6\xbb\x5b"
        patched_offsets = 0
        patched_track_ids = set()

        with open(bank_file_path, "r+b") as f:
            for track_id, offsets in offsets_by_track.items():
                duration_ms = duration_ms_by_track.get(int(track_id))
                if duration_ms is None:
                    continue
                duration_bytes = struct.pack("<d", float(duration_ms))

                for offset in offsets:
                    f.seek(offset)
                    existing_block = f.read(36)
                    block_matches = (
                        len(existing_block) >= 36
                        and existing_block[:28] == zero_bytes
                        and existing_block[28:36] == duration_bytes
                    )

                    f.seek(offset)
                    remaining = f.read()
                    pos_in_remaining = remaining.find(hex_pattern)
                    pattern_matches = block_matches
                    if pos_in_remaining != -1:
                        pos = offset + pos_in_remaining

                        f.seek(pos + len(hex_pattern))
                        existing_after_pattern = f.read(8)
                        pattern_matches = pattern_matches and existing_after_pattern == duration_bytes

                        if pos >= 28:
                            f.seek(pos - 28)
                            existing_before_pattern = f.read(8)
                            pattern_matches = pattern_matches and existing_before_pattern == duration_bytes

                    if block_matches and pattern_matches:
                        continue

                    f.seek(offset)
                    f.write(zero_bytes)
                    f.write(duration_bytes)

                    if pos_in_remaining != -1:
                        pos = offset + pos_in_remaining
                        f.seek(pos + len(hex_pattern))
                        f.write(duration_bytes)
                        if pos >= 28:
                            f.seek(pos - 28)
                            f.write(duration_bytes)

                    patched_offsets += 1
                    patched_track_ids.add(int(track_id))

        return {
            "patched_offsets": patched_offsets,
            "patched_track_ids": patched_track_ids,
        }

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
                    "GI loop point Manual mode ignored for %1 track(s) with invalid manual duration.",
                ).replace("%1", str(len(invalid_manual)))
            )

        if missing_durations:
            unique_missing = []
            seen = set()
            for track_id in missing_durations:
                if track_id in seen:
                    continue
                seen.add(track_id)
                unique_missing.append(track_id)

            self._emit_status(
                QCoreApplication.translate(
                    "Application",
                    "Could not determine duration for %1 track(s): %2",
                )
                .replace("%1", str(len(unique_missing)))
                .replace("%2", ", ".join(unique_missing[:8]))
            )
        return duration_ms_by_track
