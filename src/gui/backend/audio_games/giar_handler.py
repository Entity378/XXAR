import shutil
import struct
from pathlib import Path

from PyQt5.QtCore import QCoreApplication

from .base_handler import BaseBrowserHandler, _natural_sort_key


class GIARBrowserHandler(BaseBrowserHandler):
    game_id = "genshin"
    LOOP_POINT_MODES = {"auto", "manual", "disabled"}

    def __init__(self, bridge, status_callback=None):
        super().__init__(bridge, game_id=self.game_id)
        self._status_callback = status_callback

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
            for pck_file in sorted(streaming_root.glob("*.pck"), key=lambda p: _natural_sort_key(p.name))
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
            for pck_file in sorted(streaming_root.glob("*.pck"), key=lambda p: _natural_sort_key(p.name))
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
        name = str(pck_filename or "").lower()
        if not name.startswith("music"):
            return False
        file_type = str((repl_info or {}).get("file_type", "")).lower()
        return file_type == "wem"

    def _is_bank_pck(self, path):
        name = path.name.lower()
        return name.startswith("bank")

    @staticmethod
    def tracker_display_file_id(tracker_key):
        key_text = str(tracker_key or "").strip()
        return key_text.split("|")[-1] if "|" in key_text else key_text

    @staticmethod
    def tracker_plain_file_id(tracker_key):
        key_text = str(tracker_key or "").strip()
        return key_text.split("|")[-1] if "|" in key_text else key_text

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
