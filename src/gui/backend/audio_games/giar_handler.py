from .base_handler import BaseBrowserHandler


class GIARBrowserHandler(BaseBrowserHandler):
    game_id = "genshin"
    LOOP_POINT_MODES = {"auto", "manual", "disabled"}

    def __init__(self, bridge, status_callback=None):
        super().__init__(bridge, game_id=self.game_id)
        self._status_callback = status_callback

    _OVERRIDE_PCKS = {"Patch.pck", "Hotfix.pck"}

    @classmethod
    def include_pck_file(
        cls,
        pck_file,
        current_language_folder,
        merge_wem_enabled,
        hide_useless_pck_enabled,
    ):
        if pck_file.name in cls._OVERRIDE_PCKS:
            return False
        return True

    @staticmethod
    def should_list_direct_wem(merge_wem_enabled):
        return True

    @classmethod
    def is_loop_entry_applicable(cls, pck_filename, repl_info):
        name = str(pck_filename or "").lower()
        if not name.startswith("music"):
            return False
        file_type = str((repl_info or {}).get("file_type", "")).lower()
        return file_type in ("wem", "bnk")

    @staticmethod
    def tracker_display_file_id(tracker_key):
        key_text = str(tracker_key or "").strip()
        return key_text.split("|")[-1] if "|" in key_text else key_text

    @staticmethod
    def tracker_plain_file_id(tracker_key):
        key_text = str(tracker_key or "").strip()
        return key_text.split("|")[-1] if "|" in key_text else key_text
