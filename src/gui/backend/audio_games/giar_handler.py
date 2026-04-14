from .base_handler import BaseBrowserHandler


class GIARBrowserHandler(BaseBrowserHandler):
    game_id = "genshin"
    LOOP_POINT_MODES = {"auto", "manual", "disabled"}

    def include_pck_file(
        self,
        pck_file,
        current_language_folder,
        merge_wem_enabled,
        hide_useless_pck_enabled,
    ):
        if pck_file.name in self.game.protected_pcks:
            return False
        return True

    @staticmethod
    def should_list_direct_wem(merge_wem_enabled):
        return True

    @classmethod
    def is_loop_entry_applicable(cls, pck_filename, repl_info):
        name = str(pck_filename or "").lower()
        from src.core.game_registry import get_game
        titlescreen = {
            n.lower() for n in (get_game("genshin").titlescreen_pcks or ())
        }
        if not name.startswith("music") and name not in titlescreen:
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
