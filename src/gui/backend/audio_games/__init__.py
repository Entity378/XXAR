from .base_handler import BaseBrowserHandler
from .giar_handler import GIARBrowserHandler
from .srar_handler import SRARBrowserHandler
from .zzar_handler import ZZARBrowserHandler

_BROWSER_HANDLER_CLASSES = {
    "zzz": ZZARBrowserHandler,
    "zzar": ZZARBrowserHandler,
    "genshin": GIARBrowserHandler,
    "giar": GIARBrowserHandler,
    "hsr": SRARBrowserHandler,
    "srar": SRARBrowserHandler,
}


def get_browser_handler_class(game_id):
    key = str(game_id or "").strip().lower()
    return _BROWSER_HANDLER_CLASSES.get(key, _BROWSER_HANDLER_CLASSES["zzz"])


__all__ = [
    "BaseBrowserHandler",
    "ZZARBrowserHandler",
    "GIARBrowserHandler",
    "SRARBrowserHandler",
    "get_browser_handler_class",
]
