from PyQt5.QtCore import QObject, QMetaObject, Q_ARG, Qt

from src.core.logger import get_logger
from src.gui.utils.native_dialogs import NativeDialogs

logger = get_logger(__name__)


class HircEditorConnector:

    def _connect_hirc_editor(self):
        self.hirc_editor_page = self.root.findChild(QObject, "hircEditorPage")
        if not self.hirc_editor_page:
            logger.info("[HIRC Editor] hircEditorPage not present (page disabled)")
            return

        db = self.hirc_editor_bridge

        self.hirc_editor_page.refreshRequested.connect(db.refreshBnkList)
        self.hirc_editor_page.bnkSelected.connect(db.loadBnkHirc)
        self.hirc_editor_page.patchSourceRequested.connect(db.patchSourceId)
        self.hirc_editor_page.patchLoopRequested.connect(db.patchLoopMs)
        self.hirc_editor_page.patchVolumeRequested.connect(db.patchVolumeDb)
        self.hirc_editor_page.refreshMusicPcksRequested.connect(db.listMusicPcks)
        self.hirc_editor_page.browseWemFileRequested.connect(self._on_hirc_editor_browse_wem)
        self.hirc_editor_page.addWemRequested.connect(db.addWemToPck)

        db.bnkListReady.connect(
            lambda data: QMetaObject.invokeMethod(
                self.hirc_editor_page,
                "setBnkList",
                Qt.QueuedConnection,
                Q_ARG("QVariant", data),
            )
        )
        db.bnkHircReady.connect(
            lambda pck, bnk_id, objs: QMetaObject.invokeMethod(
                self.hirc_editor_page,
                "setBnkHirc",
                Qt.QueuedConnection,
                Q_ARG("QVariant", pck),
                Q_ARG("QVariant", int(bnk_id)),
                Q_ARG("QVariant", objs),
            )
        )
        db.statusUpdate.connect(
            lambda msg: QMetaObject.invokeMethod(
                self.hirc_editor_page,
                "setStatusText",
                Qt.QueuedConnection,
                Q_ARG("QVariant", msg),
            )
        )
        db.errorOccurred.connect(self._on_hirc_editor_error)
        db.patchApplied.connect(
            lambda pck, off, old, new: QMetaObject.invokeMethod(
                self.hirc_editor_page,
                "onPatchApplied",
                Qt.QueuedConnection,
                Q_ARG("QVariant", pck),
                Q_ARG("QVariant", int(off)),
                Q_ARG("QVariant", int(old)),
                Q_ARG("QVariant", int(new)),
            )
        )
        db.loopPatchApplied.connect(
            lambda pck, bnk_id, track_id, ms: QMetaObject.invokeMethod(
                self.hirc_editor_page,
                "onLoopPatched",
                Qt.QueuedConnection,
                Q_ARG("QVariant", pck),
                Q_ARG("QVariant", int(bnk_id)),
                Q_ARG("QVariant", int(track_id)),
                Q_ARG("QVariant", float(ms)),
            )
        )
        db.volumePatchApplied.connect(
            lambda pck, off, db_val: QMetaObject.invokeMethod(
                self.hirc_editor_page,
                "onVolumePatched",
                Qt.QueuedConnection,
                Q_ARG("QVariant", pck),
                Q_ARG("QVariant", int(off)),
                Q_ARG("QVariant", float(db_val)),
            )
        )
        db.musicPckListReady.connect(
            lambda data: QMetaObject.invokeMethod(
                self.hirc_editor_page,
                "setMusicPckList",
                Qt.QueuedConnection,
                Q_ARG("QVariant", data),
            )
        )
        db.wemAdded.connect(
            lambda pck, wid, src: QMetaObject.invokeMethod(
                self.hirc_editor_page,
                "onWemAdded",
                Qt.QueuedConnection,
                Q_ARG("QVariant", pck),
                Q_ARG("QVariant", int(wid)),
                Q_ARG("QVariant", src),
            )
        )
        try:
            db.listMusicPcks()
        except Exception as e:
            logger.warning(f"[HIRC Editor] Initial pck list failed: {e}")

        # Only kick off the bnk scan when the user actually has the editor on;
        # otherwise the page is mounted-but-hidden and we'd waste a full scan.
        if bool(self.root.property("hircEditorTabEnabled")):
            try:
                db.refreshBnkList()
            except Exception as e:
                logger.warning(f"[HIRC Editor] Initial bnk refresh failed: {e}")

        logger.info("[HIRC Editor] Page connected")

    def _on_hirc_editor_browse_wem(self):
        files = NativeDialogs.get_open_files(
            "Select a WEM file",
            filter_str="WEM files (*.wem);;All files (*)",
            remember_key="hirc_editor_wem_add",
        )
        if not files:
            return
        path = files[0]
        QMetaObject.invokeMethod(
            self.hirc_editor_page,
            "setWemAddPath",
            Qt.QueuedConnection,
            Q_ARG("QVariant", path),
        )

    def _on_hirc_editor_error(self, title, body):
        try:
            QMetaObject.invokeMethod(
                self.hirc_editor_page,
                "setStatusText",
                Qt.QueuedConnection,
                Q_ARG("QVariant", f"ERROR — {title}: {body}"),
            )
        except Exception:
            logger.error(f"[HIRC Editor] {title}: {body}")
