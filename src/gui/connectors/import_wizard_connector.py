from PyQt5.QtCore import QCoreApplication
from pathlib import Path

from PyQt5.QtCore import QObject, QMetaObject, Q_ARG, Qt

from src.core.app_config import APP_NAME

from src.gui.utils.native_dialogs import NativeDialogs
import src.core.app_config as app_config


from src.core.logger import get_logger
logger = get_logger(__name__)

class ImportWizardConnector:

    def _connect_import_wizard(self):
        self.import_wizard = self.root.findChild(QObject, "importWizard")
        if not self.import_wizard:
            return

        self.import_wizard.browseFilesClicked.connect(self.on_wizard_browse_files)
        self.import_wizard.browseFolderClicked.connect(self.on_wizard_browse_folder)
        self.import_wizard.browseThumbnailClicked.connect(
            self.on_wizard_browse_thumbnail
        )
        self.import_wizard.createModClicked.connect(self.on_wizard_create_mod)
        self.import_wizard.wizardCancelled.connect(self.on_wizard_cancelled)
        logger.info(f"[{APP_NAME}] Import wizard connected")

    def on_wizard_browse_files(self, mode):
        logger.info(f"[Import Wizard] Browsing for files, mode: {mode}")

        if mode == "pck_file":
            filter_str = "PCK Files (*.pck);;All Files (*)"
            title = "Select PCK File(s)"
        else:
            filter_str = "WEM Files (*.wem);;All Files (*)"
            title = "Select WEM File(s)"

        files = NativeDialogs.get_open_files(
            title, filter_str=filter_str, remember_key="import_wem_files"
        )

        if files:
            logger.info(f"[Import Wizard] Selected {len(files)} file(s)")
            self.wizard_selected_files = files

            display_names = [Path(f).name for f in files]
            QMetaObject.invokeMethod(
                self.import_wizard,
                "setSelectedFiles",
                Qt.QueuedConnection,
                Q_ARG("QVariant", display_names),
            )
        else:
            logger.info("[Import Wizard] File selection cancelled")

    def on_wizard_browse_folder(self, mode):
        logger.info(f"[Import Wizard] Browsing for folder, mode: {mode}")

        folder = NativeDialogs.get_directory(
            "Select Folder", remember_key="import_folder"
        )

        if folder:
            logger.info(f"[Import Wizard] Selected folder: {folder}")
            self.wizard_selected_folder = folder

            folder_path = Path(folder)
            if mode == "pck_folder":
                files = list(folder_path.rglob("*.pck"))
            else:
                files = list(folder_path.rglob("*.wem"))

            self.wizard_selected_files = [str(f) for f in files]

            display_names = [str(f.relative_to(folder_path)) for f in files]

            logger.info(f"[Import Wizard] Found {len(files)} files in folder (recursive)")

            QMetaObject.invokeMethod(
                self.import_wizard,
                "setSelectedFolder",
                Qt.QueuedConnection,
                Q_ARG("QVariant", folder),
                Q_ARG("QVariant", display_names),
            )
        else:
            logger.info("[Import Wizard] Folder selection cancelled")

    def on_wizard_browse_thumbnail(self):
        logger.info("[Import Wizard] Browsing for thumbnail...")

        file_path = NativeDialogs.get_open_file(
            "Select Thumbnail Image",
            filter_str="Image Files (*.png *.jpg *.jpeg *.bmp *.gif);;All Files (*)",
            remember_key="thumbnail",
        )

        if file_path:
            logger.info(f"[Import Wizard] Selected thumbnail: {file_path}")
            QMetaObject.invokeMethod(
                self.import_wizard,
                "setThumbnailPath",
                Qt.QueuedConnection,
                Q_ARG("QVariant", file_path),
            )
        else:
            logger.info("[Import Wizard] Thumbnail selection cancelled")

    def on_wizard_create_mod(self, wizard_data_js):
        logger.info("[Import Wizard] Creating mod...")

        wizard_data = wizard_data_js.toVariant()
        logger.info(f"[Import Wizard] Data: {wizard_data}")

        settings = self.load_settings()
        game_audio_dir = settings.get("game_audio_dir", "")
        persistent_audio_dir = settings.get("persistent_audio_dir", "")

        if not game_audio_dir or not Path(game_audio_dir).exists():
            self.mod_manager_bridge.errorOccurred.emit(
                "Error",
                "Game audio directory not set. Please configure it in Settings first.",
            )
            return

        save_path = NativeDialogs.get_save_file(
            f"Save {app_config.MOD_FILE_EXT} Mod Package",
            filter_str=f"{app_config.MOD_FILE_EXT_UPPER} Mod Packages (*{app_config.MOD_FILE_EXT})",
            remember_key="save_mod",
            default_filename=f"{wizard_data['modName']}{app_config.MOD_FILE_EXT}",
        )

        if not save_path:
            logger.info("[Import Wizard] Save cancelled")
            return

        if not save_path.endswith(app_config.MOD_FILE_EXT):
            save_path += app_config.MOD_FILE_EXT

        logger.info(f"[Import Wizard] Saving to: {save_path}")

        QMetaObject.invokeMethod(self.import_wizard, "startImporting", Qt.QueuedConnection)

        import_mode = wizard_data["importMode"]
        files_dict = {}

        for file_path in self.wizard_selected_files:
            file_id = Path(file_path).stem
            files_dict[file_id] = {"path": file_path}

        import_data = {
            "import_mode": import_mode,
            "files": files_dict,
            "metadata": {
                "name": wizard_data["modName"],
                "author": wizard_data["modAuthor"],
                "version": wizard_data["modVersion"],
                "description": wizard_data["modDescription"],
            },
            "thumbnail": wizard_data.get("thumbnailPath", ""),
            "save_path": save_path,
        }

        from src.gui.backend.import_worker import ImportWorker

        self.import_worker = ImportWorker(
            import_data,
            game_audio_dir,
            self.mod_manager_bridge.mod_package_manager,
            persistent_audio_dir,
        )

        self.import_worker.progress.connect(self.on_import_progress)
        self.import_worker.progressPercent.connect(self.on_import_percent)
        self.import_worker.finished.connect(self.on_import_finished)
        self.import_worker.start()

    def on_wizard_cancelled(self):
        logger.info("[Import Wizard] Wizard cancelled")
        self.wizard_selected_files = []
        self.wizard_selected_folder = ""

    def on_import_progress(self, message):
        logger.info(f"[Import Worker] {message}")
        if self.import_wizard:
            self.import_wizard.setProperty("importStatus", message)

    def on_import_percent(self, percent):
        if self.import_wizard:
            self.import_wizard.setProperty("importPercent", percent)

    def on_import_finished(self, success, message):
        if self.import_wizard:
            QMetaObject.invokeMethod(self.import_wizard, "finishImporting", Qt.QueuedConnection)

        if success:
            logger.info(f"[Import Worker] Success: {message}")
            self.mod_manager_bridge.progressUpdate.emit(message)
            self.mod_manager_bridge.refreshMods()
        else:
            logger.error(f"[Import Worker] Error: {message}")
            self.mod_manager_bridge.errorOccurred.emit(QCoreApplication.translate("Application", "Import Error"), message)

        self.import_worker = None
        self.wizard_selected_files = []
        self.wizard_selected_folder = ""
