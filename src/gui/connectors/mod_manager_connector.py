from PyQt5.QtCore import QCoreApplication
import sys
import subprocess
from pathlib import Path
from src.core.app_config import APP_NAME

from PyQt5.QtCore import QObject, QMetaObject, Q_ARG, Qt

from src.gui.utils.native_dialogs import NativeDialogs
import src.core.app_config as app_config
from src.core.subprocess_utils import IS_WINDOWS


from src.core.logger import get_logger
logger = get_logger(__name__)

class ModManagerConnector:

    def _connect_mod_manager(self):
        root = self.root
        mod_page = root.findChild(QObject, "modManagerPage")

        self.mod_manager_bridge.progressUpdate.connect(self.on_progress_update)
        self.mod_manager_bridge.errorOccurred.connect(self.on_error_occurred)
        self.mod_manager_bridge.alertDialogRequested.connect(self.on_alert_dialog_requested)

        if not mod_page:
            return

        self.mod_page = mod_page

        self.mod_manager_bridge.modsLoaded.connect(
            lambda mods: QMetaObject.invokeMethod(
                mod_page, "loadMods",
                Qt.QueuedConnection,
                Q_ARG("QVariant", mods)
            )
        )
        self.mod_manager_bridge.refreshMods()

        mod_page.installModClicked.connect(self.on_install_mod_clicked)
        mod_page.importModClicked.connect(self.on_import_mod_clicked)
        mod_page.removeModsClicked.connect(self.on_remove_mods_clicked)
        mod_page.refreshClicked.connect(self.mod_manager_bridge.refreshMods)
        mod_page.openFolderClicked.connect(self.on_open_folder_clicked)
        mod_page.applyModsClicked.connect(self.mod_manager_bridge.applyMods)
        mod_page.testPermissionDialogClicked.connect(self._on_test_permission_dialog)
        mod_page.modToggled.connect(self.on_mod_toggled)
        mod_page.modSelected.connect(self.on_mod_selected)
        mod_page.moreInfoClicked.connect(self.on_more_info_clicked)

        root.dialogConfirmed.connect(self.on_dialog_confirmed)
        root.dialogCancelled.connect(self.on_dialog_cancelled)
        root.conflictsResolved.connect(self.on_conflicts_resolved)
        root.languageWarningDontShowAgain.connect(self.on_language_warning_dont_show_again)
        root.moveLanguageToStreaming.connect(self.on_move_language_to_streaming)
        root.moveHashPckToStreaming.connect(self.on_move_hash_pck_to_streaming)

        mod_page.setProperty("modManager", self.mod_manager_bridge)

        mod_page.setProperty("devMode", app_config.DEBUG)

        logger.info(f"[{APP_NAME}] Mod manager page connected")

    def _on_test_permission_dialog(self):
        self.on_alert_dialog_requested(
            QCoreApplication.translate("Application", "Permission Denied"),
            QCoreApplication.translate("Application", "%1 does not have permission to write to the game folder.\n\nTry one of the following:\n* Run %1 as Administrator\n* Repair your game files in the launcher").replace("%1", APP_NAME),
            ""
        )

    def on_install_mod_clicked(self):
        logger.info("[Mod Manager] Opening file dialog for mod installation...")

        file_paths = NativeDialogs.get_open_files(
            QCoreApplication.translate("Application", "Select %1 Mod Package(s)").replace("%1", app_config.MOD_FILE_EXT),
            filter_str=QCoreApplication.translate("Application", "%1 Mod Packages (*%2);;ZIP Files (*.zip);;All Files (*)").replace("%1", app_config.MOD_FILE_EXT_UPPER).replace("%2", app_config.MOD_FILE_EXT),
            remember_key="install_mod",
        )

        if file_paths:
            logger.info(f"[Mod Manager] Installing {len(file_paths)} mod(s)...")
            for file_path in file_paths:
                logger.info(f"[Mod Manager] Installing mod from: {file_path}")
                self.mod_manager_bridge.installMod(file_path)
        else:
            logger.info("[Mod Manager] Installation cancelled")

    def on_import_mod_clicked(self):
        logger.info("[Import Wizard] Opening import wizard...")
        if self.import_wizard:
            QMetaObject.invokeMethod(self.import_wizard, "show", Qt.QueuedConnection)
        else:
            logger.error("[Import Wizard] ERROR: Import wizard not found")
            self.mod_manager_bridge.errorOccurred.emit(
                QCoreApplication.translate("Application", "Error"), QCoreApplication.translate("Application", "Import wizard component not found")
            )

    def on_remove_mods_clicked(self, mod_uuids):
        uuids = mod_uuids.toVariant()
        if not uuids:
            logger.info("[Mod Manager] No mods selected for removal")
            self.mod_manager_bridge.progressUpdate.emit(
                QCoreApplication.translate("Application", "Select one or more mods from the list first")
            )
            return

        self.pending_remove_uuids = uuids
        count = len(uuids)
        logger.info(f"[Mod Manager] Requesting removal of {count} mod(s)")

        if count == 1:
            title = QCoreApplication.translate("Application", "Remove Mod?")
            message = QCoreApplication.translate("Application", "Are you sure you want to remove this mod? This cannot be undone.")
        else:
            title = QCoreApplication.translate("Application", "Remove %1 Mods?").replace("%1", str(count))
            message = QCoreApplication.translate("Application", "Are you sure you want to remove %1 mods? This cannot be undone.").replace("%1", str(count))

        QMetaObject.invokeMethod(
            self.root,
            "showConfirmDialog",
            Qt.QueuedConnection,
            Q_ARG("QVariant", title),
            Q_ARG("QVariant", message),
            Q_ARG("QVariant", "remove_mod"),
            Q_ARG("QVariant", ""),
        )

    def on_dialog_confirmed(self, action_id):
        logger.info(f"[Dialog] Confirmed action: {action_id}")

        if action_id == "remove_mod":
            uuids = getattr(self, 'pending_remove_uuids', [])
            if uuids:
                logger.info(f"[Mod Manager] Removing {len(uuids)} mod(s)")
                self.mod_manager_bridge.removeMods(uuids)
                self.pending_remove_uuids = []
            else:
                logger.error("[Mod Manager] Error: No mods pending for removal")
        elif action_id == "wwise_setup":
            logger.info("[Wwise Setup] User confirmed, starting download and installation")
            self.mod_manager_bridge.startWwiseSetup()

    def on_dialog_cancelled(self, action_id):
        logger.info(f"[Dialog] Cancelled action: {action_id}")

        if action_id == "wwise_setup":
            logger.info("[Wwise Setup] User cancelled, resetting installation state")
            if self.settings_page:
                self.settings_page.setProperty("isInstallingWwise", False)
            if self.welcome_dialog:
                self.welcome_dialog.setProperty("isInstallingWwise", False)

    def on_conflicts_detected(self, conflicts):
        logger.info(f"[Mod Manager] Showing per-file conflict resolution dialog with {len(conflicts)} conflicts")
        QMetaObject.invokeMethod(
            self.root,
            "showConflictResolutionDialog",
            Qt.QueuedConnection,
            Q_ARG("QVariant", conflicts),
        )

    def on_mod_conflicts_detected(self, mod_conflicts, file_conflicts):
        logger.info(f"[Mod Manager] Showing per-mod conflict dialog with {len(mod_conflicts)} mod conflict(s)")
        QMetaObject.invokeMethod(
            self.root,
            "showModConflictDialog",
            Qt.QueuedConnection,
            Q_ARG("QVariant", mod_conflicts),
            Q_ARG("QVariant", file_conflicts),
        )

    def on_conflicts_resolved(self):
        logger.info("[Mod Manager] Conflicts resolved by user, continuing with mod application")
        self.mod_manager_bridge.applyModsAfterConflictResolution()

    def on_open_folder_clicked(self):
        mod_folder = Path(self.mod_manager_bridge.getModLibraryPath())
        mod_folder.mkdir(parents=True, exist_ok=True)
        logger.info(f"[Mod Manager] Opening mod folder: {mod_folder}")

        try:
            if IS_WINDOWS:
                subprocess.Popen(["explorer", str(mod_folder)])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(mod_folder)])
            else:
                env = NativeDialogs._get_clean_env()
                subprocess.Popen(
                    ["xdg-open", str(mod_folder)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    stdin=subprocess.DEVNULL,
                    start_new_session=True,
                    env=env
                )

            logger.info(f"[Mod Manager] Opened: {mod_folder}")
            self.mod_manager_bridge.progressUpdate.emit(f"Opened: {mod_folder}")
        except Exception as e:
            logger.error(f"[Mod Manager] ERROR: Could not open folder: {e}")
            self.mod_manager_bridge.errorOccurred.emit(
                QCoreApplication.translate("Application", "Error"), QCoreApplication.translate("Application", "Could not open folder: %1").replace("%1", str(e))
            )

    def on_mod_toggled(self, mod_uuid, enabled):
        state = "enabled" if enabled else "disabled"
        logger.info(f"[Mod Manager] Mod {state}: {mod_uuid}")
        self.mod_manager_bridge.setModEnabled(mod_uuid, enabled)

    def on_mod_selected(self, mod_uuid):
        logger.info(f"[Mod Manager] Mod clicked: {mod_uuid}")

    def on_more_info_clicked(self, mod_uuid):
        logger.info(f"[Mod Manager] More info clicked for: {mod_uuid}")

        if not self.mod_info_dialog:
            logger.error("[Mod Manager] ERROR: Mod info dialog not found")
            return

        mod_info = self.mod_manager_bridge.getModInfo(mod_uuid)

        if mod_info:
            QMetaObject.invokeMethod(
                self.mod_info_dialog,
                "setModInfo",
                Qt.QueuedConnection,
                Q_ARG("QVariant", mod_info),
            )
            QMetaObject.invokeMethod(self.mod_info_dialog, "show", Qt.QueuedConnection)
        else:
            logger.error(f"[Mod Manager] ERROR: Could not find mod info for {mod_uuid}")
