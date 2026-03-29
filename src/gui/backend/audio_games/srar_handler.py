from .base_handler import BaseBrowserHandler


class SRARBrowserHandler(BaseBrowserHandler):
    game_id = "hsr"

    @staticmethod
    def should_skip_persistent_cleanup_folder(lang_folder, pck_count):
        # HSR language folders in Persistent contain original voicelines;
        # never delete their contents.
        return True
