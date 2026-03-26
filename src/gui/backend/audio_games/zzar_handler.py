from .base_handler import BaseBrowserHandler


class ZZARBrowserHandler(BaseBrowserHandler):
    game_id = "zzz"
    loop_point_patching_supported = False

    @staticmethod
    def should_skip_persistent_cleanup_folder(lang_folder, pck_count):
        # ZZZ default language folders can contain exactly 57 original PCKs.
        return int(pck_count) == 57
