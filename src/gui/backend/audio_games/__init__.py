from .base_handler import BaseBrowserHandler
from .giar_handler import GIARBrowserHandler
from .srar_handler import SRARBrowserHandler
from .zzar_handler import ZZARBrowserHandler
from src.game_registry import (
    DEFAULT_GAME_ID,
    get_supported_game_ids,
    normalize_game_mode,
)


_CANONICAL_BROWSER_HANDLER_CLASSES = {
    "zzz": ZZARBrowserHandler,
    "genshin": GIARBrowserHandler,
    "hsr": SRARBrowserHandler,
}


def get_browser_handler_class(game_id):
    normalized = normalize_game_mode(game_id, default=DEFAULT_GAME_ID)
    return _CANONICAL_BROWSER_HANDLER_CLASSES.get(
        normalized,
        _CANONICAL_BROWSER_HANDLER_CLASSES[DEFAULT_GAME_ID],
    )


def build_browser_handlers(bridge):
    handlers = {}
    for game_id in get_supported_game_ids():
        handler_cls = get_browser_handler_class(game_id)
        handlers[game_id] = handler_cls(bridge)

    if DEFAULT_GAME_ID not in handlers:
        handlers[DEFAULT_GAME_ID] = get_browser_handler_class(DEFAULT_GAME_ID)(bridge)
    return handlers


__all__ = [
    "BaseBrowserHandler",
    "ZZARBrowserHandler",
    "GIARBrowserHandler",
    "SRARBrowserHandler",
    "get_browser_handler_class",
    "build_browser_handlers",
]
