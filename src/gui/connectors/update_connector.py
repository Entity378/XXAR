from PyQt6.QtCore import QCoreApplication
import os

from PyQt6.QtCore import QObject, QMetaObject, Q_ARG, Qt, QCoreApplication
from PyQt6.QtWidgets import QApplication

from src.core.config_manager import get_cache_dir
from src.core.app_config import APP_NAME
from src.core.subprocess_utils import IS_WINDOWS, IS_FLATPAK
import src.core.app_config as app_config
from src.gui.backend.update_manager_bridge import _get_real_exe_path


from src.core.logger import get_logger
logger = get_logger(__name__)

class UpdateConnector:

    def _connect_updates(self):
        if not self.settings_page:
            return

        self.settings_page.setProperty("devMode", app_config.DEBUG)

        settings = self.load_settings()
        self.settings_page.setProperty("githubToken", settings.get("github_token", ""))

        self.settings_page.checkForUpdatesClicked.connect(self._on_check_for_updates)
        self.settings_page.downloadUpdateClicked.connect(
            self.update_manager_bridge.downloadAndInstall
        )
        self.settings_page.restartClicked.connect(self._on_restart_for_update)
        self.settings_page.githubTokenSaved.connect(self._on_github_token_changed)
        self.settings_page.testUpdateDialogClicked.connect(self._on_test_update_dialog)
        self.settings_page.testLanguageDialogClicked.connect(self._on_test_language_dialog)
        if hasattr(self.settings_page, 'redoTutorialClicked'):
            self.settings_page.redoTutorialClicked.connect(self.on_start_tutorial)

        self.update_manager_bridge.updateAvailable.connect(self._on_update_available)
        self.update_manager_bridge.updateNotAvailable.connect(self._on_update_not_available)
        self.update_manager_bridge.updateProgress.connect(self._on_update_progress)
        self.update_manager_bridge.updateDownloaded.connect(self._on_update_downloaded)
        self.update_manager_bridge.updateError.connect(self._on_update_error)
        self.update_manager_bridge.updateApplied.connect(self._on_update_applied)

        logger.info(f"[{APP_NAME}]Settings page connected")

    def _on_check_for_updates(self):
        if self.settings_page:
            self.settings_page.setProperty("isCheckingUpdates", True)
            self.settings_page.setProperty("updateAvailable", False)
            self.settings_page.setProperty("updateDownloaded", False)
        self.update_manager_bridge.checkForUpdates()

    def _on_update_available(self, version, release_notes):
        logger.info(f"[{APP_NAME}]Update available: {version}")
        if self.settings_page:
            self.settings_page.setProperty("isCheckingUpdates", False)
            self.settings_page.setProperty("updateAvailable", True)
            self.settings_page.setProperty("latestVersion", version)

        if IS_FLATPAK:
            if self._startup_update_check:
                QMetaObject.invokeMethod(
                    self.root,
                    "showAlertDialog",
                    Qt.ConnectionType.QueuedConnection,
                    Q_ARG("QVariant", QCoreApplication.translate("Application", "Update Available -- v%1").replace("%1", version)),
                    Q_ARG("QVariant",
                           QCoreApplication.translate("Application", "A new version of XXAR is available!\n\n"
                           "Update your Flatpak to the latest version:\n\n"
                           "new .flatpak file can be downloaded from https://github.com/Entity378/XXAR/releases")),
                    Q_ARG("QVariant", ""),
                )
        elif self._startup_update_check and self.update_dialog:
            QMetaObject.invokeMethod(
                self.root,
                "showUpdateDialog",
                Qt.ConnectionType.QueuedConnection,
                Q_ARG("QVariant", version),
                Q_ARG("QVariant", release_notes),
            )
        self._startup_update_check = False

    def _on_update_not_available(self):
        logger.info(f"[{APP_NAME}]Already up to date")
        was_startup = self._startup_update_check
        self._startup_update_check = False
        if self.settings_page:
            self.settings_page.setProperty("isCheckingUpdates", False)
            self.settings_page.setProperty("updateAvailable", False)
        if not was_startup:
            QMetaObject.invokeMethod(
                self.root,
                "showSuccessToast",
                Qt.ConnectionType.QueuedConnection,
                Q_ARG("QVariant", QCoreApplication.translate("Application", "You're running the latest version!")),
            )

    def _on_update_progress(self, percent):
        if self.settings_page:
            self.settings_page.setProperty("downloadPercent", percent)
        if self.update_dialog:
            self.update_dialog.setProperty("downloadPercent", percent)

    def _on_update_downloaded(self):
        logger.info(f"[{APP_NAME}]Update downloaded, ready to install")
        if self.settings_page:
            self.settings_page.setProperty("isDownloadingUpdate", False)
            self.settings_page.setProperty("updateDownloaded", True)
        if self.update_dialog and self.update_dialog.property("visible"):
            self.update_dialog.setProperty("isDownloading", False)
            QMetaObject.invokeMethod(self.update_dialog, "hide", Qt.ConnectionType.QueuedConnection)
            self._on_restart_for_update()

    def _on_update_error(self, message):
        logger.error(f"[{APP_NAME}]Update error: {message}")
        was_startup = self._startup_update_check
        self._startup_update_check = False
        if self.settings_page:
            self.settings_page.setProperty("isCheckingUpdates", False)
            self.settings_page.setProperty("isDownloadingUpdate", False)
        if self.update_dialog and self.update_dialog.property("visible"):
            self.update_dialog.setProperty("isDownloading", False)
            QMetaObject.invokeMethod(self.update_dialog, "hide", Qt.ConnectionType.QueuedConnection)
        if not was_startup:
            QMetaObject.invokeMethod(
                self.root,
                "showErrorToast",
                Qt.ConnectionType.QueuedConnection,
                Q_ARG("QVariant", QCoreApplication.translate("Application", "Update error: %1").replace("%1", message)),
            )

    def _on_github_token_changed(self, token):
        self.update_manager_bridge.setGithubToken(token)
        QMetaObject.invokeMethod(
            self.root,
            "showSuccessToast",
            Qt.ConnectionType.QueuedConnection,
            Q_ARG("QVariant", QCoreApplication.translate("Application", "GitHub token saved")),
        )

    def _on_test_update_dialog(self):
        logger.info(f"[{APP_NAME}]Test update dialog triggered")
        if self.update_dialog:
            QMetaObject.invokeMethod(
                self.root,
                "showUpdateDialog",
                Qt.ConnectionType.QueuedConnection,
                Q_ARG("QVariant", "99.0.0"),
                Q_ARG("QVariant", "## Test Release\n\n- This is a test changelog entry\n- Another cool feature\n- Bug fixes and improvements\n\nThis dialog is for testing only."),
            )

    def _on_test_language_dialog(self):
        logger.info(f"[{APP_NAME}]Test language dialog triggered")
        QMetaObject.invokeMethod(
            self.root,
            "showMultipleLanguagesWarning",
            Qt.ConnectionType.QueuedConnection,
            Q_ARG("QVariant", "English, Japanese"),
            Q_ARG("QVariant", "English"),
            Q_ARG("QVariant", "External0.pck"),
        )

    def _on_update_dialog_accepted(self):
        logger.info(f"[{APP_NAME}]User accepted update from dialog")
        self.update_manager_bridge.downloadAndInstall()

    def _on_update_dialog_dismissed(self):
        logger.info(f"[{APP_NAME}]User dismissed update dialog")

    def _on_restart_for_update(self):
        logger.info(f"[{APP_NAME}]Applying update and restarting...")
        self.update_manager_bridge.applyUpdate()

    def _on_update_applied(self):
        logger.info(f"[{APP_NAME}]Update applied successfully, restarting application...")
        try:
            flag_file = get_cache_dir() / "update_success"
            flag_file.parent.mkdir(parents=True, exist_ok=True)
            flag_file.write_text(QCoreApplication.applicationVersion())
            logger.info(f"[{APP_NAME}]Update success flag written: {flag_file}")
        except Exception as e:
            logger.error(f"[{APP_NAME}]Failed to write update success flag: {e}")

        if IS_WINDOWS:
            QApplication.quit()
        else:
            exe = _get_real_exe_path()
            logger.info(f"[{APP_NAME}]Launching updated binary: {exe}")
            import subprocess
            subprocess.Popen(
                [exe],
                start_new_session=True,
            )
            QApplication.quit()

    def _check_update_success_flag(self):
        try:
            flag_file = get_cache_dir() / "update_success"
            if flag_file.exists():
                old_version = flag_file.read_text().strip()
                flag_file.unlink()
                new_version = QCoreApplication.applicationVersion()
                logger.info(f"[{APP_NAME}]Update success! {old_version} -> {new_version}")
                QMetaObject.invokeMethod(
                    self.root,
                    "showSuccessDialog",
                    Qt.ConnectionType.QueuedConnection,
                    Q_ARG("QVariant", QCoreApplication.translate("Application", "Update Successful!")),
                    Q_ARG("QVariant", QCoreApplication.translate("Application", "XXAR has been updated to version %1.").replace("%1", new_version)),
                    Q_ARG("QVariant", f"../assets/{app_config.ASSETS_DIR}/VivianHappy.png"),
                )
        except Exception as e:
            logger.error(f"[{APP_NAME}]Error checking update success flag: {e}")
