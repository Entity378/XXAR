from PyQt6.QtCore import QObject, pyqtProperty, pyqtSignal, pyqtSlot

from src.core.app_config import ACCENT_COLOR, ACCENT_COLOR_DARK, ACCENT_COLOR_LIGHT, GAME_THEME_PALETTES
from src.core.game_registry import DEFAULT_GAME_ID, normalize_game_id


class UIThemeBridge(QObject):
    themeChanged = pyqtSignal()

    def __init__(self, game_id=DEFAULT_GAME_ID, parent=None):
        super().__init__(parent)
        self._game_id = DEFAULT_GAME_ID
        self._accent_color = ACCENT_COLOR
        self._accent_color_light = ACCENT_COLOR_LIGHT
        self._accent_color_dark = ACCENT_COLOR_DARK
        self.set_theme_for_game(game_id)

    @pyqtProperty(str, notify=themeChanged)
    def gameId(self):
        return self._game_id

    @pyqtProperty(str, notify=themeChanged)
    def accentColor(self):
        return self._accent_color

    @pyqtProperty(str, notify=themeChanged)
    def accentColorLight(self):
        return self._accent_color_light

    @pyqtProperty(str, notify=themeChanged)
    def accentColorDark(self):
        return self._accent_color_dark

    @pyqtSlot(str)
    def setThemeForGame(self, game_id):
        self.set_theme_for_game(game_id)

    def set_theme_for_game(self, game_id):
        normalized = normalize_game_id(game_id)
        palette = GAME_THEME_PALETTES.get(normalized, GAME_THEME_PALETTES["zzz"])
        new_values = (
            normalized,
            palette[0],
            palette[1],
            palette[2],
        )
        old_values = (
            self._game_id,
            self._accent_color,
            self._accent_color_light,
            self._accent_color_dark,
        )
        if new_values == old_values:
            return False

        self._game_id = normalized
        self._accent_color = palette[0]
        self._accent_color_light = palette[1]
        self._accent_color_dark = palette[2]
        self.themeChanged.emit()
        return True
