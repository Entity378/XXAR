import re
import struct
from pathlib import Path

from PyQt5.QtCore import QCoreApplication

from src.game_registry import get_game


def _natural_sort_key(value):
    text = str(value or "")
    parts = re.split(r"(\d+)", text.lower())
    return [int(part) if part.isdigit() else part for part in parts]


class BaseBrowserHandler:
    game_id = "zzz"
    LOOP_POINT_MODES = {"auto", "manual", "disabled"}
    loop_point_patching_supported = None

    def __init__(self, bridge, game_id=None):
        self.bridge = bridge
        self.game_id = game_id or self.game_id
        self.game = get_game(self.game_id)
        self._status_callback = None

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
        return sorted(
            self.bridge.language_folders.keys(),
            key=lambda name: (
                0 if name == "Full" else 1,
                priority.get(name, 99),
                str(name).lower(),
            ),
        )

    @staticmethod
    def collect_pck_files(directory):
        return sorted(Path(directory).glob("*.pck"), key=lambda p: _natural_sort_key(p.name))

    def include_pck_file(
        self,
        pck_file,
        current_language_folder,
        merge_wem_enabled,
        hide_useless_pck_enabled,
    ):
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

    @classmethod
    def is_loop_entry_applicable(cls, pck_filename, repl_info):
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
        return {"patched_files": 0, "patched_ids": 0}

    @classmethod
    def apply_post_mod_manager_steps(
        cls,
        replacements,
        streaming_root,
        persistent_root,
        resolved_pck_names=None,
        status_callback=None,
    ):
        return {"patched_files": 0, "patched_ids": 0}
