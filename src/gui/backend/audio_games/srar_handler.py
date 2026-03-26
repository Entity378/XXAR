from .base_handler import BaseBrowserHandler


class SRARBrowserHandler(BaseBrowserHandler):
    game_id = "hsr"
    loop_point_patching_supported = False
