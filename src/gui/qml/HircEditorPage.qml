import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import "../components"
import "."

Item {
    id: hircEditorPage
    objectName: "hircEditorPage"
    clip: true

    // Public signals
    signal refreshRequested()
    signal bnkSelected(string pckName, var bnkId)
    signal refreshMusicPcksRequested()
    signal browseWemFileRequested()
    // Mod-draft staging that mirrors the Browser tab.
    // Apply Changes lives inside the changes overlay.
    signal stageAddWemRequested(string pckName, var wemId, string audioFilePath, var langId)
    signal stageTrackRequested(string pckName, var bnkId, var trackObjId, string remapsJson, string loopMs, string volumeDb)
    signal showChangesRequested()
    signal removeMediaAddRequested(string pckName, var wemId)
    signal removeTrackPatchRequested(string pckName, var bnkId, var trackObjId)
    signal editTrackLoopRequested(string pckName, var bnkId, var trackObjId, string value)
    signal editTrackVolumeRequested(string pckName, var bnkId, var trackObjId, string value)
    signal editRemapTargetRequested(string pckName, var bnkId, var trackObjId, string slot, var index, string value)
    signal applyAllRequested()
    signal importModForEditingRequested()
    signal exportModRequested()
    signal resetDraftRequested()
    signal browseThumbnailRequested()
    signal createModRequested(string name, string author, string version, string description, string thumbnailPath)

    // Public state (set from connector)
    property var bnkList: []
    property var hircObjects: []
    property string statusText: qsTranslate("Application", "Idle")
    property string selectedPck: ""
    property var selectedBnkId: 0
    property string hircFilter: "all"
    property string objectFilter: ""
    // Map { pck_name: true } for currently-expanded pck nodes in the tree.
    property var expandedPcks: ({})
    // Cached flat tree model; rebuilt only on (bnkList, expandedPcks, search) change so reassigning ListView.model doesn't reset scroll.
    property var bnkTreeModel: []

    // Add-WEM panel state
    property var musicPckList: []
    property string wemAddPath: ""
    property string wemAddTargetPck: ""
    property string wemAddIdText: ""
    property var wemAddLangId: 0

    property int draftCount: 0
    property var draftChanges: []

    // Pending edits per MusicTrack: keys "<obj_id>:<kind>[:<idx>]" -> typed string.
    // Kinds: "src" (AkBankSourceData), "pl" (TrackSrcInfo), "loop", "vol".
    // Strings avoid lossy float round-trips while editing.
    property var pending: ({})

    function pendingKey(objId, kind, idx) {
        return objId + ":" + kind + (idx !== undefined && idx !== null ? ":" + idx : "")
    }

    function setPending(objId, kind, idx, val) {
        var key = pendingKey(objId, kind, idx)
        var copy = {}
        for (var k in pending) copy[k] = pending[k]
        copy[key] = val
        pending = copy
    }

    function getPendingOrDefault(objId, kind, idx, defaultVal) {
        var key = pendingKey(objId, kind, idx)
        return (key in pending) ? pending[key] : defaultVal
    }

    function formatDurationMs(totalMs) {
        // Render a millisecond duration as mm:ss.SSS, matching the Browser changes view.
        var ms = Math.max(0, Math.floor(Number(totalMs) || 0))
        var minutes = Math.floor(ms / 60000)
        var seconds = Math.floor((ms % 60000) / 1000)
        var millis = ms % 1000
        return `${minutes.toString().padStart(2,'0')}:${seconds.toString().padStart(2,'0')}.${millis.toString().padStart(3,'0')}`
    }

    function parseDurationMs(text) {
        // Accept "mm:ss.SSS", "mm:ss", or plain milliseconds; return integer ms or null.
        var raw = String(text || "").trim()
        if (raw === "") return null
        if (raw.indexOf(":") === -1) {
            var asMs = Number(raw)
            return isNaN(asMs) ? null : Math.round(asMs)
        }
        var mmss = raw.split(":")
        if (mmss.length !== 2) return null
        var secMs = mmss[1].split(".")
        var minutes = parseInt(mmss[0], 10)
        var seconds = parseInt(secMs[0], 10)
        var millis = secMs.length > 1 ? parseInt((secMs[1] + "000").slice(0, 3), 10) : 0
        if (isNaN(minutes) || isNaN(seconds) || isNaN(millis)) return null
        return (minutes * 60 + seconds) * 1000 + millis
    }

    function hasPendingForTrack(objId, modelData) {
        for (var k in pending) {
            if (k.indexOf(objId + ":") !== 0) continue
            var val = pending[k]
            // Typed value matching the existing one is a no-op (button stays disabled).
            var parts = k.split(":")
            var kind = parts[1]
            if (kind === "src" && modelData.sources) {
                var idx = parseInt(parts[2])
                var src = modelData.sources[idx]
                if (src && parseInt(val) !== src.source_id && val !== "") return true
            } else if (kind === "pl" && modelData.playlist) {
                var idx = parseInt(parts[2])
                var ts = modelData.playlist[idx]
                if (ts && parseInt(val) !== ts.source_id && val !== "") return true
            } else if (kind === "loop") {
                var v = parseDurationMs(val)
                var curLoop = (modelData.loop_ms === null || modelData.loop_ms === undefined)
                              ? null : Math.floor(modelData.loop_ms)
                if (v !== null && v !== curLoop) return true
            } else if (kind === "vol") {
                var v = parseFloat(val)
                if (!isNaN(v) && v !== modelData.volume_db) return true
            }
        }
        return false
    }

    function stagePendingForTrack(objId, modelData) {
        // Collect this track's pending edits into a logical (offset-free) patch and stage it.
        var remaps = []
        for (var i = 0; i < (modelData.sources || []).length; i++) {
            var k = pendingKey(objId, "src", i)
            if (k in pending) {
                var src = modelData.sources[i]
                var v = parseInt(pending[k])
                if (!isNaN(v) && v !== src.source_id) {
                    remaps.push({slot: "src", index: i,
                                 old_source_id: src.source_id, new_source_id: v})
                }
            }
        }
        for (var j = 0; j < (modelData.playlist || []).length; j++) {
            var k2 = pendingKey(objId, "pl", j)
            if (k2 in pending) {
                var ts = modelData.playlist[j]
                var v2 = parseInt(pending[k2])
                if (!isNaN(v2) && v2 !== ts.source_id) {
                    remaps.push({slot: "pl", index: j,
                                 old_source_id: ts.source_id, new_source_id: v2})
                }
            }
        }
        var loopStr = ""
        var loopK = pendingKey(objId, "loop")
        if (loopK in pending) {
            var lv = parseDurationMs(pending[loopK])
            var curLoop = (modelData.loop_ms === null || modelData.loop_ms === undefined)
                          ? null : Math.floor(modelData.loop_ms)
            if (lv !== null && lv !== curLoop) loopStr = "" + lv
        }
        var volStr = ""
        var volK = pendingKey(objId, "vol")
        if (volK in pending) {
            var vv = parseFloat(pending[volK])
            if (!isNaN(vv) && vv !== modelData.volume_db) volStr = "" + vv
        }
        if (remaps.length === 0 && loopStr === "" && volStr === "") return
        hircEditorPage.stageTrackRequested(
            hircEditorPage.selectedPck, hircEditorPage.selectedBnkId, objId,
            JSON.stringify(remaps), loopStr, volStr
        )
        // Clear pending for this track only.
        var copy = {}
        for (var key in pending) {
            if (key.indexOf(objId + ":") !== 0) copy[key] = pending[key]
        }
        pending = copy
    }

    function clearAllPending() { pending = {} }

    function setMusicPckList(data) { musicPckList = data || [] }
    function setWemAddPath(path) { wemAddPath = path || "" }

    function setDraftCount(n) { draftCount = n || 0 }
    function setDraftChanges(list) {
        // Data-driven populate + open, mirroring the Browser's showChanges().
        draftChanges = list || []
        changesOverlay.visible = true
        changesOverlay.closing = false
    }
    function setThumbnailPath(path) { hircMetaThumbInput.text = path || "" }
    function onWemStaged(sname) {
        // Staged: clear the add fields so the next add starts fresh.
        wemAddPath = ""
        wemAddIdText = ""
    }
    function onDraftApplied(ok, msg) { statusText = msg }
    function onModExported(ok, name) {
        statusText = ok ? qsTranslate("Application", "Mod exported: %1").replace("%1", name)
                        : qsTranslate("Application", "Export failed: %1").replace("%1", name)
    }
    function openExportDialog(prefill) {
        hircMetaNameInput.text = (prefill && prefill.name) ? prefill.name : ""
        hircMetaAuthorInput.text = (prefill && prefill.author) ? prefill.author : ""
        hircMetaVersionInput.text = (prefill && prefill.version) ? prefill.version : "1.0.0"
        hircMetaDescInput.text = (prefill && prefill.description) ? prefill.description : ""
        hircMetaThumbInput.text = ""
        metadataOverlay.visible = true
        metadataOverlay.closing = false
        hircMetaNameInput.forceActiveFocus()
    }

    function togglePckExpanded(pckName) {
        var copy = {}
        for (var k in expandedPcks) copy[k] = expandedPcks[k]
        if (copy[pckName]) delete copy[pckName]
        else copy[pckName] = true
        expandedPcks = copy
    }

    // Apply the unified search to both the bank list (left) and the inspector objects (right).
    function applyHircSearch() {
        var q = (typeof hircSearchInput !== "undefined") ? hircSearchInput.text : ""
        objectFilter = q.toLowerCase()
        rebuildBnkTreeModel()
    }

    function rebuildBnkTreeModel() {
        // Preserve the current scroll position across the model reassignment.
        var savedY = bnkListView ? bnkListView.contentY : 0
        bnkTreeModel = buildBnkTreeModel(typeof hircSearchInput !== "undefined" ? hircSearchInput.text : "")
        if (bnkListView) {
            // Defer until after layout so contentHeight reflects the new model.
            Qt.callLater(function() {
                var maxY = Math.max(0, bnkListView.contentHeight - bnkListView.height)
                bnkListView.contentY = Math.max(0, Math.min(savedY, maxY))
            })
        }
    }

    onBnkListChanged: rebuildBnkTreeModel()
    onExpandedPcksChanged: rebuildBnkTreeModel()

    function buildBnkTreeModel(filterText) {
        var f = (filterText || "").toLowerCase()
        // Group by pck_name preserving the original order.
        var byPck = {}
        var order = []
        for (var i = 0; i < bnkList.length; i++) {
            var b = bnkList[i]
            if (!(b.pck_name in byPck)) {
                byPck[b.pck_name] = []
                order.push(b.pck_name)
            }
            byPck[b.pck_name].push(b)
        }
        var rows = []
        for (var p = 0; p < order.length; p++) {
            var pck = order[p]
            var children = byPck[pck]
            // Keep a pck if its name, a child bnk_id, or a contained source id/name matches.
            // The search blob is built server-side per bnk.
            var pckMatches = !f || pck.toLowerCase().indexOf(f) !== -1
            var childMatches = []
            if (!pckMatches && f) {
                for (var c = 0; c < children.length; c++) {
                    if (("" + children[c].bnk_id).indexOf(f) !== -1
                        || (children[c].search && children[c].search.indexOf(f) !== -1)) {
                        childMatches.push(children[c])
                    }
                }
            }
            if (!pckMatches && childMatches.length === 0) continue
            var totalMusic = 0
            for (var t = 0; t < children.length; t++) totalMusic += children[t].music_object_count
            // Children share pck_name and is_override (deduped upstream), so take the flag from the first.
            var isOverride = !!(children[0] && children[0].is_override)
            var pckRow = {
                row_type: "pck",
                pck_name: pck,
                bnk_count: children.length,
                music_object_count: totalMusic,
                is_override: isOverride,
                expanded: !!expandedPcks[pck] || (!pckMatches && childMatches.length > 0),
            }
            rows.push(pckRow)
            if (pckRow.expanded) {
                var visible = (pckMatches || !f) ? children : childMatches
                for (var k = 0; k < visible.length; k++) {
                    var ch = visible[k]
                    rows.push({
                        row_type: "bnk",
                        pck_name: pck,
                        bnk_id: ch.bnk_id,
                        bnk_size: ch.bnk_size,
                        music_object_count: ch.music_object_count,
                    })
                }
            }
        }
        return rows
    }

    // Setters used by HircEditorConnector via QMetaObject.invokeMethod
    function setBnkList(data) {
        bnkList = data || []
        statusText = qsTranslate("Application", "Loaded %1 bnks").replace("%1", bnkList.length)
    }
    function setBnkHirc(pck, bnkId, objs) {
        if (pck !== selectedPck || bnkId !== selectedBnkId) {
            selectedPck = pck
            selectedBnkId = bnkId
        }
        hircObjects = objs || []
        // Fresh data invalidates any in-flight edits.
        clearAllPending()
        statusText = qsTranslate("Application", "Loaded %1 music HIRC objects in %2:%3")
                        .replace("%1", hircObjects.length)
                        .replace("%2", pck)
                        .replace("%3", bnkId)
    }
    function clearInspector() {
        // Reset the right-hand inspector on game switch (the loaded bnk belongs to the old game).
        selectedPck = ""
        selectedBnkId = 0
        hircObjects = []
        clearAllPending()
        // Clearing the unified search resets both the bank list and the object filter.
        if (typeof hircSearchInput !== "undefined") hircSearchInput.text = ""
        objectFilter = ""
    }
    function setStatusText(msg) { statusText = msg }

    // ── Outer / inner frames matching Browser/ModManager pages ──────────
    Rectangle {
        id: outerFrame
        anchors.fill: parent
        anchors.margins: 15
        color: Theme.backgroundColor
        radius: Theme.radiusLarge

        Rectangle {
            id: innerFrame
            anchors.fill: parent
            anchors.margins: 15
            color: Theme.surfaceColor
            radius: Theme.radiusLarge

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: Theme.spacingMedium
                spacing: Theme.spacingSmall

                RowLayout {
                    Layout.fillWidth: true
                    spacing: Theme.spacingSmall

                    Rectangle {
                        Layout.fillWidth: true
                        height: Theme.buttonHeight
                        color: Theme.cardBackground
                        radius: Theme.radiusMedium

                        TextInput {
                            id: hircSearchInput
                            anchors.fill: parent
                            anchors.leftMargin: 14
                            anchors.rightMargin: 14
                            verticalAlignment: Text.AlignVCenter
                            color: Theme.textPrimary
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSizeSmall
                            clip: true

                            onTextChanged: hircEditorPage.applyHircSearch()
                            Keys.onReturnPressed: hircEditorPage.applyHircSearch()

                            Text {
                                anchors.fill: parent
                                verticalAlignment: Text.AlignVCenter
                                color: Theme.textPrimary
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSizeSmall
                                text: qsTranslate("Application", "Search by pck, bnk_id, obj_id, source_id or name")
                                visible: !hircSearchInput.text && !hircSearchInput.activeFocus
                            }
                        }
                    }

                    XXARButton {
                        text: qsTranslate("Application", "Search")
                        onClicked: hircEditorPage.applyHircSearch()
                    }
                    XXARButton {
                        text: qsTranslate("Application", "Clear")
                        onClicked: hircSearchInput.text = ""
                    }
                }

                // ── Two-column work area ────────────────────────────────
                RowLayout {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    spacing: Theme.spacingMedium

                    // ─── LEFT: bnk list ─────────────────────────────────
                    Rectangle {
                        Layout.preferredWidth: 360
                        Layout.fillHeight: true
                        color: Theme.surfaceDark
                        radius: Theme.radiusMedium

                        ColumnLayout {
                            anchors.fill: parent
                            anchors.margins: Theme.spacingMedium
                            spacing: Theme.spacingSmall

                            RowLayout {
                                Layout.fillWidth: true
                                spacing: Theme.spacingSmall

                                Text {
                                    text: qsTranslate("Application", "Banks")
                                    color: Theme.textPrimary
                                    font.family: Theme.fontFamilyTitle
                                    font.pixelSize: Theme.fontSizeMedium
                                    Layout.fillWidth: true
                                }

                                Rectangle {
                                    width: 100
                                    Layout.preferredHeight: Theme.buttonHeight
                                    radius: Theme.radiusMedium
                                    color: refreshArea.pressed ? Theme.accentDark
                                         : refreshArea.containsMouse ? Theme.accentLight
                                         : Theme.primaryAccent
                                    Behavior on color { ColorAnimation { duration: Theme.animationDuration } }

                                    Text {
                                        anchors.centerIn: parent
                                        text: qsTranslate("Application", "Refresh")
                                        color: Theme.textOnAccent
                                        font.family: Theme.fontFamily
                                        font.pixelSize: Theme.fontSizeSmall
                                    }
                                    MouseArea {
                                        id: refreshArea
                                        anchors.fill: parent
                                        hoverEnabled: true
                                        cursorShape: Qt.PointingHandCursor
                                        onClicked: hircEditorPage.refreshRequested()
                                    }
                                }
                            }

                            ListView {
                                id: bnkListView
                                Layout.fillWidth: true
                                Layout.fillHeight: true
                                clip: true
                                spacing: 2
                                model: hircEditorPage.bnkTreeModel

                                delegate: Loader {
                                    width: ListView.view.width
                                    sourceComponent: modelData.row_type === "pck" ? pckRowComponent : bnkRowComponent
                                    property var rowData: modelData
                                }

                                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                            }

                            Component {
                                id: pckRowComponent
                                Rectangle {
                                    height: 36
                                    radius: 6
                                    color: pckMouse.containsMouse
                                           ? Qt.lighter(Theme.surfaceColor, 1.2)
                                           : Theme.surfaceColor
                                    Behavior on color { ColorAnimation { duration: 100 } }

                                    RowLayout {
                                        anchors.fill: parent
                                        anchors.leftMargin: 8
                                        anchors.rightMargin: 8
                                        spacing: 8

                                        Text {
                                            text: rowData.expanded ? "▼" : "▶"
                                            color: Theme.primaryAccent
                                            font.pixelSize: 10
                                            Layout.preferredWidth: 12
                                        }
                                        Text {
                                            text: rowData.pck_name
                                            color: Theme.textPrimary
                                            font.family: Theme.fontFamily
                                            font.pixelSize: Theme.fontSizeSmall
                                            font.bold: true
                                            Layout.fillWidth: true
                                            elide: Text.ElideRight
                                        }
                                        Text {
                                            visible: rowData.is_override === true
                                            text: "★ override"
                                            color: Theme.primaryAccent
                                            font.family: Theme.fontFamily
                                            font.pixelSize: 10
                                            font.bold: true
                                        }
                                        Text {
                                            text: rowData.bnk_count + " bnk · " + rowData.music_object_count + " HIRC"
                                            color: Theme.textSecondary
                                            font.family: Theme.fontFamily
                                            font.pixelSize: 10
                                        }
                                    }
                                    MouseArea {
                                        id: pckMouse
                                        anchors.fill: parent
                                        hoverEnabled: true
                                        cursorShape: Qt.PointingHandCursor
                                        onClicked: hircEditorPage.togglePckExpanded(rowData.pck_name)
                                    }
                                }
                            }

                            Component {
                                id: bnkRowComponent
                                Rectangle {
                                    height: 32
                                    radius: 5
                                    color: bnkMouse.containsMouse
                                           ? Qt.lighter(Theme.surfaceColor, 1.15)
                                           : ((hircEditorPage.selectedPck === rowData.pck_name
                                               && hircEditorPage.selectedBnkId === rowData.bnk_id)
                                              ? Theme.cardBackground
                                              : Qt.darker(Theme.surfaceColor, 1.15))
                                    Behavior on color { ColorAnimation { duration: 100 } }

                                    RowLayout {
                                        anchors.fill: parent
                                        anchors.leftMargin: 28
                                        anchors.rightMargin: 8
                                        spacing: 8

                                        Text {
                                            text: rowData.bnk_id
                                            color: Theme.textPrimary
                                            font.family: Theme.fontFamily
                                            font.pixelSize: Theme.fontSizeSmall
                                            Layout.preferredWidth: 110
                                            elide: Text.ElideRight
                                        }
                                        Text {
                                            text: rowData.music_object_count + " HIRC · "
                                                  + (rowData.bnk_size / 1024).toFixed(1) + " KB"
                                            color: Theme.textSecondary
                                            font.family: Theme.fontFamily
                                            font.pixelSize: 10
                                            Layout.fillWidth: true
                                            elide: Text.ElideRight
                                        }
                                    }
                                    MouseArea {
                                        id: bnkMouse
                                        anchors.fill: parent
                                        hoverEnabled: true
                                        cursorShape: Qt.PointingHandCursor
                                        onClicked: {
                                            hircEditorPage.selectedPck = rowData.pck_name
                                            hircEditorPage.selectedBnkId = rowData.bnk_id
                                            hircEditorPage.bnkSelected(rowData.pck_name, rowData.bnk_id)
                                        }
                                    }
                                }
                            }
                        }
                    }

                    // ─── RIGHT: HIRC inspector ─────────────────────────
                    Rectangle {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        color: Theme.surfaceDark
                        radius: Theme.radiusMedium

                        ColumnLayout {
                            anchors.fill: parent
                            anchors.margins: Theme.spacingMedium
                            spacing: Theme.spacingSmall

                            RowLayout {
                                Layout.fillWidth: true
                                spacing: Theme.spacingSmall

                                Text {
                                    text: hircEditorPage.selectedPck
                                          ? qsTranslate("Application", "HIRC: %1 : %2")
                                                .replace("%1", hircEditorPage.selectedPck)
                                                .replace("%2", hircEditorPage.selectedBnkId)
                                          : qsTranslate("Application", "Select a bnk on the left")
                                    color: Theme.textPrimary
                                    font.family: Theme.fontFamilyTitle
                                    font.pixelSize: Theme.fontSizeNormal
                                    Layout.fillWidth: true
                                    elide: Text.ElideRight
                                }

                                Repeater {
                                    model: [
                                        {label: qsTranslate("Application", "All"),     value: "all"},
                                        {label: "Track",   value: "MusicTrack"},
                                        {label: "Segment", value: "MusicSegment"},
                                        {label: "Switch",  value: "MusicSwitchCntr"},
                                        {label: "RanSeq",  value: "MusicRanSeqCntr"},
                                    ]
                                    Rectangle {
                                        width: 70
                                        Layout.preferredHeight: Theme.buttonHeight
                                        radius: Theme.radiusMedium
                                        color: hircEditorPage.hircFilter === modelData.value
                                               ? Theme.primaryAccent : Theme.cardBackground
                                        Behavior on color { ColorAnimation { duration: 100 } }

                                        Text {
                                            anchors.centerIn: parent
                                            text: modelData.label
                                            color: hircEditorPage.hircFilter === modelData.value
                                                   ? Theme.textOnAccent : Theme.textPrimary
                                            font.family: Theme.fontFamily
                                            font.pixelSize: 11
                                            font.bold: hircEditorPage.hircFilter === modelData.value
                                        }
                                        MouseArea {
                                            anchors.fill: parent
                                            cursorShape: Qt.PointingHandCursor
                                            onClicked: hircEditorPage.hircFilter = modelData.value
                                        }
                                    }
                                }
                            }

                            ListView {
                                id: hircListView
                                Layout.fillWidth: true
                                Layout.fillHeight: true
                                clip: true
                                spacing: Theme.spacingSmall

                                model: {
                                    var f = hircEditorPage.hircFilter
                                    var q = hircEditorPage.objectFilter
                                    var out = []
                                    for (var i = 0; i < hircEditorPage.hircObjects.length; i++) {
                                        var o = hircEditorPage.hircObjects[i]
                                        if (f !== "all" && o.type !== f) continue
                                        if (q) {
                                            var hay = ("" + o.obj_id) + " "
                                            for (var s = 0; s < (o.sources || []).length; s++) {
                                                hay += " " + o.sources[s].source_id + " " + (o.sources[s].name || "")
                                            }
                                            for (var p = 0; p < (o.playlist || []).length; p++) {
                                                hay += " " + o.playlist[p].source_id + " " + (o.playlist[p].name || "")
                                            }
                                            if (hay.toLowerCase().indexOf(q) === -1) continue
                                        }
                                        out.push(o)
                                    }
                                    return out
                                }

                                delegate: Rectangle {
                                    width: ListView.view.width
                                    height: detailCol.implicitHeight + 18
                                    radius: Theme.radiusMedium
                                    color: Theme.surfaceColor
                                    border.color: modelData.type === "MusicTrack"
                                                  ? Theme.primaryAccent : Theme.cardBackground
                                    border.width: 1

                                    // Expose the outer track to nested Repeater delegates
                                    // (their own modelData refers to source/playlist rows).
                                    property var track: modelData

                                    ColumnLayout {
                                        id: detailCol
                                        anchors.left: parent.left
                                        anchors.right: parent.right
                                        anchors.top: parent.top
                                        anchors.margins: 9
                                        spacing: Theme.spacingTiny

                                        // Type tag + obj_id header
                                        RowLayout {
                                            Layout.fillWidth: true
                                            spacing: Theme.spacingSmall
                                            Rectangle {
                                                width: 100
                                                height: 22
                                                radius: Theme.radiusSmall / 2
                                                color: Theme.cardBackground
                                                Text {
                                                    anchors.centerIn: parent
                                                    text: modelData.type
                                                    color: Theme.primaryAccent
                                                    font.family: Theme.fontFamily
                                                    font.pixelSize: 11
                                                    font.bold: true
                                                }
                                            }
                                            Text {
                                                text: "obj_id " + modelData.obj_id + "  (0x" + modelData.obj_id.toString(16).toUpperCase() + ")"
                                                color: Theme.textPrimary
                                                font.family: Theme.fontFamily
                                                font.pixelSize: Theme.fontSizeSmall
                                                Layout.fillWidth: true
                                                elide: Text.ElideRight
                                            }
                                            Text {
                                                text: modelData.body_size + " B"
                                                color: Theme.textSecondary
                                                font.family: Theme.fontFamily
                                                font.pixelSize: 11
                                            }
                                        }

                                        // AkBankSourceData rows
                                        Repeater {
                                            model: modelData.sources || []
                                            Rectangle {
                                                Layout.fillWidth: true
                                                height: 30
                                                radius: Theme.radiusSmall / 3
                                                color: Theme.surfaceDark

                                                RowLayout {
                                                    anchors.fill: parent
                                                    anchors.leftMargin: Theme.spacingSmall
                                                    anchors.rightMargin: Theme.spacingSmall
                                                    spacing: Theme.spacingSmall
                                                    Text {
                                                        text: "AkBankSourceData[" + modelData.index + "]"
                                                        color: Theme.textSecondary
                                                        font.family: Theme.fontFamily
                                                        font.pixelSize: 11
                                                        Layout.preferredWidth: 160
                                                    }
                                                    TextField {
                                                        text: hircEditorPage.getPendingOrDefault(
                                                                  track.obj_id, "src", modelData.index,
                                                                  "" + modelData.source_id
                                                              )
                                                        color: Theme.textPrimary
                                                        font.family: Theme.fontFamily
                                                        font.pixelSize: 12
                                                        background: Rectangle {
                                                            color: Theme.surfaceColor
                                                            radius: Theme.radiusSmall / 3
                                                            border.color: Theme.cardBackground
                                                            border.width: 1
                                                        }
                                                        Layout.preferredWidth: 130
                                                        validator: RegularExpressionValidator { regularExpression: /^[0-9]{1,10}$/ }
                                                        onTextEdited: hircEditorPage.setPending(
                                                                          track.obj_id, "src",
                                                                          modelData.index, text
                                                                      )
                                                    }
                                                    Text {
                                                        visible: !!(modelData.name) && modelData.name.length > 0
                                                        text: "♪ " + (modelData.name || "")
                                                        color: Theme.primaryAccent
                                                        font.family: Theme.fontFamily
                                                        font.pixelSize: 11
                                                        Layout.fillWidth: true
                                                        elide: Text.ElideRight
                                                    }
                                                    Text {
                                                        text: "@ " + modelData.abs_offset_in_pck
                                                        color: Theme.textSecondary
                                                        font.family: Theme.fontFamily
                                                        font.pixelSize: 10
                                                        Layout.fillWidth: !(modelData.name && modelData.name.length > 0)
                                                        horizontalAlignment: Text.AlignRight
                                                        elide: Text.ElideRight
                                                    }
                                                }
                                            }
                                        }

                                        // TrackSrcInfo rows
                                        Repeater {
                                            model: modelData.playlist || []
                                            Rectangle {
                                                Layout.fillWidth: true
                                                height: 30
                                                radius: Theme.radiusSmall / 3
                                                color: Theme.surfaceDark

                                                RowLayout {
                                                    anchors.fill: parent
                                                    anchors.leftMargin: Theme.spacingSmall
                                                    anchors.rightMargin: Theme.spacingSmall
                                                    spacing: Theme.spacingSmall
                                                    Text {
                                                        text: "TrackSrcInfo[" + modelData.index + "]"
                                                        color: Theme.textSecondary
                                                        font.family: Theme.fontFamily
                                                        font.pixelSize: 11
                                                        Layout.preferredWidth: 160
                                                    }
                                                    TextField {
                                                        text: hircEditorPage.getPendingOrDefault(
                                                                  track.obj_id, "pl", modelData.index,
                                                                  "" + modelData.source_id
                                                              )
                                                        color: Theme.textPrimary
                                                        font.family: Theme.fontFamily
                                                        font.pixelSize: 12
                                                        background: Rectangle {
                                                            color: Theme.surfaceColor
                                                            radius: Theme.radiusSmall / 3
                                                            border.color: Theme.cardBackground
                                                            border.width: 1
                                                        }
                                                        Layout.preferredWidth: 130
                                                        validator: RegularExpressionValidator { regularExpression: /^[0-9]{1,10}$/ }
                                                        onTextEdited: hircEditorPage.setPending(
                                                                          track.obj_id, "pl",
                                                                          modelData.index, text
                                                                      )
                                                    }
                                                    Text {
                                                        visible: !!(modelData.name) && modelData.name.length > 0
                                                        text: "♪ " + (modelData.name || "")
                                                        color: Theme.primaryAccent
                                                        font.family: Theme.fontFamily
                                                        font.pixelSize: 11
                                                        Layout.fillWidth: true
                                                        elide: Text.ElideRight
                                                    }
                                                    Text {
                                                        text: "@ " + modelData.abs_offset_in_pck
                                                        color: Theme.textSecondary
                                                        font.family: Theme.fontFamily
                                                        font.pixelSize: 10
                                                        Layout.fillWidth: !(modelData.name && modelData.name.length > 0)
                                                        horizontalAlignment: Text.AlignRight
                                                        elide: Text.ElideRight
                                                    }
                                                }
                                            }
                                        }

                                        // Loop point (visible if MusicTrack with playlist)
                                        Rectangle {
                                            Layout.fillWidth: true
                                            height: 30
                                            radius: Theme.radiusSmall / 3
                                            color: Qt.darker(Theme.primaryAccent, 6.5)
                                            visible: modelData.type === "MusicTrack"
                                                     && modelData.loop_ms !== null
                                                     && modelData.loop_ms !== undefined

                                            RowLayout {
                                                anchors.fill: parent
                                                anchors.leftMargin: Theme.spacingSmall
                                                anchors.rightMargin: Theme.spacingSmall
                                                spacing: Theme.spacingSmall
                                                Text {
                                                    text: qsTranslate("Application", "Loop")
                                                    color: Theme.primaryAccent
                                                    font.family: Theme.fontFamily
                                                    font.pixelSize: 11
                                                    font.bold: true
                                                    Layout.preferredWidth: 160
                                                }
                                                TextField {
                                                    text: hircEditorPage.getPendingOrDefault(
                                                              track.obj_id, "loop", null,
                                                              (track.loop_ms !== null && track.loop_ms !== undefined)
                                                                ? hircEditorPage.formatDurationMs(track.loop_ms) : ""
                                                          )
                                                    color: Theme.textPrimary
                                                    font.family: Theme.fontFamily
                                                    font.pixelSize: 12
                                                    background: Rectangle {
                                                        color: Theme.surfaceColor
                                                        radius: Theme.radiusSmall / 3
                                                        border.color: Theme.cardBackground
                                                        border.width: 1
                                                    }
                                                    Layout.preferredWidth: 130
                                                    validator: RegularExpressionValidator { regularExpression: /^[0-9:.]*$/ }
                                                    onTextEdited: hircEditorPage.setPending(
                                                                      track.obj_id, "loop", null, text
                                                                  )
                                                }
                                                Text {
                                                    text: qsTranslate("Application", "applies to all TrackSrcInfo + segment")
                                                    color: Theme.textSecondary
                                                    font.family: Theme.fontFamily
                                                    font.pixelSize: 10
                                                    Layout.fillWidth: true
                                                    elide: Text.ElideRight
                                                }
                                            }
                                        }

                                        // Shown for MusicTracks whose AkPropBundle is reachable (has_volume or volume_insertable).
                                        // Sourceless stubs and containers stay hidden, since there's nothing to apply a volume to.
                                        Rectangle {
                                            Layout.fillWidth: true
                                            height: 30
                                            radius: Theme.radiusSmall / 3
                                            color: Qt.darker(Theme.primaryAccent, 6.5)
                                            visible: track.has_volume === true || track.volume_insertable === true

                                            RowLayout {
                                                anchors.fill: parent
                                                anchors.leftMargin: Theme.spacingSmall
                                                anchors.rightMargin: Theme.spacingSmall
                                                spacing: Theme.spacingSmall
                                                Text {
                                                    text: qsTranslate("Application", "Volume (dB)")
                                                    color: Theme.primaryAccent
                                                    font.family: Theme.fontFamily
                                                    font.pixelSize: 11
                                                    font.bold: true
                                                    Layout.preferredWidth: 160
                                                }
                                                TextField {
                                                    text: hircEditorPage.getPendingOrDefault(
                                                              track.obj_id, "vol", null,
                                                              (track.volume_db !== null && track.volume_db !== undefined)
                                                                ? track.volume_db.toFixed(2) : ""
                                                          )
                                                    color: Theme.textPrimary
                                                    font.family: Theme.fontFamily
                                                    font.pixelSize: 12
                                                    background: Rectangle {
                                                        color: Theme.surfaceColor
                                                        radius: Theme.radiusSmall / 3
                                                        border.color: Theme.cardBackground
                                                        border.width: 1
                                                    }
                                                    Layout.preferredWidth: 130
                                                    validator: DoubleValidator { bottom: -96; top: 24; decimals: 2; notation: DoubleValidator.StandardNotation; locale: "C" }
                                                    onTextEdited: hircEditorPage.setPending(
                                                                      track.obj_id, "vol", null, text
                                                                  )
                                                }
                                                Text {
                                                    text: track.has_volume === true
                                                            ? "@ " + track.volume_offset_abs
                                                            : qsTranslate("Application", "(new — inserted on apply)")
                                                    color: Theme.textSecondary
                                                    font.family: Theme.fontFamily
                                                    font.pixelSize: 10
                                                    Layout.fillWidth: true
                                                    elide: Text.ElideRight
                                                }
                                            }
                                        }

                                        Item {
                                            Layout.fillWidth: true
                                            Layout.preferredHeight: 32
                                            visible: (track.sources && track.sources.length > 0)
                                                     || (track.playlist && track.playlist.length > 0)
                                                     || (track.loop_ms !== null && track.loop_ms !== undefined)
                                                     || track.has_volume === true

                                            property bool dirty: hircEditorPage.hasPendingForTrack(track.obj_id, track)

                                            Rectangle {
                                                width: 100
                                                height: 28
                                                anchors.right: parent.right
                                                anchors.verticalCenter: parent.verticalCenter
                                                radius: Theme.radiusMedium
                                                color: !parent.dirty ? Theme.disabledAccent
                                                     : applyArea.pressed ? Theme.accentDark
                                                     : applyArea.containsMouse ? Theme.accentLight
                                                     : Theme.primaryAccent
                                                Behavior on color { ColorAnimation { duration: Theme.animationDuration } }

                                                Text {
                                                    anchors.centerIn: parent
                                                    text: qsTranslate("Application", "Stage")
                                                    color: Theme.textOnAccent
                                                    font.family: Theme.fontFamily
                                                    font.pixelSize: Theme.fontSizeSmall
                                                    font.bold: true
                                                }
                                                MouseArea {
                                                    id: applyArea
                                                    anchors.fill: parent
                                                    hoverEnabled: true
                                                    enabled: parent.parent.dirty
                                                    cursorShape: parent.parent.dirty ? Qt.PointingHandCursor : Qt.ArrowCursor
                                                    onClicked: hircEditorPage.stagePendingForTrack(track.obj_id, track)
                                                }
                                            }
                                        }
                                    }
                                }

                                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                            }
                        }
                    }
                }

                // ── Add custom WEM bar ──────────────────────────────────
                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 56
                    radius: Theme.radiusMedium
                    color: Theme.surfaceDark

                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: Theme.spacingMedium
                        anchors.rightMargin: Theme.spacingSmall
                        spacing: Theme.spacingSmall

                        Text {
                            text: qsTranslate("Application", "Add WEM:")
                            color: Theme.primaryAccent
                            font.family: Theme.fontFamilyTitle
                            font.pixelSize: Theme.fontSizeSmall
                            font.bold: true
                        }

                        // Browse button
                        Rectangle {
                            Layout.preferredWidth: 80
                            Layout.preferredHeight: Theme.buttonHeight
                            radius: Theme.radiusMedium
                            color: browseArea.pressed ? Theme.accentDark
                                 : browseArea.containsMouse ? Theme.accentLight
                                 : Theme.cardBackground
                            Behavior on color { ColorAnimation { duration: Theme.animationDuration } }

                            Text {
                                anchors.centerIn: parent
                                text: qsTranslate("Application", "Browse")
                                color: Theme.textPrimary
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSizeSmall
                            }
                            MouseArea {
                                id: browseArea
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: hircEditorPage.browseWemFileRequested()
                            }
                        }

                        // Selected file path (read-only display)
                        Rectangle {
                            Layout.fillWidth: true
                            Layout.preferredHeight: Theme.buttonHeight
                            radius: Theme.radiusMedium
                            color: Theme.surfaceColor
                            border.color: Theme.cardBackground
                            border.width: 1

                            Text {
                                anchors.fill: parent
                                anchors.leftMargin: Theme.spacingSmall
                                anchors.rightMargin: Theme.spacingSmall
                                verticalAlignment: Text.AlignVCenter
                                text: hircEditorPage.wemAddPath || qsTranslate("Application", "(no audio selected — wav/mp3/ogg/wem)")
                                color: hircEditorPage.wemAddPath ? Theme.textPrimary : Theme.textSecondary
                                font.family: Theme.fontFamily
                                font.pixelSize: 11
                                elide: Text.ElideMiddle
                            }
                        }

                        // Custom wem id input
                        Text {
                            text: "ID"
                            color: Theme.textSecondary
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSizeSmall
                        }
                        TextField {
                            id: wemIdField
                            text: hircEditorPage.wemAddIdText
                            Layout.preferredWidth: 130
                            Layout.preferredHeight: Theme.buttonHeight
                            placeholderText: qsTranslate("Application", "wem id (u32)")
                            color: Theme.textPrimary
                            font.family: Theme.fontFamily
                            font.pixelSize: 12
                            background: Rectangle {
                                color: Theme.surfaceColor
                                radius: Theme.radiusMedium
                                border.color: Theme.cardBackground
                                border.width: 1
                            }
                            validator: RegularExpressionValidator { regularExpression: /^[0-9]{1,10}$/ }
                            onTextChanged: hircEditorPage.wemAddIdText = text
                        }

                        // Target pck selector (ComboBox)
                        ComboBox {
                            id: targetPckCombo
                            Layout.preferredWidth: 160
                            Layout.preferredHeight: Theme.buttonHeight
                            model: {
                                var out = []
                                for (var i = 0; i < hircEditorPage.musicPckList.length; i++) {
                                    out.push(hircEditorPage.musicPckList[i].pck_name
                                             + (hircEditorPage.musicPckList[i].is_override ? " ★" : ""))
                                }
                                return out
                            }
                            currentIndex: {
                                if (!hircEditorPage.wemAddTargetPck) return 0
                                for (var i = 0; i < hircEditorPage.musicPckList.length; i++) {
                                    if (hircEditorPage.musicPckList[i].pck_name === hircEditorPage.wemAddTargetPck)
                                        return i
                                }
                                return 0
                            }
                            onActivated: {
                                if (index >= 0 && index < hircEditorPage.musicPckList.length) {
                                    hircEditorPage.wemAddTargetPck = hircEditorPage.musicPckList[index].pck_name
                                }
                            }
                            background: Rectangle {
                                color: Theme.surfaceColor
                                radius: Theme.radiusMedium
                                border.color: Theme.cardBackground
                                border.width: 1
                            }
                            contentItem: Text {
                                text: targetPckCombo.displayText
                                color: Theme.textPrimary
                                font.family: Theme.fontFamily
                                font.pixelSize: 11
                                verticalAlignment: Text.AlignVCenter
                                leftPadding: Theme.spacingSmall
                            }
                        }

                        // Add button
                        Rectangle {
                            Layout.preferredWidth: 80
                            Layout.preferredHeight: Theme.buttonHeight
                            radius: Theme.radiusMedium
                            property bool canAdd: hircEditorPage.wemAddPath !== ""
                                                  && hircEditorPage.wemAddIdText !== ""
                                                  && targetPckCombo.currentIndex >= 0
                                                  && hircEditorPage.musicPckList.length > 0
                            color: !canAdd ? Theme.disabledAccent
                                 : addArea.pressed ? Theme.accentDark
                                 : addArea.containsMouse ? Theme.accentLight
                                 : Theme.primaryAccent
                            Behavior on color { ColorAnimation { duration: Theme.animationDuration } }

                            Text {
                                anchors.centerIn: parent
                                text: qsTranslate("Application", "Stage")
                                color: Theme.textOnAccent
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSizeSmall
                                font.bold: true
                            }
                            MouseArea {
                                id: addArea
                                anchors.fill: parent
                                hoverEnabled: true
                                enabled: parent.canAdd
                                cursorShape: parent.canAdd ? Qt.PointingHandCursor : Qt.ArrowCursor
                                onClicked: {
                                    var idx = targetPckCombo.currentIndex
                                    if (idx < 0 || idx >= hircEditorPage.musicPckList.length) return
                                    var pck = hircEditorPage.musicPckList[idx].pck_name
                                    var wid = parseInt(hircEditorPage.wemAddIdText)
                                    if (isNaN(wid)) return
                                    hircEditorPage.stageAddWemRequested(pck, wid, hircEditorPage.wemAddPath, hircEditorPage.wemAddLangId)
                                }
                            }
                        }
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: Theme.spacingSmall

                    XXARButton {
                        text: qsTranslate("Application", "Import %1 for Editing").replace("%1", modFileExt)
                        onClicked: hircEditorPage.importModForEditingRequested()
                    }
                    XXARButton {
                        text: hircEditorPage.draftCount > 0
                              ? qsTranslate("Application", "Show Changes (%1)").arg(hircEditorPage.draftCount)
                              : qsTranslate("Application", "Show Changes")
                        onClicked: hircEditorPage.showChangesRequested()
                    }
                    XXARButton {
                        text: qsTranslate("Application", "Export as Mod Package")
                        onClicked: hircEditorPage.exportModRequested()
                    }
                    XXARButton {
                        text: qsTranslate("Application", "Reset All Changes")
                        buttonColor: Theme.disabledAccent
                        textColor: Theme.textPrimary
                        onClicked: hircEditorPage.resetDraftRequested()
                    }
                    Item { Layout.fillWidth: true }
                }

                Text {
                    text: hircEditorPage.statusText
                    color: Theme.textSecondary
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeSmall
                    Layout.fillWidth: true
                    elide: Text.ElideRight
                }
            }
        }
    }

    Item {
        id: changesOverlay
        visible: false
        anchors.fill: parent
        z: 2000
        property bool closing: false

        Timer {
            id: changesHideTimer
            interval: 200
            onTriggered: { changesOverlay.visible = false; changesOverlay.closing = false }
        }

        Rectangle {
            anchors.fill: parent
            color: "#80000000"
            opacity: (!changesOverlay.closing && changesOverlay.visible) ? 1.0 : 0.0
            Behavior on opacity { NumberAnimation { duration: 200 } }

            Image {
                anchors.fill: parent
                source: "../assets/" + assetsDir + "/gradient.png"
                fillMode: Image.Stretch
                mipmap: true
                opacity: 0.6
            }

            OverlayBackdropMouseArea {
                dialog: changesDialog
                onClickedOutside: { changesOverlay.closing = true; changesHideTimer.start() }
            }
        }

        Rectangle {
            id: changesDialog
            width: Math.min(parent.width - 40, 940)
            height: Math.min(560, parent.height - 60)
            anchors.centerIn: parent
            color: Theme.surfaceColor
            radius: Theme.radiusLarge
            border.color: Theme.cardBackground
            border.width: 1
            scale: (!changesOverlay.closing && changesOverlay.visible) ? 1.0 : 0.9
            opacity: (!changesOverlay.closing && changesOverlay.visible) ? 1.0 : 0.0
            Behavior on scale { NumberAnimation { duration: 200; easing.type: Easing.OutBack } }
            Behavior on opacity { NumberAnimation { duration: 200 } }

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 20
                spacing: 12

                Text {
                    text: qsTranslate("Application", "Current Changes") + " (" + hircEditorPage.draftCount + ")"
                    color: Theme.primaryAccent
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeNormal
                    font.bold: true
                    Layout.fillWidth: true
                }

                Rectangle {
                    Layout.fillWidth: true
                    height: 32
                    color: Theme.surfaceDark
                    radius: 6
                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 12
                        anchors.rightMargin: 12
                        spacing: 8
                        Text { Layout.preferredWidth: 64;  text: qsTranslate("Application", "Type");    color: Theme.textSecondary; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSmall; font.bold: true }
                        Text { Layout.preferredWidth: 160; text: qsTranslate("Application", "Target");  color: Theme.textSecondary; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSmall; font.bold: true }
                        Text { Layout.fillWidth: true;     text: qsTranslate("Application", "Source");  color: Theme.textSecondary; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSmall; font.bold: true }
                        Text { Layout.preferredWidth: 118; text: qsTranslate("Application", "Loop");    color: Theme.textSecondary; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSmall; font.bold: true }
                        Text { Layout.preferredWidth: 96;  text: qsTranslate("Application", "Volume (dB)");  color: Theme.textSecondary; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSmall; font.bold: true }
                        Text { Layout.preferredWidth: 84;  text: qsTranslate("Application", "Actions"); color: Theme.textSecondary; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSmall; font.bold: true }
                    }
                }

                ListView {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    spacing: 6
                    model: hircEditorPage.draftChanges
                    ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

                    delegate: Rectangle {
                        id: rowRoot
                        property var rowData: modelData
                        width: ListView.view.width
                        implicitHeight: rowLayout.implicitHeight + 16
                        height: implicitHeight
                        radius: 6
                        color: Theme.surfaceDark
                        RowLayout {
                            id: rowLayout
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.top: parent.top
                            anchors.leftMargin: 12
                            anchors.rightMargin: 12
                            anchors.topMargin: 8
                            spacing: 8

                            Rectangle {
                                Layout.preferredWidth: 64
                                Layout.preferredHeight: 26
                                Layout.alignment: Qt.AlignVCenter
                                radius: 4
                                color: rowRoot.rowData.kind === "add_wem" ? Theme.primaryAccent : Theme.cardBackground
                                Text {
                                    anchors.centerIn: parent
                                    text: rowRoot.rowData.kind === "add_wem" ? "ADD" : "TRACK"
                                    color: rowRoot.rowData.kind === "add_wem" ? Theme.textOnAccent : Theme.textPrimary
                                    font.pixelSize: 11; font.bold: true; font.family: Theme.fontFamily
                                }
                            }

                            Column {
                                id: targetCol
                                Layout.preferredWidth: 160
                                Layout.alignment: Qt.AlignVCenter
                                Text {
                                    width: targetCol.width
                                    height: 26
                                    verticalAlignment: Text.AlignVCenter
                                    text: rowRoot.rowData.pck_name || ""
                                    color: Theme.textPrimary; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSmall
                                    elide: Text.ElideMiddle
                                }
                                Text {
                                    width: targetCol.width
                                    visible: rowRoot.rowData.kind === "track"
                                    text: "bnk " + rowRoot.rowData.bnk_id + " · trk " + rowRoot.rowData.track_obj_id
                                    color: Theme.textSecondary; font.family: Theme.fontFamily; font.pixelSize: 12
                                    elide: Text.ElideRight
                                }
                            }

                            Column {
                                id: sourceCol
                                Layout.fillWidth: true
                                Layout.alignment: Qt.AlignVCenter
                                spacing: 4
                                Repeater {
                                    model: rowRoot.rowData.kind === "track" ? (rowRoot.rowData.remaps || []) : []
                                    Row {
                                        spacing: 4
                                        // Measure the widest label so Source and Playlist share one prefix width.
                                        // The ids and inputs stay aligned with no extra padding.
                                        TextMetrics {
                                            id: pfxMetrics
                                            font.family: Theme.fontFamily
                                            font.pixelSize: Theme.fontSizeSmall
                                            text: "Playlist[" + modelData.index + "]:"
                                        }
                                        Text {
                                            width: pfxMetrics.advanceWidth
                                            height: 26
                                            verticalAlignment: Text.AlignVCenter
                                            text: (modelData.slot === "pl" ? "Playlist[" : "Source[") + modelData.index + "]:"
                                            color: Theme.textSecondary; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSmall
                                        }
                                        Text {
                                            height: 26
                                            verticalAlignment: Text.AlignVCenter
                                            text: (modelData.old_source_id !== null && modelData.old_source_id !== undefined
                                                   ? "" + modelData.old_source_id : "")
                                            color: Theme.textPrimary; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSmall
                                        }
                                        Text {
                                            height: 26
                                            verticalAlignment: Text.AlignVCenter
                                            text: "→"
                                            color: Theme.textPrimary; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSmall
                                        }
                                        Rectangle {
                                            width: 110; height: 26; radius: Theme.radiusSmall
                                            color: Theme.inputBackground || "#2a2a2a"
                                            border.color: srcInput.activeFocus ? Theme.primaryAccent : Theme.cardBackground
                                            border.width: 1
                                            TextInput {
                                                id: srcInput
                                                anchors.fill: parent; anchors.leftMargin: 8; anchors.rightMargin: 8
                                                verticalAlignment: Text.AlignVCenter
                                                text: "" + modelData.new_source_id
                                                color: Theme.textPrimary; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSmall
                                                validator: RegularExpressionValidator { regularExpression: /^[0-9]{0,10}$/ }
                                                clip: true
                                                onEditingFinished: hircEditorPage.editRemapTargetRequested(
                                                    rowRoot.rowData.pck_name, rowRoot.rowData.bnk_id, rowRoot.rowData.track_obj_id,
                                                    modelData.slot, modelData.index, text)
                                            }
                                        }
                                    }
                                }
                                Text {
                                    visible: rowRoot.rowData.kind === "add_wem"
                                    width: sourceCol.width
                                    height: 26
                                    verticalAlignment: Text.AlignVCenter
                                    text: rowRoot.rowData.source_display || ""
                                    color: Theme.textPrimary; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSmall
                                    elide: Text.ElideRight
                                }
                                // With no remap staged, show the current sources/playlist so it's clear they're preserved.
                                Repeater {
                                    model: (rowRoot.rowData.kind === "track" && (rowRoot.rowData.remaps || []).length === 0)
                                           ? (rowRoot.rowData.current_sources || []) : []
                                    Text {
                                        width: sourceCol.width
                                        height: 22
                                        verticalAlignment: Text.AlignVCenter
                                        text: modelData
                                        color: Theme.textSecondary; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSmall
                                        elide: Text.ElideRight
                                    }
                                }
                                Text {
                                    visible: rowRoot.rowData.kind === "track" && (rowRoot.rowData.remaps || []).length === 0
                                             && (rowRoot.rowData.current_sources || []).length === 0
                                    height: 26
                                    verticalAlignment: Text.AlignVCenter
                                    text: "—"
                                    color: Theme.textSecondary; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSmall
                                }
                            }

                            Item {
                                Layout.preferredWidth: 118
                                Layout.preferredHeight: 26
                                Layout.alignment: Qt.AlignVCenter
                                Text {
                                    visible: rowRoot.rowData.kind !== "track"
                                    anchors.left: parent.left; anchors.verticalCenter: parent.verticalCenter
                                    text: "—"; color: Theme.textSecondary; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSmall
                                }
                                SpinBox {
                                    id: hircLoopSpin
                                    from: 0
                                    to: 3600000
                                    anchors.fill: parent
                                    editable: true
                                    locale: Qt.locale("C")
                                    visible: rowRoot.rowData.kind === "track"
                                    // Effective loop is the staged value if edited, else the track's current loop.
                                    // This shows an unedited loop's real value instead of a misleading 0.
                                    value: {
                                        var eff = rowRoot.rowData.loop_ms === "" ? rowRoot.rowData.current_loop_ms : rowRoot.rowData.loop_ms
                                        return (eff === "" || eff === undefined) ? 0 : Math.max(0, Math.round(parseFloat(eff)))
                                    }
                                    textFromValue: function(value, locale) {
                                        return formatDurationMs(value)
                                    }
                                    valueFromText: function(text, locale) {
                                        var ms = parseDurationMs(text)
                                        return ms === null ? hircLoopSpin.value : ms
                                    }
                                    background: Rectangle {
                                        HoverHandler { id: loopSpinBgHover }
                                        color: loopSpinBgHover.hovered
                                            ? Qt.lighter(Theme.cardBackground, 1.08)
                                            : Theme.cardBackground
                                        radius: Theme.radiusSmall
                                    }
                                    contentItem: TextInput {
                                        text: hircLoopSpin.textFromValue(hircLoopSpin.value, hircLoopSpin.locale)
                                        anchors.fill: parent
                                        anchors.leftMargin: 6
                                        anchors.rightMargin: 22
                                        font.family: Theme.fontFamily
                                        font.pixelSize: Theme.fontSizeSmall
                                        color: Theme.textPrimary
                                        horizontalAlignment: Text.AlignHCenter
                                        verticalAlignment: Text.AlignVCenter
                                        readOnly: !hircLoopSpin.editable
                                        validator: hircLoopSpin.validator
                                        inputMethodHints: Qt.ImhNone
                                        selectByMouse: true
                                        clip: true
                                        onTextEdited: {
                                            hircLoopSpin.value = hircLoopSpin.valueFromText(text, hircLoopSpin.locale)
                                        }
                                    }
                                    up.indicator: Rectangle {
                                        x: parent.width - width
                                        y: 0
                                        width: 20
                                        height: parent.height / 2
                                        color: "transparent"
                                        Text {
                                            anchors.centerIn: parent
                                            text: "+"
                                            color: Theme.textPrimary
                                            font.family: Theme.fontFamily
                                            font.pixelSize: 12
                                        }
                                    }
                                    down.indicator: Rectangle {
                                        x: parent.width - width
                                        y: parent.height / 2
                                        width: 20
                                        height: parent.height / 2
                                        color: "transparent"
                                        Text {
                                            anchors.centerIn: parent
                                            text: "-"
                                            color: Theme.textPrimary
                                            font.family: Theme.fontFamily
                                            font.pixelSize: 12
                                        }
                                    }
                                    onValueChanged: {
                                        // Baseline is the effective current loop, so initialising to the real loop is a no-op.
                                        // Only a genuine change stages a loop edit.
                                        var eff = rowRoot.rowData.loop_ms === "" ? rowRoot.rowData.current_loop_ms : rowRoot.rowData.loop_ms
                                        var cur = (eff === "" || eff === undefined) ? 0 : Math.max(0, Math.round(parseFloat(eff)))
                                        if (value !== cur)
                                            hircEditorPage.editTrackLoopRequested(
                                                rowRoot.rowData.pck_name, rowRoot.rowData.bnk_id, rowRoot.rowData.track_obj_id,
                                                value > 0 ? "" + value : "")
                                    }
                                }
                            }

                            Item {
                                Layout.preferredWidth: 96
                                Layout.preferredHeight: 26
                                Layout.alignment: Qt.AlignVCenter
                                Text {
                                    visible: rowRoot.rowData.kind !== "track"
                                    anchors.left: parent.left; anchors.verticalCenter: parent.verticalCenter
                                    text: "—"; color: Theme.textSecondary; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSmall
                                }
                                SpinBox {
                                    anchors.fill: parent
                                    visible: rowRoot.rowData.kind === "track"
                                    from: -960
                                    to: 240
                                    stepSize: 5
                                    editable: true
                                    locale: Qt.locale("C")
                                    value: rowRoot.rowData.volume_db === "" ? 0 : Math.round(parseFloat(rowRoot.rowData.volume_db) * 10)
                                    textFromValue: function(value, locale) {
                                        return (value / 10.0).toFixed(1)
                                    }
                                    valueFromText: function(text, locale) {
                                        var v = parseFloat(text)
                                        if (isNaN(v)) return 0
                                        return Math.round(v * 10)
                                    }
                                    onValueModified: hircEditorPage.editTrackVolumeRequested(
                                        rowRoot.rowData.pck_name, rowRoot.rowData.bnk_id, rowRoot.rowData.track_obj_id,
                                        (value / 10.0).toFixed(1))
                                    background: Rectangle {
                                        color: Theme.inputBackground || "#2a2a2a"
                                        border.color: Theme.cardBackground
                                        border.width: 1
                                        radius: Theme.radiusSmall
                                    }
                                    contentItem: TextInput {
                                        text: parent.textFromValue(parent.value, parent.locale)
                                        font.family: Theme.fontFamily
                                        font.pixelSize: Theme.fontSizeSmall
                                        color: Theme.textPrimary
                                        horizontalAlignment: Qt.AlignHCenter
                                        verticalAlignment: Qt.AlignVCenter
                                        readOnly: !parent.editable
                                        validator: DoubleValidator { bottom: -96; top: 24; decimals: 1; notation: DoubleValidator.StandardNotation; locale: "C" }
                                    }
                                    up.indicator: Item { width: 0 }
                                    down.indicator: Item { width: 0 }
                                }
                            }

                            Item {
                                Layout.preferredWidth: 84
                                Layout.preferredHeight: 26
                                Layout.alignment: Qt.AlignVCenter
                                XXARButton {
                                    anchors.fill: parent
                                    text: qsTranslate("Application", "Remove")
                                    buttonColor: Theme.disabledAccent
                                    textColor: Theme.textPrimary
                                    fontSize: 11
                                    onClicked: {
                                        if (rowRoot.rowData.kind === "add_wem")
                                            hircEditorPage.removeMediaAddRequested(rowRoot.rowData.pck_name, rowRoot.rowData.wem_id)
                                        else
                                            hircEditorPage.removeTrackPatchRequested(rowRoot.rowData.pck_name, rowRoot.rowData.bnk_id, rowRoot.rowData.track_obj_id)
                                    }
                                }
                            }
                        }
                    }

                    Text {
                        anchors.centerIn: parent
                        text: qsTranslate("Application", "No changes yet.\nStage some edits to see them here.")
                        color: Theme.textSecondary
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeNormal
                        horizontalAlignment: Text.AlignHCenter
                        visible: !hircEditorPage.draftChanges || hircEditorPage.draftChanges.length === 0
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: Theme.spacingSmall
                    Item { Layout.fillWidth: true }

                    XXARButton {
                        text: qsTranslate("Application", "Apply Changes")
                        buttonColor: Theme.primaryAccent
                        visible: hircEditorPage.draftCount > 0
                        onClicked: {
                            hircEditorPage.applyAllRequested()
                            changesOverlay.closing = true
                            changesHideTimer.start()
                        }
                    }

                    XXARButton {
                        text: qsTranslate("Application", "Close")
                        onClicked: { changesOverlay.closing = true; changesHideTimer.start() }
                    }
                }
            }
        }
    }

    Item {
        id: metadataOverlay
        visible: false
        anchors.fill: parent
        z: 2001
        property bool closing: false

        Timer {
            id: metadataHideTimer
            interval: 200
            onTriggered: { metadataOverlay.visible = false; metadataOverlay.closing = false }
        }

        Rectangle {
            anchors.fill: parent
            color: "#80000000"
            opacity: (!metadataOverlay.closing && metadataOverlay.visible) ? 1.0 : 0.0
            Behavior on opacity { NumberAnimation { duration: 200 } }

            Image {
                anchors.fill: parent
                source: "../assets/" + assetsDir + "/gradient.png"
                fillMode: Image.Stretch
                mipmap: true
                opacity: 0.6
            }

            OverlayBackdropMouseArea {
                dialog: metadataDialog
                onClickedOutside: { metadataOverlay.closing = true; metadataHideTimer.start() }
            }
        }

        Rectangle {
            id: metadataDialog
            width: Math.min(500, parent.width - 60)
            height: Math.min(560, parent.height - 80)
            anchors.centerIn: parent
            color: Theme.surfaceColor
            radius: Theme.radiusLarge
            border.color: Theme.cardBackground
            border.width: 1
            scale: (!metadataOverlay.closing && metadataOverlay.visible) ? 1.0 : 0.9
            opacity: (!metadataOverlay.closing && metadataOverlay.visible) ? 1.0 : 0.0
            Behavior on scale { NumberAnimation { duration: 200; easing.type: Easing.OutBack } }
            Behavior on opacity { NumberAnimation { duration: 200 } }

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 20
                spacing: 12

                Text {
                    text: qsTranslate("Application", "Mod Package Metadata")
                    color: Theme.primaryAccent
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeNormal
                    font.bold: true
                    Layout.fillWidth: true
                }

                Text { text: qsTranslate("Application", "Name*:"); color: Theme.textPrimary; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSmall }
                Rectangle {
                    Layout.fillWidth: true; height: Theme.buttonHeight
                    color: Theme.cardBackground; radius: Theme.radiusMedium
                    TextInput {
                        id: hircMetaNameInput
                        anchors.fill: parent; anchors.leftMargin: 14; anchors.rightMargin: 14
                        verticalAlignment: Text.AlignVCenter
                        color: Theme.textPrimary; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSmall; clip: true
                        Text {
                            anchors.fill: parent; verticalAlignment: Text.AlignVCenter
                            color: Theme.textSecondary; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSmall
                            text: qsTranslate("Application", "My Awesome Mod")
                            visible: !hircMetaNameInput.text && !hircMetaNameInput.activeFocus
                        }
                    }
                }

                Text { text: qsTranslate("Application", "Author*:"); color: Theme.textPrimary; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSmall }
                Rectangle {
                    Layout.fillWidth: true; height: Theme.buttonHeight
                    color: Theme.cardBackground; radius: Theme.radiusMedium
                    TextInput {
                        id: hircMetaAuthorInput
                        anchors.fill: parent; anchors.leftMargin: 14; anchors.rightMargin: 14
                        verticalAlignment: Text.AlignVCenter
                        color: Theme.textPrimary; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSmall; clip: true
                        Text {
                            anchors.fill: parent; verticalAlignment: Text.AlignVCenter
                            color: Theme.textSecondary; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSmall
                            text: qsTranslate("Application", "Your Name")
                            visible: !hircMetaAuthorInput.text && !hircMetaAuthorInput.activeFocus
                        }
                    }
                }

                Text { text: qsTranslate("Application", "Version:"); color: Theme.textPrimary; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSmall }
                Rectangle {
                    Layout.fillWidth: true; height: Theme.buttonHeight
                    color: Theme.cardBackground; radius: Theme.radiusMedium
                    TextInput {
                        id: hircMetaVersionInput
                        anchors.fill: parent; anchors.leftMargin: 14; anchors.rightMargin: 14
                        verticalAlignment: Text.AlignVCenter
                        color: Theme.textPrimary; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSmall
                        text: "1.0.0"; clip: true
                    }
                }

                Text { text: qsTranslate("Application", "Description:"); color: Theme.textPrimary; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSmall }
                Rectangle {
                    Layout.fillWidth: true; Layout.preferredHeight: 100
                    color: Theme.cardBackground; radius: Theme.radiusMedium
                    TextEdit {
                        id: hircMetaDescInput
                        anchors.fill: parent; anchors.margins: 14
                        color: Theme.textPrimary; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSmall
                        wrapMode: TextEdit.Wrap; clip: true
                        Text {
                            anchors.fill: parent
                            color: Theme.textSecondary; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSmall
                            text: qsTranslate("Application", "Describe what your mod does...")
                            visible: !hircMetaDescInput.text && !hircMetaDescInput.activeFocus
                        }
                    }
                }

                Text { text: qsTranslate("Application", "Thumbnail:"); color: Theme.textPrimary; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSmall }
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8
                    Rectangle {
                        Layout.fillWidth: true; height: Theme.buttonHeight
                        color: Theme.cardBackground; radius: Theme.radiusMedium
                        TextInput {
                            id: hircMetaThumbInput
                            anchors.fill: parent; anchors.leftMargin: 14; anchors.rightMargin: 14
                            verticalAlignment: Text.AlignVCenter
                            color: Theme.textPrimary; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSmall
                            readOnly: true; clip: true
                            Text {
                                anchors.fill: parent; verticalAlignment: Text.AlignVCenter
                                color: Theme.textSecondary; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSmall
                                text: qsTranslate("Application", "Optional: Select thumbnail image")
                                visible: !hircMetaThumbInput.text
                            }
                        }
                    }
                    XXARButton {
                        text: qsTranslate("Application", "Browse")
                        onClicked: hircEditorPage.browseThumbnailRequested()
                    }
                }

                Item { Layout.fillHeight: true }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: Theme.spacingSmall
                    Item { Layout.fillWidth: true }

                    XXARButton {
                        text: qsTranslate("Application", "Cancel")
                        buttonColor: Theme.disabledAccent
                        onClicked: { metadataOverlay.closing = true; metadataHideTimer.start() }
                    }

                    XXARButton {
                        text: qsTranslate("Application", "Create Package")
                        buttonColor: Theme.primaryAccent
                        onClicked: {
                            var name = hircMetaNameInput.text.trim()
                            var author = hircMetaAuthorInput.text.trim()
                            if (!name || !author) return
                            var version = hircMetaVersionInput.text.trim() || "1.0.0"
                            hircEditorPage.createModRequested(name, author, version,
                                hircMetaDescInput.text.trim(), hircMetaThumbInput.text.trim())
                            metadataOverlay.closing = true
                            metadataHideTimer.start()
                        }
                    }
                }
            }
        }
    }
}
