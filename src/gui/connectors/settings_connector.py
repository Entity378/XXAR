from PyQt5.QtCore import QCoreApplication
import json
import platform
import threading
from pathlib import Path

from PyQt5.QtCore import QObject, QMetaObject, Q_ARG, Qt, QTimer
from PyQt5.QtWidgets import QApplication

from gui.backend.native_dialogs import NativeDialogs
from src.app_config import (
    APP_NAME,
    ASSETS_DIR,
)
from src.config_manager import (
    get_custom_mod_library_settings_key,
    get_game_mod_library_dir,
    normalize_game_id,
)
from src.game_registry import (
    DEFAULT_GAME_ID,
    build_audio_paths,
    detect_game_id_from_path,
    extract_game_data_dir_from_audio_path,
    get_game,
    get_audio_settings_keys,
    get_supported_game_ids,
    is_valid_game_data_dir,
    normalize_game_data_dir,
)


class SettingsConnector:
    _swap_in_progress = False

    def _set_root_active_game_props(self, game_id):
        if not self.root:
            return
        game = get_game(game_id)
        self.root.setProperty("activeGameShort", game.short_label)
        self.root.setProperty("activeGameName", game.display_name)
        if getattr(self, "settings_page", None):
            self.settings_page.setProperty("gameDataFolderName", game.data_dir_name)
        if getattr(self, "welcome_dialog", None):
            self.welcome_dialog.setProperty("gameDataFolderName", game.data_dir_name)
        if getattr(self, "ui_theme_bridge", None):
            self.ui_theme_bridge.set_theme_for_game(game_id)

    def _get_selected_or_detected_game_id(self, preferred_path=""):
        detected = detect_game_id_from_path(preferred_path, default=None) if preferred_path else None
        if detected:
            return normalize_game_id(detected)
        settings = self.load_settings()
        return normalize_game_id(settings.get("selected_game", DEFAULT_GAME_ID))

    def _cycle_game_id(self, current_game_id):
        supported = [normalize_game_id(g) for g in get_supported_game_ids()]
        if not supported:
            return DEFAULT_GAME_ID
        if current_game_id not in supported:
            return supported[0]
        return supported[(supported.index(current_game_id) + 1) % len(supported)]

    def _switch_active_game(self, target_game_id):
        settings = self.load_settings()
        target_game_id = normalize_game_id(target_game_id)
        settings["selected_game"] = target_game_id

        game_audio_key, persistent_audio_key = get_audio_settings_keys(target_game_id)
        game_data_dir = self._get_saved_game_data_dir(settings, target_game_id)
        if game_data_dir and is_valid_game_data_dir(game_data_dir):
            audio_dir, persistent_dir = build_audio_paths(target_game_id, game_data_dir)
            settings[game_audio_key] = str(audio_dir)
            settings[persistent_audio_key] = str(persistent_dir)
            settings["game_audio_dir"] = str(audio_dir)
            settings["persistent_audio_dir"] = str(persistent_dir)
        else:
            game_data_dir = ""
            settings["game_audio_dir"] = ""
            settings["persistent_audio_dir"] = ""

        custom_mods_dir = self._get_custom_mods_dir_for_game(settings, target_game_id)

        self.settings_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.settings_file, "w") as f:
            json.dump(settings, f, indent=2)

        # Light UI updates — instant, main thread.
        if self.settings_page:
            self.settings_page.setProperty(
                "defaultModsDirectory", str(get_game_mod_library_dir(target_game_id))
            )
            self.settings_page.setModsDirectory(custom_mods_dir or "")
            self.settings_page.setGameDirectory(game_data_dir)

        if self.audio_page:
            QMetaObject.invokeMethod(
                self.audio_page,
                "setGameDirectory",
                Qt.QueuedConnection,
                Q_ARG("QVariant", game_data_dir),
            )

        self._set_root_active_game_props(target_game_id)

        # Heavy work — background thread (glob, scan, refresh).
        threading.Thread(
            target=self._switch_active_game_heavy,
            args=(target_game_id, game_data_dir),
            daemon=True,
        ).start()

        return target_game_id, game_data_dir

    def _switch_active_game_heavy(self, target_game_id, game_data_dir):
        try:
            if self.audio_browser_bridge:
                if game_data_dir:
                    self.audio_browser_bridge.loadFromSettings()
                else:
                    # No directory configured — clear the browser.
                    self.audio_browser_bridge._index_cancel.set()
                    self.audio_browser_bridge.treeCleared.emit()
                    self.audio_browser_bridge.languageTabsReady.emit([])
                    self.audio_browser_bridge.statusUpdate.emit(
                        QCoreApplication.translate(
                            "Application",
                            "No game directory configured. Set it in Settings.",
                        )
                    )
            if self.mod_manager_bridge:
                self.mod_manager_bridge.load_settings()
                self.mod_manager_bridge.refreshMods()
            if self.gamebanana_bridge:
                self.gamebanana_bridge.set_active_game(target_game_id, reload=False)
                if self.gamebanana_page:
                    QMetaObject.invokeMethod(
                        self.gamebanana_page,
                        "reloadForActiveGame",
                        Qt.QueuedConnection,
                    )
                else:
                    self.gamebanana_bridge.refresh()
        except Exception as e:
            print(f"[Settings] Background game switch error: {e}")

    def on_swap_game_requested(self):
        if self._swap_in_progress:
            return

        self._swap_in_progress = True
        try:
            # Cancel any running indexing immediately.
            if self.audio_browser_bridge:
                self.audio_browser_bridge._index_cancel.set()

            settings = self.load_settings()
            current = normalize_game_id(
                settings.get("selected_game", DEFAULT_GAME_ID)
            )
            next_game = self._cycle_game_id(current)
            active_game_id, game_data_dir = self._switch_active_game(next_game)
            active_game = get_game(active_game_id)

            message = QCoreApplication.translate(
                "Application", "Active game: %1"
            ).replace("%1", active_game.display_name)
            if not game_data_dir:
                message += "\n" + QCoreApplication.translate(
                    "Application",
                    "No folder configured for this game yet. Set it in Settings.",
                )

            QMetaObject.invokeMethod(
                self.root,
                "showSuccessToast",
                Qt.QueuedConnection,
                Q_ARG("QVariant", message),
            )
        except Exception as e:
            print(f"[Settings] Failed to swap active game: {e}")
            QMetaObject.invokeMethod(
                self.root,
                "showErrorToast",
                Qt.QueuedConnection,
                Q_ARG(
                    "QVariant",
                    QCoreApplication.translate("Application", "Failed to swap game: %1").replace("%1", str(e)),
                ),
            )
        finally:
            # Unlock after 1 second cooldown.
            QTimer.singleShot(1000, self._unlock_swap)

    def _unlock_swap(self):
        self._swap_in_progress = False

    def _store_game_data_dir_settings(self, settings, game_data_dir, set_active=False):
        if not game_data_dir:
            return None

        normalized = normalize_game_data_dir(game_data_dir)
        if not is_valid_game_data_dir(normalized):
            return None

        game_id = normalize_game_id(
            detect_game_id_from_path(normalized, default=DEFAULT_GAME_ID)
        )
        game_audio_key, persistent_audio_key = get_audio_settings_keys(game_id)
        audio_dir, persistent_dir = build_audio_paths(game_id, normalized)
        settings[game_audio_key] = str(audio_dir)
        settings[persistent_audio_key] = str(persistent_dir)

        if set_active:
            settings["selected_game"] = game_id
            # Keep legacy keys for backward compatibility with current bridges.
            settings["game_audio_dir"] = str(audio_dir)
            settings["persistent_audio_dir"] = str(persistent_dir)

        return game_id

    def _get_saved_game_data_dir(self, settings, game_id):
        game_audio_key, _ = get_audio_settings_keys(game_id)
        audio_dir = settings.get(game_audio_key, "")
        if not audio_dir and game_id == DEFAULT_GAME_ID:
            audio_dir = settings.get("game_audio_dir", "")
        return extract_game_data_dir_from_audio_path(audio_dir)

    @staticmethod
    def _get_custom_mods_dir_for_game(settings, game_id):
        custom_key = get_custom_mod_library_settings_key(game_id)
        custom_mods_dir = settings.get(custom_key, "")
        if not custom_mods_dir and normalize_game_id(game_id) == DEFAULT_GAME_ID:
            custom_mods_dir = settings.get("custom_mod_library_dir", "")
        return custom_mods_dir

    def _connect_settings(self):
        self.settings_page = self.root.findChild(QObject, "settingsPage")
        if not self.settings_page:
            return

        self.settings_page.browseGameDirClicked.connect(self.on_browse_game_dir)
        self.settings_page.autoDetectClicked.connect(self.on_auto_detect)
        self.settings_page.browseModsDirClicked.connect(self.on_browse_mods_dir)
        self.settings_page.resetModsDirClicked.connect(self.on_reset_mods_dir)
        self.settings_page.saveSettingsClicked.connect(self.on_save_settings)

        self.settings_page.modCreationModeToggled.connect(
            self.mod_manager_bridge.setModCreationMode
        )
        self.settings_page.checkWwiseClicked.connect(
            self.mod_manager_bridge.checkWwiseInstalled
        )
        self.settings_page.runWwiseSetupClicked.connect(
            self.mod_manager_bridge.runWwiseSetup
        )
        self.settings_page.checkAudioToolsClicked.connect(
            self.mod_manager_bridge.checkAudioToolsInstalled
        )
        self.settings_page.runAudioToolsSetupClicked.connect(
            self.mod_manager_bridge.runAudioToolsSetup
        )
        self.settings_page.languageChanged.connect(self.on_language_changed)
        self.settings_page.uiScaleSelected.connect(self.on_ui_scale_changed)
        self.root.swapGameRequested.connect(self.on_swap_game_requested)

        self.mod_manager_bridge.modCreationModeChanged.connect(
            self.on_mod_creation_mode_changed
        )
        self.mod_manager_bridge.wwiseStatusChanged.connect(
            self.on_wwise_status_changed
        )
        self.mod_manager_bridge.wwiseSetupConfirmation.connect(
            self.on_wwise_setup_confirmation
        )
        self.mod_manager_bridge.wwiseSetupSuccess.connect(
            self.on_wwise_setup_success
        )
        self.mod_manager_bridge.audioToolsStatusChanged.connect(
            self.on_audio_tools_status_changed
        )
        self.mod_manager_bridge.audioToolsSetupSuccess.connect(
            self.on_audio_tools_setup_success
        )
        self.mod_manager_bridge.modInstallSuccess.connect(
            self.on_mod_install_success
        )
        self.mod_manager_bridge.conflictsDetected.connect(
            self.on_conflicts_detected
        )
        self.mod_manager_bridge.modConflictsDetected.connect(
            self.on_mod_conflicts_detected
        )

        self.load_settings_to_ui()
        print(f"[{APP_NAME}] Settings page connected")

    def _connect_welcome_dialog(self):
        self.welcome_dialog = self.root.findChild(QObject, "welcomeDialog")
        if not self.welcome_dialog:
            print(f"[{APP_NAME}] WARNING: Welcome dialog not found!")
            return

        self.welcome_dialog.modeSelected.connect(self.on_welcome_mode_selected)
        self.welcome_dialog.gameSelected.connect(self.on_welcome_game_selected)
        self.welcome_dialog.browseGameDirClicked.connect(self.on_welcome_browse_game_dir)
        self.welcome_dialog.autoDetectClicked.connect(self.on_welcome_auto_detect)
        self.welcome_dialog.checkWwiseClicked.connect(
            self.mod_manager_bridge.checkWwiseInstalled
        )
        self.welcome_dialog.runWwiseSetupClicked.connect(
            self.mod_manager_bridge.runWwiseSetup
        )
        self.welcome_dialog.checkAudioToolsClicked.connect(
            self.mod_manager_bridge.checkAudioToolsInstalled
        )
        self.welcome_dialog.runAudioToolsSetupClicked.connect(
            self.mod_manager_bridge.runAudioToolsSetup
        )

        self.mod_manager_bridge.wwiseStatusChanged.connect(
            self.on_welcome_wwise_status_changed
        )
        self.mod_manager_bridge.audioToolsStatusChanged.connect(
            self.on_welcome_audio_tools_status_changed
        )

        self.welcome_dialog.welcomeLanguageChanged.connect(self.on_language_changed)

        if hasattr(self.welcome_dialog, 'startTutorialClicked'):
            self.welcome_dialog.startTutorialClicked.connect(self.on_start_tutorial)

        settings = self.load_settings()
        selected_game = normalize_game_id(
            settings.get("selected_game", DEFAULT_GAME_ID)
        )
        self._set_root_active_game_props(selected_game)

        print(f"[{APP_NAME}] Welcome dialog connected")

    def load_settings_to_ui(self):
        settings = self.load_settings()
        selected_game = normalize_game_id(
            settings.get("selected_game", DEFAULT_GAME_ID)
        )
        game_audio_key, _ = get_audio_settings_keys(selected_game)
        existing_audio_dir = settings.get(game_audio_key, "") or settings.get(
            "game_audio_dir", ""
        )
        selected_data_dir = extract_game_data_dir_from_audio_path(
            existing_audio_dir
        )

        mod_creation_mode = settings.get("mod_creation_mode", False)
        self.root.setProperty("modCreationEnabled", mod_creation_mode)
        self.settings_page.setProperty("modCreationEnabled", mod_creation_mode)

        enable_gb_thumbnails = settings.get("enable_gb_thumbnails", False)
        self.settings_page.setProperty("enableGbThumbnails", enable_gb_thumbnails)

        # Also propagate to gameBananaPage so the thumbnail guard knows the state
        gb_page = self.root.findChild(QObject, "gameBananaPage")
        if gb_page:
            gb_page.setProperty("thumbnailsEnabled", enable_gb_thumbnails)

        hide_gb_thumbnail_warning = settings.get("hide_gb_thumbnail_warning", False)
        self.settings_page.setProperty("hideGbThumbnailWarning", hide_gb_thumbnail_warning)

        if mod_creation_mode:
            self.mod_manager_bridge.checkWwiseInstalled()

        if platform.system() == "Windows":
            self.mod_manager_bridge.checkAudioToolsInstalled()

        if selected_data_dir:
            self.settings_page.setGameDirectory(selected_data_dir)
        self._set_root_active_game_props(selected_game)

        self.settings_page.setProperty(
            "defaultModsDirectory", str(get_game_mod_library_dir(selected_game))
        )
        custom_mods_dir = self._get_custom_mods_dir_for_game(settings, selected_game)
        if custom_mods_dir:
            self.settings_page.setModsDirectory(custom_mods_dir)

        saved_lang = settings.get("language", "en")
        self.settings_page.setProperty("currentLanguage", saved_lang)

        saved_scale = settings.get("ui_scale", 1.0)
        self.settings_page.setProperty("uiScale", saved_scale)

    def on_language_changed(self, lang_code):
        self.translation_manager.changeLanguage(lang_code)

        if self.settings_page:
            self.settings_page.setProperty("currentLanguage", lang_code)

        try:
            settings = self.load_settings()
            settings["language"] = lang_code
            self.settings_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.settings_file, "w") as f:
                json.dump(settings, f, indent=2)
            print(f"[{APP_NAME}] Language changed to: {lang_code}")
        except Exception as e:
            print(f"[{APP_NAME}] Error saving language preference: {e}")

    def on_ui_scale_changed(self, scale):
        try:
            settings = self.load_settings()
            settings["ui_scale"] = scale
            self.settings_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.settings_file, "w") as f:
                json.dump(settings, f, indent=2)
            print(f"[{APP_NAME}] UI scale changed to: {scale}")
            QMetaObject.invokeMethod(
                self.root, "showSuccessToast", Qt.QueuedConnection,
                Q_ARG("QVariant", QCoreApplication.translate("Application", "UI scale saved. Restart to apply.")),
            )
        except Exception as e:
            print(f"[{APP_NAME}] Error saving UI scale: {e}")

    def on_mod_creation_mode_changed(self, enabled):
        self.root.setProperty("modCreationEnabled", enabled)

        if self.settings_page:
            self.settings_page.setProperty("modCreationEnabled", enabled)
            if enabled:
                self.mod_manager_bridge.checkWwiseInstalled()

    def on_wwise_status_changed(self, installed):
        if self.settings_page:
            self.settings_page.setProperty("wwiseInstalled", installed)
            self.settings_page.setProperty("isInstallingWwise", False)

    def on_wwise_setup_confirmation(self):
        title = QCoreApplication.translate("Application", "Wwise Setup Warning")
        message = QCoreApplication.translate("Application", "You are about to download licensed software from Audiokinetic.\n\n"
            "By proceeding, you acknowledge that:\n"
            "• You are downloading software directly from Audiokinetic\n"
            "• This software is subject to Audiokinetic's licensing terms\n"
            "• You use this software at your own risk\n"
            "• Pucas01 and other ZZAR contributors are not responsible for any issues\n\n"
            "Do you want to continue?")
        QMetaObject.invokeMethod(
            self.root,
            "showConfirmDialog",
            Qt.QueuedConnection,
            Q_ARG("QVariant", title),
            Q_ARG("QVariant", message),
            Q_ARG("QVariant", "wwise_setup"),
            Q_ARG("QVariant", f"../assets/{ASSETS_DIR}/BellNervous.png")
        )

    def on_wwise_setup_success(self, title, message):
        QMetaObject.invokeMethod(
            self.root,
            "showSuccessDialog",
            Qt.QueuedConnection,
            Q_ARG("QVariant", title),
            Q_ARG("QVariant", message),
            Q_ARG("QVariant", ""),
        )

    def on_audio_tools_status_changed(self, installed):
        print(f"[{APP_NAME}] on_audio_tools_status_changed called: installed={installed}")
        if self.settings_page:
            print(f"[{APP_NAME}] Setting audioToolsInstalled={installed}, isInstallingAudioTools=False")
            self.settings_page.setProperty("audioToolsInstalled", installed)
            self.settings_page.setProperty("isInstallingAudioTools", False)
            print(f"[{APP_NAME}] Properties set successfully")
        else:
            print(f"[{APP_NAME}] WARNING: settings_page is None!")

    def on_audio_tools_setup_success(self, title, message):
        if self.audio_browser_bridge:
            self.audio_browser_bridge.refresh_audio_tools()
        QMetaObject.invokeMethod(
            self.root,
            "showSuccessDialog",
            Qt.QueuedConnection,
            Q_ARG("QVariant", title),
            Q_ARG("QVariant", message),
            Q_ARG("QVariant", ""),
        )

    def on_mod_install_success(self, title, message, image_path):
        print(f"[DEBUG] Mod install success dialog triggered: {title}")
        print(f"[DEBUG] Message: {message}")
        print(f"[DEBUG] Image: {image_path}")
        QMetaObject.invokeMethod(
            self.root,
            "showSuccessDialog",
            Qt.QueuedConnection,
            Q_ARG("QVariant", title),
            Q_ARG("QVariant", message),
            Q_ARG("QVariant", image_path),
        )

    def on_browse_game_dir(self):
        current = self.settings_page.property("gameDirectory")
        start_dir = current if current and Path(current).exists() else str(Path.home())
        game_id = self._get_selected_or_detected_game_id(current or "")
        game_data_folder = get_game(game_id).data_dir_name

        dirname = NativeDialogs.get_directory(
            QCoreApplication.translate("Application", "Select %1 Folder").replace("%1", game_data_folder), start_dir
        )

        if dirname:
            selected_path = normalize_game_data_dir(dirname)
            if not is_valid_game_data_dir(selected_path):
                QMetaObject.invokeMethod(
                    self.root,
                    "showAlertDialog",
                    Qt.QueuedConnection,
                    Q_ARG("QVariant", QCoreApplication.translate("Application", "Invalid Directory")),
                    Q_ARG(
                        "QVariant",
                        QCoreApplication.translate("Application", "Please select the %1 folder.\n\nThis folder should contain 'StreamingAssets' and other game data folders.").replace("%1", game_data_folder),
                    ),
                    Q_ARG("QVariant", ""),
                )
                return

            self.settings_page.setGameDirectory(str(selected_path))

    def on_browse_mods_dir(self):
        current = self.settings_page.property("modsDirectory")
        start_dir = current if current and Path(current).exists() else str(Path.home())

        dirname = NativeDialogs.get_directory(
            QCoreApplication.translate("Application", "Select Mods Directory"), start_dir
        )

        if dirname:
            self.settings_page.setModsDirectory(dirname)

    def on_reset_mods_dir(self):
        self.settings_page.setModsDirectory("")

    def on_auto_detect(self):
        if self.auto_detect_worker and self.auto_detect_worker.isRunning():
            return

        if self.settings_page:
            self.settings_page.setProperty("isAutoDetecting", True)

        game_id = self._get_selected_or_detected_game_id(
            self.settings_page.property("gameDirectory") if self.settings_page else ""
        )
        game = get_game(game_id)

        from gui.main_qml import AutoDetectWorker
        self.auto_detect_worker = AutoDetectWorker(
            platform.system(),
            install_dir_name=game.install_dir_name,
            data_dir_name=game.data_dir_name,
        )
        self.auto_detect_worker.found.connect(self.on_auto_detect_found_settings)
        self.auto_detect_worker.notFound.connect(self.on_auto_detect_not_found_settings)
        self.auto_detect_worker.start()

    def on_auto_detect_found_settings(self, game_data_dir):
        if self.settings_page:
            self.settings_page.setProperty("isAutoDetecting", False)
            self.settings_page.setGameDirectory(game_data_dir)

        QMetaObject.invokeMethod(
            self.root,
            "showSuccessToast",
            Qt.QueuedConnection,
            Q_ARG("QVariant", QCoreApplication.translate("Application", "Found game directory:\n%1").replace("%1", game_data_dir)),
        )

    def on_auto_detect_not_found_settings(self):
        if self.settings_page:
            self.settings_page.setProperty("isAutoDetecting", False)
        game_id = self._get_selected_or_detected_game_id(
            self.settings_page.property("gameDirectory") if self.settings_page else ""
        )
        game_data_folder = get_game(game_id).data_dir_name

        QMetaObject.invokeMethod(
            self.root,
            "showAlertDialog",
            Qt.QueuedConnection,
            Q_ARG("QVariant", QCoreApplication.translate("Application", "Not Found")),
            Q_ARG(
                "QVariant",
                QCoreApplication.translate("Application", "Could not auto-detect game directory.\n\nPlease select the %1 folder manually using the Browse button.").replace("%1", game_data_folder),
            ),
            Q_ARG("QVariant", ""),
        )

    def on_save_settings(self, game_path):
        print(f"[Settings] Saving settings with game path: {game_path}")

        mod_creation_mode = self.settings_page.property("modCreationEnabled")
        enable_gb_thumbnails = self.settings_page.property("enableGbThumbnails")
        hide_gb_thumbnail_warning = self.settings_page.property("hideGbThumbnailWarning")
        custom_mods_dir = self.settings_page.property("modsDirectory") or ""

        try:
            if self.settings_file.exists():
                with open(self.settings_file, "r") as f:
                    settings = json.load(f)
            else:
                settings = {}
        except Exception:
            settings = {}

        settings["mod_creation_mode"] = mod_creation_mode
        settings["enable_gb_thumbnails"] = enable_gb_thumbnails
        settings["hide_gb_thumbnail_warning"] = hide_gb_thumbnail_warning
        current_game = normalize_game_id(
            settings.get("selected_game", DEFAULT_GAME_ID)
        )
        custom_mods_key = get_custom_mod_library_settings_key(current_game)
        settings[custom_mods_key] = custom_mods_dir
        if current_game == DEFAULT_GAME_ID:
            settings["custom_mod_library_dir"] = custom_mods_dir

        # Propagate thumbnailsEnabled to the GameBanana page immediately
        gb_page = self.root.findChild(QObject, "gameBananaPage")
        if gb_page:
            gb_page.setProperty("thumbnailsEnabled", bool(enable_gb_thumbnails))
        saved_game = self._store_game_data_dir_settings(
            settings, game_path, set_active=True
        )
        if saved_game:
            current_game = saved_game
            custom_mods_key = get_custom_mod_library_settings_key(current_game)
            settings[custom_mods_key] = custom_mods_dir
            if current_game == DEFAULT_GAME_ID:
                settings["custom_mod_library_dir"] = custom_mods_dir
            print(f"[Settings] Active game saved: {saved_game}")
        elif game_path:
            QMetaObject.invokeMethod(
                self.root,
                "showAlertDialog",
                Qt.QueuedConnection,
                Q_ARG("QVariant", QCoreApplication.translate("Application", "Invalid Directory")),
                Q_ARG(
                    "QVariant",
                    QCoreApplication.translate("Application", "The game directory is invalid, so it was not saved. All other settings have been saved."),
                ),
                Q_ARG("QVariant", ""),
            )
        elif "selected_game" not in settings:
            settings["selected_game"] = DEFAULT_GAME_ID
        print(f"[Settings] Mod Creation Mode: {mod_creation_mode}")
        print(f"[Settings] Custom mods dir: {custom_mods_dir or '(default)'}")

        try:
            self.settings_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.settings_file, "w") as f:
                json.dump(settings, f, indent=2)

            print(f"[Settings] Settings saved to: {self.settings_file}")

            QMetaObject.invokeMethod(
                self.root,
                "showSuccessToast",
                Qt.QueuedConnection,
                Q_ARG("QVariant", QCoreApplication.translate("Application", "Settings have been saved successfully!")),
            )

            if self.mod_manager_bridge:
                print("[Settings] Reloading mod manager with new paths...")
                self.mod_manager_bridge.load_settings()
                self.mod_manager_bridge.refreshMods()

            active_game = normalize_game_id(
                settings.get("selected_game", DEFAULT_GAME_ID)
            )
            self._set_root_active_game_props(active_game)
            active_data_dir = self._get_saved_game_data_dir(settings, active_game)
            if active_data_dir and self.audio_page:
                QMetaObject.invokeMethod(
                    self.audio_page,
                    "setGameDirectory",
                    Qt.QueuedConnection,
                    Q_ARG("QVariant", active_data_dir),
                )
            if active_data_dir and self.audio_browser_bridge:
                self.audio_browser_bridge.scanLanguageFolders(active_data_dir)

        except Exception as e:
            print(f"[Settings] ERROR: Failed to save settings: {e}")
            QMetaObject.invokeMethod(
                self.root,
                "showAlertDialog",
                Qt.QueuedConnection,
                Q_ARG("QVariant", QCoreApplication.translate("Application", "Error")),
                Q_ARG("QVariant", QCoreApplication.translate("Application", "Failed to save settings:\n\n%1").replace("%1", str(e))),
                Q_ARG("QVariant", ""),
            )

    def check_first_launch(self):
        try:
            if not self.settings_file.exists():
                print(f"[{APP_NAME}] First launch detected - showing welcome dialog")
                QMetaObject.invokeMethod(
                    self.root,
                    "showWelcomeDialog",
                    Qt.QueuedConnection,
                )
                return True
            else:
                print(f"[{APP_NAME}] Settings file exists, skipping welcome dialog")
                return False
        except Exception as e:
            print(f"[{APP_NAME}] Error checking first launch: {e}")
            return False

    def _can_move_language_folder(self, folder_name, persistent_path, streaming_path):
        """Check if a persistent language folder can be moved to streaming.
        Moveable only if the streaming folder does NOT already have this language folder."""
        streaming_folder = streaming_path / folder_name

        streaming_exists = streaming_folder.exists()
        streaming_has_pcks = streaming_exists and any(streaming_folder.glob("*.pck"))
        print(f"[{APP_NAME}] Move check for '{folder_name}': streaming exists={streaming_exists}, has PCKs={streaming_has_pcks}")

        if streaming_has_pcks:
            print(f"[{APP_NAME}]   -> NOT moveable: streaming already has '{folder_name}' with PCK files")
            return False

        print(f"[{APP_NAME}]   -> MOVEABLE")
        return True

    def check_multiple_languages(self):
        try:
            settings = self.load_settings()
            selected_game = normalize_game_id(
                settings.get("selected_game", DEFAULT_GAME_ID)
            )
            game_def = get_game(selected_game)
            if not game_def.check_streaming_pairing:
                print(f"[{APP_NAME}] Skipping language check for game: {selected_game}")
                return

            if settings.get("hide_language_warning", False):
                print(f"[{APP_NAME}] Language warning disabled by user")
                return

            streaming_key, persistent_key = get_audio_settings_keys(selected_game)
            persistent_dir = settings.get(persistent_key, "") or settings.get(
                "persistent_audio_dir", ""
            )
            if not persistent_dir:
                print(f"[{APP_NAME}] No persistent directory configured yet")
                return

            persistent_path = Path(persistent_dir)
            if not persistent_path.exists():
                print(f"[{APP_NAME}] Persistent directory does not exist yet")
                return

            streaming_dir = settings.get(streaming_key, "") or settings.get("game_audio_dir", "")
            streaming_path = Path(streaming_dir) if streaming_dir else None

            language_folders = []
            moveable_folders = []
            for item in persistent_path.iterdir():
                if item.is_dir():
                    pck_files = list(item.glob("*.pck"))
                    if pck_files:
                        language_folders.append(item.name)
                        print(f"[{APP_NAME}] Found language folder: {item.name} with {len(pck_files)} PCK files")

                        if streaming_path and self._can_move_language_folder(item.name, persistent_path, streaming_path):
                            moveable_folders.append(item.name)
                            print(f"[{APP_NAME}] Language folder {item.name} is moveable to streaming")

            # Detect game-pushed PCK files identified by a sibling .hash file
            hash_pcks = []
            if streaming_path:
                for hash_file in persistent_path.glob("*.hash"):
                    pck_name = hash_file.stem.split("_")[0] + ".pck"
                    pck_in_persistent = persistent_path / pck_name
                    pck_in_streaming = streaming_path / pck_name
                    if pck_in_persistent.exists():
                        hash_pcks.append(pck_name)
                        print(f"[{APP_NAME}] Found hash-identified PCK in Persistent (missing from Streaming): {pck_name}")

            if moveable_folders or hash_pcks:
                print(f"[{APP_NAME}] Found moveable language folders: {moveable_folders}, hash PCKs: {hash_pcks}")
                languages_text = ", ".join(language_folders)
                moveable_text = ", ".join(moveable_folders)
                hash_pcks_text = ", ".join(hash_pcks)
                QMetaObject.invokeMethod(
                    self.root,
                    "showMultipleLanguagesWarning",
                    Qt.QueuedConnection,
                    Q_ARG("QVariant", languages_text),
                    Q_ARG("QVariant", moveable_text),
                    Q_ARG("QVariant", hash_pcks_text),
                )
            else:
                print(f"[{APP_NAME}] Language check OK: {len(language_folders)} language folder(s), no hash PCKs, none moveable")
                QMetaObject.invokeMethod(
                    self.root,
                    "hideLanguageWarningDialog",
                    Qt.QueuedConnection,
                )

        except Exception as e:
            print(f"[{APP_NAME}] Error checking multiple languages: {e}")

    def on_move_language_to_streaming(self, folder_name):
        """Move a language folder from Persistent to StreamingAssets."""
        import shutil

        try:
            settings = self.load_settings()
            selected_game = normalize_game_id(
                settings.get("selected_game", DEFAULT_GAME_ID)
            )
            streaming_key, persistent_key = get_audio_settings_keys(selected_game)
            persistent_dir = settings.get(persistent_key, "") or settings.get("persistent_audio_dir", "")
            streaming_dir = settings.get(streaming_key, "") or settings.get("game_audio_dir", "")

            if not persistent_dir or not streaming_dir:
                QMetaObject.invokeMethod(
                    self.root, "showErrorToast", Qt.QueuedConnection,
                    Q_ARG("QVariant", QCoreApplication.translate("Application", "Game directories not configured")),
                )
                return

            persistent_path = Path(persistent_dir)
            streaming_path = Path(streaming_dir)
            source = persistent_path / folder_name
            destination = streaming_path / folder_name

            if not source.exists():
                QMetaObject.invokeMethod(
                    self.root, "showErrorToast", Qt.QueuedConnection,
                    Q_ARG("QVariant", QCoreApplication.translate("Application", "Folder '%1' not found in Persistent").replace("%1", folder_name)),
                )
                return

            if destination.exists() and any(destination.glob("*.pck")):
                QMetaObject.invokeMethod(
                    self.root, "showErrorToast", Qt.QueuedConnection,
                    Q_ARG("QVariant", QCoreApplication.translate("Application", "Folder '%1' already exists in StreamingAssets").replace("%1", folder_name)),
                )
                return

            PROTECTED_PCKS = {'Patch.pck', 'Hotfix.pck'}

            print(f"[{APP_NAME}] Moving language folder: {source} -> {destination}")
            destination.mkdir(parents=True, exist_ok=True)

            skipped = []
            for item in source.iterdir():
                if item.is_file() and item.name in PROTECTED_PCKS:
                    skipped.append(item.name)
                    print(f"[{APP_NAME}] Leaving protected file in Persistent: {item.name}")
                    continue
                shutil.move(str(item), str(destination / item.name))

            if not any(source.iterdir()):
                source.rmdir()
                print(f"[{APP_NAME}] Removed empty source folder: {source}")
            elif skipped:
                print(f"[{APP_NAME}] Source folder kept (contains protected files: {', '.join(skipped)})")

            print(f"[{APP_NAME}] Successfully moved {folder_name} to StreamingAssets")

            QMetaObject.invokeMethod(
                self.root, "showSuccessToast", Qt.QueuedConnection,
                Q_ARG("QVariant", QCoreApplication.translate("Application", "Moved '%1' to StreamingAssets successfully!").replace("%1", folder_name)),
            )

            self.check_multiple_languages()

        except Exception as e:
            print(f"[{APP_NAME}] Error moving language folder: {e}")
            QMetaObject.invokeMethod(
                self.root, "showErrorToast", Qt.QueuedConnection,
                Q_ARG("QVariant", QCoreApplication.translate("Application", "Failed to move '%1': %2").replace("%1", folder_name).replace("%2", str(e))),
            )

    def on_move_hash_pck_to_streaming(self, pck_name):
        """Move a game-pushed PCK file (identified by a .hash file) from Persistent to StreamingAssets."""
        import shutil

        try:
            settings = self.load_settings()
            selected_game = normalize_game_id(
                settings.get("selected_game", DEFAULT_GAME_ID)
            )
            streaming_key, persistent_key = get_audio_settings_keys(selected_game)
            persistent_dir = settings.get(persistent_key, "") or settings.get("persistent_audio_dir", "")
            streaming_dir = settings.get(streaming_key, "") or settings.get("game_audio_dir", "")

            if not persistent_dir or not streaming_dir:
                QMetaObject.invokeMethod(
                    self.root, "showErrorToast", Qt.QueuedConnection,
                    Q_ARG("QVariant", QCoreApplication.translate("Application", "Game directories not configured")),
                )
                return

            persistent_path = Path(persistent_dir)
            streaming_path = Path(streaming_dir)
            source_pck = persistent_path / pck_name
            dest_pck = streaming_path / pck_name

            if not source_pck.exists():
                QMetaObject.invokeMethod(
                    self.root, "showErrorToast", Qt.QueuedConnection,
                    Q_ARG("QVariant", QCoreApplication.translate("Application", "File '%1' not found in Persistent").replace("%1", pck_name)),
                )
                return

            print(f"[{APP_NAME}] Moving hash PCK: {source_pck} -> {dest_pck}")
            shutil.move(str(source_pck), str(dest_pck))

            # Remove the accompanying .hash file(s) from Persistent
            pck_stem = Path(pck_name).stem
            for hash_file in persistent_path.glob(f"{pck_stem}_*.hash"):
                hash_file.unlink()
                print(f"[{APP_NAME}] Removed hash file: {hash_file.name}")

            print(f"[{APP_NAME}] Successfully moved {pck_name} to StreamingAssets")
            QMetaObject.invokeMethod(
                self.root, "showSuccessToast", Qt.QueuedConnection,
                Q_ARG("QVariant", QCoreApplication.translate("Application", "Moved '%1' to StreamingAssets successfully!").replace("%1", pck_name)),
            )

            self.check_multiple_languages()

        except Exception as e:
            print(f"[{APP_NAME}] Error moving hash PCK: {e}")
            QMetaObject.invokeMethod(
                self.root, "showErrorToast", Qt.QueuedConnection,
                Q_ARG("QVariant", QCoreApplication.translate("Application", "Failed to move '%1': %2").replace("%1", pck_name).replace("%2", str(e))),
            )

    def on_welcome_game_selected(self, game_id):
        game_id = normalize_game_id(game_id)
        print(f"[{APP_NAME}] User selected game: {game_id}")
        self._set_root_active_game_props(game_id)
        if self.welcome_dialog:
            game = get_game(game_id)
            self.welcome_dialog.setProperty(
                "currentGameDisplayName", game.display_name
            )

    def on_welcome_mode_selected(self, mode):
        print(f"[{APP_NAME}] User selected mode: {mode}")

        try:
            settings = {}
            if self.settings_file.exists():
                with open(self.settings_file, "r") as f:
                    settings = json.load(f)

            settings["mod_creation_mode"] = (mode == "maker")
            settings["first_launch_complete"] = True

            # Read multi-game selections from the welcome dialog
            # QML var properties arrive as QJSValue; call toVariant() first.
            selected_games = []
            game_dirs_map = {}
            if self.welcome_dialog:
                sg = self.welcome_dialog.property("selectedGames")
                if hasattr(sg, "toVariant"):
                    sg = sg.toVariant()
                selected_games = list(sg) if sg else []
                gd = self.welcome_dialog.property("gameDirectories")
                if hasattr(gd, "toVariant"):
                    gd = gd.toVariant()
                game_dirs_map = dict(gd) if gd else {}

            # Primary game = first selected game
            primary_game = normalize_game_id(selected_games[0]) if selected_games else None
            if primary_game:
                settings["selected_game"] = primary_game

            # Store directories for every selected game
            for gid in selected_games:
                gid = normalize_game_id(gid)
                gdir = game_dirs_map.get(gid, "")
                if gdir:
                    is_primary = (gid == primary_game)
                    self._store_game_data_dir_settings(
                        settings, gdir, set_active=is_primary
                    )

            active_game_id = primary_game or normalize_game_id(
                settings.get("selected_game", DEFAULT_GAME_ID)
            )
            game_dir = self._get_saved_game_data_dir(settings, active_game_id)
            self._set_root_active_game_props(active_game_id)

            self.settings_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.settings_file, "w") as f:
                json.dump(settings, f, indent=4)

            mod_creation = (mode == "maker")
            self.root.setProperty("modCreationEnabled", mod_creation)
            if self.settings_page:
                self.settings_page.setProperty("modCreationEnabled", mod_creation)
                if game_dir:
                    self.settings_page.setGameDirectory(game_dir)

            if game_dir and self.audio_page:
                QMetaObject.invokeMethod(
                    self.audio_page, "setGameDirectory",
                    Qt.QueuedConnection, Q_ARG("QVariant", game_dir),
                )
                if self.audio_browser_bridge:
                    self.audio_browser_bridge.scanLanguageFolders(game_dir)

            self.mod_manager_bridge.setModCreationMode(mod_creation)

            if game_dir:
                self.mod_manager_bridge.load_settings()
                self.mod_manager_bridge.refreshMods()

            QMetaObject.invokeMethod(
                self.root,
                "showSuccessToast",
                Qt.QueuedConnection,
                Q_ARG("QVariant", QCoreApplication.translate("Application", "Welcome setup complete! Settings have been saved.")),
            )

            self.check_multiple_languages()

        except Exception as e:
            print(f"[{APP_NAME}] Error saving welcome mode: {e}")
            QMetaObject.invokeMethod(
                self.root,
                "showErrorToast",
                Qt.QueuedConnection,
                Q_ARG("QVariant", QCoreApplication.translate("Application", "Error saving settings: %1").replace("%1", str(e))),
            )

    def on_start_tutorial(self):
        print(f"[{APP_NAME}] Starting tutorial...")
        self.root.setProperty("tutorialActive", True)
        QMetaObject.invokeMethod(
            self.root,
            "showTutorial",
            Qt.QueuedConnection,
        )

    def on_welcome_browse_game_dir(self):
        print(f"[{APP_NAME}] Welcome browse button clicked!")
        current = self.welcome_dialog.property("gameDirectory")
        start_dir = current if current and Path(current).exists() else str(Path.home())
        welcome_game = self.welcome_dialog.property("selectedGame") if self.welcome_dialog else ""
        if welcome_game:
            game_id = normalize_game_id(welcome_game)
        else:
            game_id = self._get_selected_or_detected_game_id(current or "")
        game_data_folder = get_game(game_id).data_dir_name

        was_visible = self.welcome_dialog.property("visible")
        if was_visible:
            self.welcome_dialog.setProperty("visible", False)
            QApplication.processEvents()

        dirname = NativeDialogs.get_directory(
            QCoreApplication.translate("Application", "Select %1 Folder").replace("%1", game_data_folder), start_dir
        )

        if was_visible:
            self.welcome_dialog.setProperty("visible", True)

        if dirname:
            selected_path = normalize_game_data_dir(dirname)
            if not is_valid_game_data_dir(selected_path):
                QMetaObject.invokeMethod(
                    self.root,
                    "showAlertDialog",
                    Qt.QueuedConnection,
                    Q_ARG("QVariant", QCoreApplication.translate("Application", "Invalid Directory")),
                    Q_ARG(
                        "QVariant",
                        QCoreApplication.translate("Application", "Please select the %1 folder.\n\nThis folder should contain 'StreamingAssets' and other game data folders.").replace("%1", game_data_folder),
                    ),
                    Q_ARG("QVariant", ""),
                )
                return

            QMetaObject.invokeMethod(
                self.welcome_dialog,
                "setGameDirectory",
                Qt.QueuedConnection,
                Q_ARG("QVariant", str(selected_path)),
            )

    def on_welcome_auto_detect(self):
        print(f"[{APP_NAME}] Welcome auto-detect button clicked!")

        if self.auto_detect_worker and self.auto_detect_worker.isRunning():
            return

        if self.welcome_dialog:
            self.welcome_dialog.setProperty("isAutoDetecting", True)

        welcome_game = self.welcome_dialog.property("selectedGame") if self.welcome_dialog else ""
        if welcome_game:
            game_id = normalize_game_id(welcome_game)
        else:
            game_id = self._get_selected_or_detected_game_id(
                self.welcome_dialog.property("gameDirectory") if self.welcome_dialog else ""
            )
        game = get_game(game_id)

        from gui.main_qml import AutoDetectWorker
        self.auto_detect_worker = AutoDetectWorker(
            platform.system(),
            install_dir_name=game.install_dir_name,
            data_dir_name=game.data_dir_name,
        )
        self.auto_detect_worker.found.connect(self.on_auto_detect_found_welcome)
        self.auto_detect_worker.notFound.connect(self.on_auto_detect_not_found_welcome)
        self.auto_detect_worker.start()

    def on_auto_detect_found_welcome(self, game_data_dir):
        if self.welcome_dialog:
            self.welcome_dialog.setProperty("isAutoDetecting", False)
            QMetaObject.invokeMethod(
                self.welcome_dialog,
                "setGameDirectory",
                Qt.QueuedConnection,
                Q_ARG("QVariant", game_data_dir),
            )

        QMetaObject.invokeMethod(
            self.root,
            "showSuccessToast",
            Qt.QueuedConnection,
            Q_ARG("QVariant", QCoreApplication.translate("Application", "Found game directory!")),
        )

    def on_auto_detect_not_found_welcome(self):
        if self.welcome_dialog:
            self.welcome_dialog.setProperty("isAutoDetecting", False)
        welcome_game = self.welcome_dialog.property("selectedGame") if self.welcome_dialog else ""
        if welcome_game:
            game_id = normalize_game_id(welcome_game)
        else:
            game_id = self._get_selected_or_detected_game_id(
                self.welcome_dialog.property("gameDirectory") if self.welcome_dialog else ""
            )
        game_data_folder = get_game(game_id).data_dir_name

        QMetaObject.invokeMethod(
            self.root,
            "showAlertDialog",
            Qt.QueuedConnection,
            Q_ARG("QVariant", QCoreApplication.translate("Application", "Not Found")),
            Q_ARG(
                "QVariant",
                QCoreApplication.translate("Application", "Could not auto-detect game directory.\n\nPlease select the %1 folder manually using the Browse button.").replace("%1", game_data_folder),
            ),
            Q_ARG("QVariant", ""),
        )

    def on_welcome_wwise_status_changed(self, installed):
        if self.welcome_dialog:
            self.welcome_dialog.setProperty("wwiseInstalled", installed)
            self.welcome_dialog.setProperty("isInstallingWwise", False)

    def on_welcome_audio_tools_status_changed(self, installed):
        print(f"[{APP_NAME}] on_welcome_audio_tools_status_changed called: installed={installed}")
        if self.welcome_dialog:
            print(f"[{APP_NAME}] Setting welcome dialog audioToolsInstalled={installed}, isInstallingAudioTools=False")
            self.welcome_dialog.setProperty("audioToolsInstalled", installed)
            self.welcome_dialog.setProperty("isInstallingAudioTools", False)
            print(f"[{APP_NAME}] Welcome dialog properties set successfully")
        else:
            print(f"[{APP_NAME}] WARNING: welcome_dialog is None!")

    def on_language_warning_dont_show_again(self, dont_show):
        try:
            settings = self.load_settings()
            settings["hide_language_warning"] = dont_show

            self.settings_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.settings_file, "w") as f:
                json.dump(settings, f, indent=2)

            print(f"[{APP_NAME}] Language warning preference saved: hide={dont_show}")
        except Exception as e:
            print(f"[{APP_NAME}] Error saving language warning preference: {e}")
