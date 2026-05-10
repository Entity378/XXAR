

import os
import subprocess
from PyQt5.QtCore import QObject, QMetaObject, Q_ARG, Qt

from src.core.app_config import APP_NAME
from src.core.subprocess_utils import IS_WINDOWS

from src.core.logger import get_logger
logger = get_logger(__name__)

class GameBananaConnector:
    

    def _connect_gamebanana(self):
        
        self.gamebanana_page = self.root.findChild(QObject, "gameBananaPage")
        if not self.gamebanana_page:
            logger.info(f"[{APP_NAME}] GameBanana page not found")
            return

        gb = self.gamebanana_bridge

        self.gamebanana_page.loadModsRequested.connect(gb.fetchMods)
        self.gamebanana_page.modCardClicked.connect(lambda mod_id: gb.fetchModDetails(mod_id))
        self.gamebanana_page.refreshRequested.connect(gb.refresh)
        self.gamebanana_page.downloadModRequested.connect(
            lambda url, filename, mod_name, mod_id: gb.downloadMod(url, filename, mod_name, mod_id)
        )
        self.gamebanana_page.installChosenModRequested.connect(gb.installChosenMod)

        gb.modsLoaded.connect(
            lambda mods: QMetaObject.invokeMethod(
                self.gamebanana_page, "onModsLoaded",
                Qt.QueuedConnection, Q_ARG("QVariant", mods)
            )
        )

        gb.totalModsCount.connect(
            lambda count: QMetaObject.invokeMethod(
                self.gamebanana_page, "onTotalModsCount",
                Qt.QueuedConnection, Q_ARG("QVariant", count)
            )
        )

        gb.modDetailsLoaded.connect(
            lambda details: QMetaObject.invokeMethod(
                self.gamebanana_page, "onModDetailsLoaded",
                Qt.QueuedConnection, Q_ARG("QVariant", details)
            )
        )

        gb.loadingStateChanged.connect(
            lambda loading: QMetaObject.invokeMethod(
                self.gamebanana_page, "setLoadingState",
                Qt.QueuedConnection, Q_ARG("QVariant", loading)
            )
        )

        gb.downloadProgress.connect(
            lambda progress: QMetaObject.invokeMethod(
                self.gamebanana_page, "onDownloadProgress",
                Qt.QueuedConnection, Q_ARG("QVariant", progress)
            )
        )

        gb.downloadComplete.connect(self.on_gamebanana_download_complete)
        gb.installComplete.connect(self.on_gamebanana_install_complete)
        gb.multipleModsFound.connect(self.on_gamebanana_multiple_mods)
        gb.installStateChanged.connect(
            lambda installing: QMetaObject.invokeMethod(
                self.gamebanana_page, "setInstallState",
                Qt.QueuedConnection, Q_ARG("QVariant", installing)
            )
        )

        gb.thumbnailUpdated.connect(
            lambda mod_id, url: QMetaObject.invokeMethod(
                self.gamebanana_page, "onThumbnailUpdated",
                Qt.QueuedConnection, Q_ARG("QVariant", mod_id), Q_ARG("QVariant", url)
            )
        )

        gb.downloadCountUpdated.connect(
            lambda mod_id, count: QMetaObject.invokeMethod(
                self.gamebanana_page, "onDownloadCountUpdated",
                Qt.QueuedConnection, Q_ARG("QVariant", mod_id), Q_ARG("QVariant", count)
            )
        )

        gb.modSupportUpdated.connect(
            lambda mod_id, supported: QMetaObject.invokeMethod(
                self.gamebanana_page, "onModSupportUpdated",
                Qt.QueuedConnection, Q_ARG("QVariant", mod_id), Q_ARG("QVariant", supported)
            )
        )

        gb.installedModsChanged.connect(
            lambda names: QMetaObject.invokeMethod(
                self.gamebanana_page, "onInstalledModsChanged",
                Qt.QueuedConnection, Q_ARG("QVariant", names)
            )
        )

        gb.errorOccurred.connect(self.on_error_occurred)
        gb.nonNativeDownloadComplete.connect(self.on_non_native_download_complete)

        mod_dialog = self.gamebanana_page.findChild(QObject, "modDialog")
        if mod_dialog:
            mod_dialog.downloadToPathRequested.connect(gb.downloadModToPath)

        self.root.dialogConfirmed.connect(self.on_gamebanana_dialog_confirmed)

        self._non_native_saved_path = ""

        logger.info(f"[{APP_NAME}] GameBanana page connected")

    def on_non_native_download_complete(self, file_path):
        self._non_native_saved_path = file_path
        QMetaObject.invokeMethod(
            self.root, "showConfirmDialog",
            Qt.QueuedConnection,
            Q_ARG("QVariant", "Download Complete"),
            Q_ARG("QVariant", f"Saved to:\n{file_path}\n\nOpen containing folder?"),
            Q_ARG("QVariant", "open_non_native_folder"),
            Q_ARG("QVariant", "")
        )

    def on_gamebanana_dialog_confirmed(self, action_id):
        if action_id == "open_non_native_folder" and self._non_native_saved_path:
            folder = os.path.dirname(self._non_native_saved_path)
            if IS_WINDOWS:
                os.startfile(folder)
            else:
                subprocess.Popen(["xdg-open", folder])
            self._non_native_saved_path = ""

    def on_gamebanana_download_complete(self, file_path):
        logger.info(f"[{APP_NAME}] Mod downloaded to: {file_path}")

    def on_gamebanana_install_complete(self, message):
        QMetaObject.invokeMethod(
            self.root,
            "showSuccessToast",
            Qt.QueuedConnection,
            Q_ARG("QVariant", message)
        )
        self.mod_manager_bridge.refreshMods()
        logger.info(f"[{APP_NAME}] {message}")

    def on_gamebanana_multiple_mods(self, mod_names, zip_path):
        QMetaObject.invokeMethod(
            self.gamebanana_page, "showModChooser",
            Qt.QueuedConnection,
            Q_ARG("QVariant", mod_names),
            Q_ARG("QVariant", zip_path)
        )

