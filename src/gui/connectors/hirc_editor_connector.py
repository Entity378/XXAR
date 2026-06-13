from PyQt6.QtCore import Q_ARG, QMetaObject, QObject, Qt

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
        page = self.hirc_editor_page

        page.refreshRequested.connect(db.refreshBnkList)
        page.bnkSelected.connect(db.loadBnkHirc)
        page.refreshMusicPcksRequested.connect(db.listMusicPcks)
        page.browseWemFileRequested.connect(self._on_hirc_editor_browse_wem)

        page.stageAddWemRequested.connect(db.stageAddWem)
        page.stageTrackRequested.connect(db.stageTrackEdits)
        page.showChangesRequested.connect(db.showDraftChanges)
        page.removeMediaAddRequested.connect(db.removeDraftMediaAdd)
        page.removeTrackPatchRequested.connect(db.removeDraftTrackPatch)
        page.editTrackLoopRequested.connect(db.setDraftTrackLoop)
        page.editTrackVolumeRequested.connect(db.setDraftTrackVolume)
        page.editRemapTargetRequested.connect(db.setDraftRemapTarget)
        page.applyAllRequested.connect(db.applyDraftLive)
        page.exportModRequested.connect(db.exportDraftAsMod)
        page.resetDraftRequested.connect(db.resetDraft)
        page.browseThumbnailRequested.connect(db.browseThumbnail)
        page.createModRequested.connect(db.createModPackage)

        db.bnkListReady.connect(lambda data: self._invoke(page, "setBnkList", data))
        db.bnkHircReady.connect(
            lambda pck, bnk_id, objs: QMetaObject.invokeMethod(
                page, "setBnkHirc", Qt.ConnectionType.QueuedConnection,
                Q_ARG("QVariant", pck), Q_ARG("QVariant", int(bnk_id)),
                Q_ARG("QVariant", objs),
            )
        )
        db.statusUpdate.connect(lambda msg: self._invoke(page, "setStatusText", msg))
        db.errorOccurred.connect(self._on_hirc_editor_error)
        db.inspectorCleared.connect(
            lambda: QMetaObject.invokeMethod(
                page, "clearInspector", Qt.ConnectionType.QueuedConnection
            )
        )
        db.musicPckListReady.connect(lambda data: self._invoke(page, "setMusicPckList", data))

        db.draftChangesCount.connect(lambda n: self._invoke(page, "setDraftCount", int(n)))
        db.draftChangesReady.connect(lambda data: self._invoke(page, "setDraftChanges", data))
        db.exportMetadataDialogReady.connect(lambda prefill: self._invoke(page, "openExportDialog", prefill))
        db.thumbnailPathSelected.connect(lambda p: self._invoke(page, "setThumbnailPath", p))
        db.wemStaged.connect(lambda pck, wid, sname: self._invoke(page, "onWemStaged", sname))
        db.draftApplied.connect(
            lambda ok, msg: QMetaObject.invokeMethod(
                page, "onDraftApplied", Qt.ConnectionType.QueuedConnection,
                Q_ARG("QVariant", bool(ok)), Q_ARG("QVariant", msg),
            )
        )
        db.modExported.connect(
            lambda ok, msg: QMetaObject.invokeMethod(
                page, "onModExported", Qt.ConnectionType.QueuedConnection,
                Q_ARG("QVariant", bool(ok)), Q_ARG("QVariant", msg),
            )
        )

        try:
            db.listMusicPcks()
        except Exception as e:
            logger.warning(f"[HIRC Editor] Initial pck list failed: {e}")
        try:
            db.refreshDraft()
        except Exception as e:
            logger.warning(f"[HIRC Editor] Initial draft load failed: {e}")

        # skip the full bnk scan when the editor tab is disabled (mounted-but-hidden)
        if bool(self.root.property("hircEditorTabEnabled")):
            try:
                db.refreshBnkList()
            except Exception as e:
                logger.warning(f"[HIRC Editor] Initial bnk refresh failed: {e}")

        logger.info("[HIRC Editor] Page connected")

    def _invoke(self, page, method, arg):
        QMetaObject.invokeMethod(
            page, method, Qt.ConnectionType.QueuedConnection, Q_ARG("QVariant", arg)
        )

    def _on_hirc_editor_browse_wem(self):
        files = NativeDialogs.get_open_files(
            "Select an audio file",
            filter_str="Audio Files (*.wav *.mp3 *.ogg *.flac *.m4a *.wem);;All Files (*)",
            remember_key="hirc_editor_wem_add",
        )
        if not files:
            return
        self._invoke(self.hirc_editor_page, "setWemAddPath", files[0])

    def _on_hirc_editor_error(self, title, body):
        try:
            self._invoke(self.hirc_editor_page, "setStatusText", f"ERROR — {title}: {body}")
        except Exception:
            logger.error(f"[HIRC Editor] {title}: {body}")
