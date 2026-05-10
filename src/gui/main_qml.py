from PyQt5.QtCore import QCoreApplication

import os
import sys
import json
import subprocess
from pathlib import Path

from src.core.logger import get_logger
from src.core.subprocess_utils import IS_WINDOWS, is_frozen
logger = get_logger(__name__)

if IS_WINDOWS:
    os.environ["QT_QPA_PLATFORM"] = "windows:fontengine=freetype"
from PyQt5.QtGui import QGuiApplication, QIcon, QSurfaceFormat, QFontDatabase, QPixmap
from PyQt5.QtQml import QQmlApplicationEngine, qmlRegisterSingletonType
from PyQt5.QtCore import QUrl, QObject, QCoreApplication, QMetaObject, Q_ARG, Qt, QThread, pyqtSignal, pyqtSlot
from PyQt5.QtWidgets import QApplication, QSplashScreen

class ClipboardHelper(QObject):
    @pyqtSlot(str)
    def setText(self, text):
        QApplication.clipboard().setText(text)

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(
    0, str(project_root / "src")
)

from src.gui.backend.mod_manager_bridge import ModManagerBridge
from src.gui.backend.audio_browser_bridge import AudioBrowserBridge
from src.gui.backend.audio_conversion_bridge import AudioConversionBridge
from src.gui.backend.update_manager_bridge import UpdateManagerBridge
from src.gui.backend.gamebanana_bridge import GameBananaBridge
from src.gui.backend.ui_theme_bridge import UIThemeBridge
from src.gui.backend.hirc_editor_bridge import HircEditorBridge
from src.gui.utils.native_dialogs import NativeDialogs
from src.core.config_manager import get_settings_file, get_cache_dir, normalize_game_id
from src.core.game_registry import DEFAULT_GAME_ID, get_supported_games
import src.core.app_config as app_config
from src.core.app_config import (
    APP_NAME, APP_VERSION,
    switch_active_game,
)

from src.gui.connectors.mod_manager_connector import ModManagerConnector
from src.gui.connectors.audio_browser_connector import AudioBrowserConnector
from src.gui.connectors.import_wizard_connector import ImportWizardConnector
from src.gui.connectors.settings_connector import SettingsConnector
from src.gui.connectors.update_connector import UpdateConnector
from src.gui.connectors.gamebanana_connector import GameBananaConnector
from src.gui.connectors.hirc_editor_connector import HircEditorConnector
from src.gui.translation_manager import TranslationManager

class AutoDetectWorker(QThread):

    found = pyqtSignal(str)
    notFound = pyqtSignal()

    def __init__(self, install_dir_name=None, data_dir_name=None):
        super().__init__()
        self._install_dir = install_dir_name
        self._data_dir = data_dir_name

    def run(self):
        install_dir = self._install_dir
        data_dir = self._data_dir

        if install_dir and data_dir:
            install_subdirs = [
                f"Program Files/HoYoPlay/games/{install_dir}",
                f"Program Files (x86)/HoYoPlay/games/{install_dir}",
            ]
            home_subdir = f"Games/{install_dir}"
        else:
            install_subdirs = app_config.GAME_INSTALL_SUBDIRS
            home_subdir = app_config.GAME_INSTALL_HOME_SUBDIR
            data_dir = app_config.GAME_DATA_FOLDER

        if IS_WINDOWS:

            search_paths = (
                [Path(f"{drive}:/{sub}") for drive in "CDEFGH" for sub in install_subdirs]
                + [Path.home() / home_subdir]
            )

            for base_path in search_paths:
                game_data_dir = base_path / data_dir
                if game_data_dir.exists() and (game_data_dir / "StreamingAssets").exists():
                    self.found.emit(str(game_data_dir))
                    return
        else:

            # Iterate every known Wine prefix (manual, Steam Proton, Lutris, Bottles, Heroic).
            # `find /` is slow and can't see the host FS from a Flatpak sandbox.
            logger.info(f"[{APP_NAME}] Scanning Wine prefixes for {data_dir}...")

            home = Path.home()
            drive_c_candidates: list[Path] = []

            for wine_root in (home / ".wine", Path(os.environ.get("WINEPREFIX") or "/dev/null")):
                drive_c = wine_root / "drive_c"
                if drive_c.is_dir():
                    drive_c_candidates.append(drive_c)

            steam_compatdata_roots = [
                home / ".steam" / "steam" / "steamapps" / "compatdata",
                home / ".local" / "share" / "Steam" / "steamapps" / "compatdata",
                home / ".var" / "app" / "com.valvesoftware.Steam"
                     / ".local" / "share" / "Steam" / "steamapps" / "compatdata",
            ]
            for compatdata in steam_compatdata_roots:
                if compatdata.is_dir():
                    for app_dir in compatdata.iterdir():
                        drive_c = app_dir / "pfx" / "drive_c"
                        if drive_c.is_dir():
                            drive_c_candidates.append(drive_c)

            # Lutris: each game has its own prefix at ~/Games/<name>/drive_c.
            lutris_games = home / "Games"
            if lutris_games.is_dir():
                for game_dir in lutris_games.iterdir():
                    drive_c = game_dir / "drive_c"
                    if drive_c.is_dir():
                        drive_c_candidates.append(drive_c)

            bottles_roots = [
                home / ".local" / "share" / "bottles" / "bottles",
                home / ".var" / "app" / "com.usebottles.bottles"
                     / "data" / "bottles" / "bottles",
            ]
            for bottles_root in bottles_roots:
                if bottles_root.is_dir():
                    for bottle in bottles_root.iterdir():
                        drive_c = bottle / "drive_c"
                        if drive_c.is_dir():
                            drive_c_candidates.append(drive_c)

            heroic_prefix_roots = [
                home / "Games" / "Heroic" / "Prefixes",
                home / ".var" / "app" / "com.heroicgameslauncher.hgl"
                     / "config" / "heroic" / "tools" / "wine",
            ]
            for heroic_root in heroic_prefix_roots:
                if heroic_root.is_dir():
                    for pfx in heroic_root.rglob("pfx"):
                        drive_c = pfx / "drive_c"
                        if drive_c.is_dir():
                            drive_c_candidates.append(drive_c)

            for drive_c in drive_c_candidates:
                for sub in install_subdirs:
                    game_data_dir = drive_c / sub / data_dir
                    if game_data_dir.exists() and (game_data_dir / "StreamingAssets").exists():
                        logger.info(f"[{APP_NAME}] Found game install at: {game_data_dir}")
                        self.found.emit(str(game_data_dir))
                        return

            logger.info(
                f"[{APP_NAME}] No game install found in {len(drive_c_candidates)} Wine prefixes"
            )

        self.notFound.emit()

def theme_singleton_provider(engine, script_engine):

    return None

class Application(
    ModManagerConnector,
    AudioBrowserConnector,
    ImportWizardConnector,
    SettingsConnector,
    UpdateConnector,
    GameBananaConnector,
    HircEditorConnector,
    QObject,
):

    def __init__(self, version):
        super().__init__()

        QCoreApplication.setApplicationVersion(version)

        self.app = None
        self.engine = None
        self.mod_manager_bridge = None
        self.audio_browser_bridge = None
        self.audio_conversion_bridge = None
        self.gamebanana_bridge = None
        self.ui_theme_bridge = None
        self.settings_file = get_settings_file()
        self.settings_page = None
        self.mod_page = None
        self.audio_page = None
        self.gamebanana_page = None
        self.conversion_page = None
        self.import_wizard = None
        self.mod_info_dialog = None
        self.pending_remove_uuids = []
        self.import_worker = None
        self.wizard_selected_files = []
        self.wizard_selected_folder = ""
        self.auto_detect_worker = None
        self.update_manager_bridge = None
        self.update_dialog = None
        self._startup_update_check = False
        self.hirc_editor_bridge = None
        self.hirc_editor_page = None

    def run(self):
        logger.info("=" * 50)
        logger.info(f"{APP_NAME} - {app_config.APP_FULL_NAME}")
        logger.info("QML UI Version")
        logger.info("=" * 50)

        QCoreApplication.setAttribute(Qt.AA_DontUseNativeDialogs, False)

        QCoreApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
        QCoreApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

        format = QSurfaceFormat()
        format.setSamples(4)
        QSurfaceFormat.setDefaultFormat(format)

        # DO NOT set organizationName.
        # Qt's QStandardPaths would nest cache as %LOCALAPPDATA%\XXAR\XXAR\cache\ instead of %LOCALAPPDATA%\XXAR\cache\.
        QCoreApplication.setOrganizationDomain(f"{APP_NAME.lower()}.local")
        QCoreApplication.setApplicationName(APP_NAME)

        self.app = QApplication(sys.argv)
        self.app.setApplicationName(APP_NAME)
        self.app.setApplicationVersion(QCoreApplication.applicationVersion())

        ui_path = Path(__file__).parent
        icon_path = ui_path / "assets" / "XXAR" / "XXAR-Logo2-256.png"
        if icon_path.exists():
            self.app.setWindowIcon(QIcon(str(icon_path)))

        # Splash so the user sees branding immediately
        self._splash = None
        # try:
        #     splash_path = ui_path / "assets" / "XXAR" / "XXAR-Logo2-512.png"
        #     if splash_path.exists():
        #         pixmap = QPixmap(str(splash_path))
        #         self._splash = QSplashScreen(pixmap, Qt.WindowStaysOnTopHint)
        #         self._splash.show()
        #         self.app.processEvents()
        # except Exception as e:
        #     logger.warning(f"[{APP_NAME}] Splash unavailable: {e}")
        #     self._splash = None

        fonts_dir = ui_path / "assets" / "fonts"

        audiowide_font = fonts_dir / "Audiowide" / "Audiowide-Regular.ttf"
        alatsi_font = fonts_dir / "Alatsi" / "Alatsi-Regular.ttf"
        stretch_pro_font = fonts_dir / "Stretch_Pro" / "StretchPro.otf"

        if audiowide_font.exists():
            if QFontDatabase.addApplicationFont(str(audiowide_font)) == -1:
                logger.error(f"[{APP_NAME}] WARNING: Failed to load Audiowide font")
        else:
            logger.warning(f"[{APP_NAME}] WARNING: Audiowide font not found at {audiowide_font}")

        if alatsi_font.exists():
            if QFontDatabase.addApplicationFont(str(alatsi_font)) == -1:
                logger.error(f"[{APP_NAME}] WARNING: Failed to load Alatsi font")
        else:
            logger.warning(f"[{APP_NAME}] WARNING: Alatsi font not found at {alatsi_font}")

        if stretch_pro_font.exists():
            if QFontDatabase.addApplicationFont(str(stretch_pro_font)) == -1:
                logger.error(f"[{APP_NAME}] WARNING: Failed to load Stretch Pro font")
        else:
            logger.warning(f"[{APP_NAME}] WARNING: Stretch Pro font not found at {stretch_pro_font}")

        zzz_font = fonts_dir / "ZZZ-Font" / "ZZZ-Font.ttf"
        if zzz_font.exists():
            if QFontDatabase.addApplicationFont(str(zzz_font)) == -1:
                logger.error(f"[{APP_NAME}] WARNING: Failed to load ZZZ font")
        else:
            logger.warning(f"[{APP_NAME}] WARNING: ZZZ font not found at {zzz_font}")

        self.engine = QQmlApplicationEngine()
        self.mod_manager_bridge = ModManagerBridge()
        self.audio_browser_bridge = AudioBrowserBridge()
        self.audio_conversion_bridge = AudioConversionBridge()
        self.gamebanana_bridge = GameBananaBridge()
        self.update_manager_bridge = UpdateManagerBridge()
        self.update_manager_bridge.setCurrentVersion(QCoreApplication.applicationVersion())
        self.hirc_editor_bridge = HircEditorBridge()

        context = self.engine.rootContext()
        startup_settings = self.load_settings()
        startup_game = normalize_game_id(
            startup_settings.get("selected_game", DEFAULT_GAME_ID)
        )
        switch_active_game(startup_game)
        self.gamebanana_bridge.set_active_game(startup_game, reload=False)
        self.ui_theme_bridge = UIThemeBridge(startup_game)

        context.setContextProperty("modManagerBackend", self.mod_manager_bridge)
        context.setContextProperty("audioBrowserBackend", self.audio_browser_bridge)
        context.setContextProperty("audioConversionBackend", self.audio_conversion_bridge)
        context.setContextProperty("gameBananaBackend", self.gamebanana_bridge)
        context.setContextProperty("uiTheme", self.ui_theme_bridge)
        context.setContextProperty("hircEditorBackend", self.hirc_editor_bridge)
        self.clipboard_helper = ClipboardHelper()
        context.setContextProperty("clipboardHelper", self.clipboard_helper)

        context.setContextProperty("appName", APP_NAME)
        context.setContextProperty("appFullName", app_config.APP_FULL_NAME)
        context.setContextProperty("gameName", app_config.GAME_NAME)
        context.setContextProperty("gameShort", app_config.GAME_SHORT)
        context.setContextProperty("gameDataFolder", app_config.GAME_DATA_FOLDER)
        context.setContextProperty("modFileExt", app_config.MOD_FILE_EXT)
        context.setContextProperty("modFileExtUpper", app_config.MOD_FILE_EXT_UPPER)
        context.setContextProperty("logoPng", app_config.LOGO_PNG)
        context.setContextProperty("assetsDir", app_config.ASSETS_DIR)
        context.setContextProperty("accentColor", app_config.ACCENT_COLOR)
        context.setContextProperty("accentColorLight", app_config.ACCENT_COLOR_LIGHT)
        context.setContextProperty("accentColorDark", app_config.ACCENT_COLOR_DARK)

        context.setContextProperty(
            "supportedGames",
            [
                {
                    "id": g.id,
                    "displayName": g.display_name,
                    "shortLabel": g.short_label,
                    "dataDirName": g.data_dir_name,
                }
                for g in get_supported_games()
            ],
        )

        self.translation_manager = TranslationManager(self.engine)
        context.setContextProperty("translationManager", self.translation_manager)

        settings = startup_settings
        saved_lang = settings.get("language", "en")
        if saved_lang != "en":
            self.translation_manager.changeLanguage(saved_lang)

        ui_path = Path(__file__).parent
        self.engine.addImportPath(str(ui_path / "qml"))
        self.engine.addImportPath(str(ui_path / "components"))

        if hasattr(sys, '_MEIPASS'):
            qml_base = Path(sys._MEIPASS) / 'PyQt5' / 'Qt5' / 'qml'
            if qml_base.exists():
                self.engine.addImportPath(str(qml_base))
                logger.info(f"[{APP_NAME}] Added PyInstaller QML path: {qml_base}")

        qml_file = ui_path / "qml" / "MainWindow.qml"
        logger.info(f"Loading QML from: {qml_file}")
        self.engine.load(QUrl.fromLocalFile(str(qml_file)))

        if not self.engine.rootObjects():
            logger.error("Error: Failed to load QML")
            sys.exit(1)

        logger.info(f"[{APP_NAME}] QML loaded successfully!")
        logger.info(f"[{APP_NAME}] Initializing mod manager...")

        root = self.engine.rootObjects()[0]
        self.root = root

        from PyQt5.QtGui import QGuiApplication

        screen = QGuiApplication.primaryScreen()
        screen_geo = screen.availableGeometry()

        avail_x = screen_geo.x()
        avail_y = screen_geo.y()
        avail_w = screen_geo.width()
        avail_h = screen_geo.height()

        win_w = min(root.property("width"), avail_w)
        win_h = min(root.property("height"), avail_h)
        win_x = avail_x + (avail_w - win_w) // 2
        win_y = avail_y + (avail_h - win_h) // 2

        root.setProperty("width", win_w)
        root.setProperty("height", win_h)
        root.setProperty("x", win_x)
        root.setProperty("y", win_y)
        logger.info(f"[{APP_NAME}] Window positioned: {win_w}x{win_h} at ({win_x},{win_y}), available: {avail_w}x{avail_h}")

        if self._splash is not None:
            self._splash.close()
            self._splash = None

        self._connect_mod_manager()
        self._connect_audio_browser()
        self._connect_gamebanana()
        self._connect_conversion_page()
        self._connect_settings()
        self._connect_updates()
        self._connect_import_wizard()
        self._connect_hirc_editor()

        self.mod_info_dialog = root.findChild(QObject, "modInfoDialog")
        if self.mod_info_dialog:
            self.mod_info_dialog.exportRequested.connect(
                self.mod_manager_bridge.exportMod
            )
            logger.info(f"[{APP_NAME}] Mod info dialog connected")

        self.update_dialog = root.findChild(QObject, "updateDialog")
        if self.update_dialog:
            self.update_dialog.updateAccepted.connect(self._on_update_dialog_accepted)
            self.update_dialog.updateDismissed.connect(self._on_update_dialog_dismissed)
            logger.info(f"[{APP_NAME}] Update dialog connected")

        self.conflict_resolution_dialog = root.findChild(QObject, "conflictResolutionDialog")
        if self.conflict_resolution_dialog:
            self.conflict_resolution_dialog.setProperty("modManager", self.mod_manager_bridge)
            logger.info(f"[{APP_NAME}] Conflict resolution dialog connected")

        self.mod_conflict_dialog = root.findChild(QObject, "modConflictDialog")
        if self.mod_conflict_dialog:
            self.mod_conflict_dialog.setProperty("modManager", self.mod_manager_bridge)
            logger.info(f"[{APP_NAME}] Mod conflict dialog connected")

        self.audio_match_dialog = root.findChild(QObject, "audioMatchDialog")
        if self.audio_match_dialog:
            self.audio_match_dialog.fileSelectionRequested.connect(
                self.audio_browser_bridge.selectRecordingFile
            )
            self.audio_match_dialog.matchStartRequested.connect(
                self.audio_browser_bridge.startMatchingWithFile
            )
            self.audio_match_dialog.matchCancelled.connect(
                self.audio_browser_bridge.cancelMatchingSound
            )
            self.audio_browser_bridge.audio_match_dialog = self.audio_match_dialog
            logger.info(f"[{APP_NAME}] Audio match dialog connected")

        self._connect_welcome_dialog()

        logger.info(f"[{APP_NAME}] Application ready!")
        logger.info("-" * 50)

        is_first_launch = self.check_first_launch()

        if not is_first_launch:
            self.check_multiple_languages()

        self._check_update_success_flag()

        if is_frozen():
            logger.info(f"[{APP_NAME}] Frozen build detected, checking for updates...")
            self._startup_update_check = True
            self.update_manager_bridge.checkForUpdates()

        return self.app.exec_()

    def _connect_conversion_page(self):
        self.conversion_page = self.root.findChild(QObject, "audioConversionPage")
        if not self.conversion_page:
            return

        ac = self.audio_conversion_bridge

        self.conversion_page.browseInputFileClicked.connect(
            self.on_conversion_browse_input_file
        )
        self.conversion_page.browseInputDirectoryClicked.connect(
            self.on_conversion_browse_input_dir
        )
        self.conversion_page.browseOutputDirectoryClicked.connect(
            self.on_conversion_browse_output_dir
        )
        self.conversion_page.convertAudioClicked.connect(ac.convertAudio)

        ac.inputPathSelected.connect(
            lambda path: QMetaObject.invokeMethod(
                self.conversion_page, "setInputPath",
                Qt.QueuedConnection, Q_ARG("QVariant", path)
            )
        )
        ac.outputPathSelected.connect(
            lambda path: QMetaObject.invokeMethod(
                self.conversion_page, "setOutputPath",
                Qt.QueuedConnection, Q_ARG("QVariant", path)
            )
        )
        ac.conversionStarted.connect(
            lambda: QMetaObject.invokeMethod(
                self.conversion_page, "setConvertingState",
                Qt.QueuedConnection, Q_ARG("QVariant", True)
            )
        )
        ac.conversionFinished.connect(
            lambda: QMetaObject.invokeMethod(
                self.conversion_page, "setConvertingState",
                Qt.QueuedConnection, Q_ARG("QVariant", False)
            )
        )
        ac.logMessage.connect(
            lambda msg: QMetaObject.invokeMethod(
                self.conversion_page, "appendLog",
                Qt.QueuedConnection, Q_ARG("QVariant", msg)
            )
        )
        ac.errorOccurred.connect(self.on_error_occurred)
        ac.conversionSuccess.connect(self.on_conversion_success)
        ac.conversionErrorDialog.connect(self.on_conversion_error_dialog)

        ab = self.audio_browser_bridge
        self.conversion_page.normalizeAudioToggled.connect(ab.setNormalizeAudio)
        self.conversion_page.normalizeTargetLufsSet.connect(ab.setNormalizeTargetLufs)
        ab.normalizeAudioChanged.connect(
            lambda enabled: self.conversion_page.setProperty("normalizeChecked", enabled)
        )
        self.conversion_page.setProperty("normalizeChecked", ab.normalize_audio_enabled)
        self.conversion_page.setProperty("normalizeTargetLufs", ab.normalize_target_lufs)

        logger.info(f"[{APP_NAME}] Audio conversion page connected")

    def load_settings(self):
        try:
            if self.settings_file.exists():
                with open(self.settings_file, "r") as f:
                    return json.load(f)
        except Exception as e:
            logger.error(f"Warning: Failed to load settings: {e}")
        return {}

    def on_progress_update(self, message):
        if "successfully" in message.lower() or "applied" in message.lower():
            QMetaObject.invokeMethod(
                self.root,
                "showSuccessToast",
                Qt.QueuedConnection,
                Q_ARG("QVariant", message),
            )

    def on_error_occurred(self, title, message):
        full_message = f"{title}: {message}" if title else message
        QMetaObject.invokeMethod(
            self.root,
            "showErrorToast",
            Qt.QueuedConnection,
            Q_ARG("QVariant", full_message),
        )

    def on_alert_dialog_requested(self, title, message, sticker_path=""):
        QMetaObject.invokeMethod(
            self.root,
            "showAlertDialog",
            Qt.QueuedConnection,
            Q_ARG("QVariant", title),
            Q_ARG("QVariant", message),
            Q_ARG("QVariant", sticker_path),
        )

    def on_wip_dialog_requested(self):
        QMetaObject.invokeMethod(
            self.root,
            "showSuccessDialog",
            Qt.QueuedConnection,
            Q_ARG("QVariant", QCoreApplication.translate("Application", "Work in Progress")),
            Q_ARG("QVariant", QCoreApplication.translate("Application", "This feature is not yet implemented.\n\nThis will be added in a future update. (i hope)")),
            Q_ARG("QVariant", f"../assets/{app_config.ASSETS_DIR}/YuzuhaSilly.png")
        )

    def on_wwise_error_dialog(self, title, message):
        QMetaObject.invokeMethod(
            self.root,
            "showAlertDialog",
            Qt.QueuedConnection,
            Q_ARG("QVariant", title),
            Q_ARG("QVariant", message),
            Q_ARG("QVariant", ""),
        )

    def on_audio_success_dialog(self, title, message, image_path):
        QMetaObject.invokeMethod(
            self.root,
            "showSuccessDialog",
            Qt.QueuedConnection,
            Q_ARG("QVariant", title),
            Q_ARG("QVariant", message),
            Q_ARG("QVariant", image_path),
        )

    def on_conversion_success(self, title, message):
        QMetaObject.invokeMethod(
            self.root,
            "showSuccessDialog",
            Qt.QueuedConnection,
            Q_ARG("QVariant", title),
            Q_ARG("QVariant", message),
            Q_ARG("QVariant", ""),
        )

    def on_conversion_error_dialog(self, title, message):
        QMetaObject.invokeMethod(
            self.root,
            "showAlertDialog",
            Qt.QueuedConnection,
            Q_ARG("QVariant", title),
            Q_ARG("QVariant", message),
            Q_ARG("QVariant", ""),
        )

    def on_conversion_browse_input_file(self):
        if not self.conversion_page:
            return

        mode = self.conversion_page.property("currentMode")

        if mode == 0:
            filter_str = "WEM Files (*.wem);;All Files (*)"
            title = "Select WEM File"
        elif mode == 1:
            filter_str = "Audio Files (*.mp3 *.flac *.ogg *.m4a *.aac);;All Files (*)"
            title = "Select Audio File"
        else:
            filter_str = "WAV Files (*.wav);;All Files (*)"
            title = "Select WAV File"

        file_path = NativeDialogs.get_open_file(
            title, filter_str=filter_str, remember_key="audio_convert_input_file"
        )

        if file_path:
            self.audio_conversion_bridge.inputPathSelected.emit(file_path)

    def on_conversion_browse_input_dir(self):
        dirname = NativeDialogs.get_directory(
            "Select Input Directory", remember_key="audio_convert_input_dir"
        )

        if dirname:
            self.audio_conversion_bridge.inputPathSelected.emit(dirname)

    def on_conversion_browse_output_dir(self):
        dirname = NativeDialogs.get_directory(
            "Select Output Directory", remember_key="audio_convert_output_dir"
        )

        if dirname:
            self.audio_conversion_bridge.outputPathSelected.emit(dirname)

def main():

    app = Application(version=APP_VERSION)
    return app.run()

if __name__ == "__main__":
    sys.exit(main())
