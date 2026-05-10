import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import "../components"
import "."

Item {
    id: hircEditorPage
    objectName: "hircEditorPage"
    clip: true

    // ── Public signals ──────────────────────────────────────────────────
    signal refreshRequested()
    signal bnkSelected(string pckName, var bnkId)
    signal patchSourceRequested(string pckName, var absOffsetInPck, var oldWem, var newWem)
    signal patchLoopRequested(string pckName, var bnkId, var trackObjId, var loopMs)
    signal patchVolumeRequested(string pckName, var absOffsetInPck, var dbValue)
    signal refreshMusicPcksRequested()
    signal browseWemFileRequested()
    signal addWemRequested(string pckName, var wemId, string wemFilePath)

    // ── Public state (set from connector) ───────────────────────────────
    property var bnkList: []
    property var hircObjects: []
    property string statusText: qsTranslate("Application", "Idle")
    property string selectedPck: ""
    property var selectedBnkId: 0
    property string hircFilter: "all"
    property string objectFilter: ""
    // Map { pck_name: true } for currently-expanded pck nodes in the tree.
    property var expandedPcks: ({})
    // Cached flat tree model fed to the ListView. Only rebuilt when one of
    // (bnkList, expandedPcks, search text) changes — assigning a fresh JS
    // array directly to ListView.model resets the scroll position, which is
    // disruptive when the user just clicked a bnk row.
    property var bnkTreeModel: []

    // Add-WEM panel state
    property var musicPckList: []
    property string wemAddPath: ""
    property string wemAddTargetPck: ""
    property string wemAddIdText: ""

    // ── Pending edits (per MusicTrack) ──────────────────────────────────
    // Flat dict: keys "<obj_id>:<kind>[:<idx>]" -> string value typed by user.
    // Kinds: "src" (AkBankSourceData), "pl" (TrackSrcInfo), "loop", "vol".
    // Values are kept as strings to avoid lossy float round-trips while editing.
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

    function hasPendingForTrack(objId, modelData) {
        for (var k in pending) {
            if (k.indexOf(objId + ":") !== 0) continue
            var val = pending[k]
            // Compare against current modelData; if the typed value matches the
            // existing one we treat it as no-op (button stays disabled).
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
                var v = parseFloat(val)
                if (!isNaN(v) && v !== modelData.loop_ms) return true
            } else if (kind === "vol") {
                var v = parseFloat(val)
                if (!isNaN(v) && v !== modelData.volume_db) return true
            }
        }
        return false
    }

    function applyPendingForTrack(objId, modelData) {
        // Sources
        for (var i = 0; i < (modelData.sources || []).length; i++) {
            var k = pendingKey(objId, "src", i)
            if (k in pending) {
                var src = modelData.sources[i]
                var v = parseInt(pending[k])
                if (!isNaN(v) && v !== src.source_id) {
                    hircEditorPage.patchSourceRequested(
                        hircEditorPage.selectedPck, src.abs_offset_in_pck,
                        src.source_id, v
                    )
                }
            }
        }
        // Playlist
        for (var j = 0; j < (modelData.playlist || []).length; j++) {
            var k2 = pendingKey(objId, "pl", j)
            if (k2 in pending) {
                var ts = modelData.playlist[j]
                var v2 = parseInt(pending[k2])
                if (!isNaN(v2) && v2 !== ts.source_id) {
                    hircEditorPage.patchSourceRequested(
                        hircEditorPage.selectedPck, ts.abs_offset_in_pck,
                        ts.source_id, v2
                    )
                }
            }
        }
        // Loop
        var loopK = pendingKey(objId, "loop")
        if (loopK in pending) {
            var lv = parseFloat(pending[loopK])
            if (!isNaN(lv) && lv !== modelData.loop_ms) {
                hircEditorPage.patchLoopRequested(
                    hircEditorPage.selectedPck, hircEditorPage.selectedBnkId, objId, lv
                )
            }
        }
        // Volume
        var volK = pendingKey(objId, "vol")
        if (volK in pending) {
            var vv = parseFloat(pending[volK])
            if (!isNaN(vv) && vv !== modelData.volume_db) {
                hircEditorPage.patchVolumeRequested(
                    hircEditorPage.selectedPck, modelData.volume_offset_abs, vv
                )
            }
        }
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
    function onWemAdded(pck, wid, src) {
        statusText = qsTranslate("Application", "Added WEM %1 to %2 (from %3)")
                        .replace("%1", wid).replace("%2", pck).replace("%3", src)
        wemAddPath = ""
        wemAddIdText = ""
        // Refresh: pck size changed → re-list pcks; if currently inspecting a
        // bnk in that pck, re-fetch HIRC too.
        hircEditorPage.refreshMusicPcksRequested()
        if (selectedPck) {
            hircEditorPage.bnkSelected(selectedPck, selectedBnkId)
        }
    }

    function togglePckExpanded(pckName) {
        var copy = {}
        for (var k in expandedPcks) copy[k] = expandedPcks[k]
        if (copy[pckName]) delete copy[pckName]
        else copy[pckName] = true
        expandedPcks = copy
    }

    function rebuildBnkTreeModel() {
        // Preserve the current scroll position across the model reassignment.
        var savedY = bnkListView ? bnkListView.contentY : 0
        bnkTreeModel = buildBnkTreeModel(bnkSearch ? bnkSearch.text : "")
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
            // Per-pck filtering: keep pck if name matches filter OR any child bnk_id matches.
            var pckMatches = !f || pck.toLowerCase().indexOf(f) !== -1
            var childMatches = []
            if (!pckMatches && f) {
                for (var c = 0; c < children.length; c++) {
                    if (("" + children[c].bnk_id).indexOf(f) !== -1) {
                        childMatches.push(children[c])
                    }
                }
            }
            if (!pckMatches && childMatches.length === 0) continue
            var totalMusic = 0
            for (var t = 0; t < children.length; t++) totalMusic += children[t].music_object_count
            // children share the same pck_name AND is_override (we deduped
            // upstream), so we can take the flag from the first child.
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

    // ── Setters used by HircEditorConnector via QMetaObject.invokeMethod ─────
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
    function setStatusText(msg) { statusText = msg }
    function onPatchApplied(pck, off, oldW, newW) {
        statusText = qsTranslate("Application", "Patched %1 @%2: %3 -> %4")
                        .replace("%1", pck).replace("%2", off)
                        .replace("%3", oldW).replace("%4", newW)
        if (selectedPck) { hircEditorPage.bnkSelected(selectedPck, selectedBnkId) }
    }
    function onLoopPatched(pck, bnkId, trackId, ms) {
        statusText = qsTranslate("Application", "Loop patched: track %1 -> %2 ms")
                        .replace("%1", trackId).replace("%2", ms.toFixed(2))
        if (selectedPck) { hircEditorPage.bnkSelected(selectedPck, selectedBnkId) }
    }
    function onVolumePatched(pck, off, db) {
        statusText = qsTranslate("Application", "Volume patched @%1: %2 dB")
                        .replace("%1", off).replace("%2", db.toFixed(2))
        if (selectedPck) { hircEditorPage.bnkSelected(selectedPck, selectedBnkId) }
    }


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

                            TextField {
                                id: bnkSearch
                                Layout.fillWidth: true
                                placeholderText: qsTranslate("Application", "Filter by pck/bnk_id...")
                                color: Theme.textPrimary
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSizeSmall
                                background: Rectangle {
                                    color: Theme.surfaceColor
                                    radius: Theme.radiusMedium
                                    border.color: Theme.cardBackground
                                    border.width: 1
                                }
                                onTextChanged: hircEditorPage.rebuildBnkTreeModel()
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

                            TextField {
                                id: objectSearch
                                Layout.fillWidth: true
                                placeholderText: qsTranslate("Application", "Filter by obj_id or wem source_id...")
                                color: Theme.textPrimary
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSizeSmall
                                background: Rectangle {
                                    color: Theme.surfaceColor
                                    radius: Theme.radiusMedium
                                    border.color: Theme.cardBackground
                                    border.width: 1
                                }
                                onTextChanged: hircEditorPage.objectFilter = text.toLowerCase()
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
                                                hay += " " + o.sources[s].source_id
                                            }
                                            for (var p = 0; p < (o.playlist || []).length; p++) {
                                                hay += " " + o.playlist[p].source_id
                                            }
                                            if (hay.indexOf(q) === -1) continue
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
                                                        validator: RegExpValidator { regExp: /^[0-9]{1,10}$/ }
                                                        onTextEdited: hircEditorPage.setPending(
                                                                          track.obj_id, "src",
                                                                          modelData.index, text
                                                                      )
                                                    }
                                                    Text {
                                                        text: "@ " + modelData.abs_offset_in_pck
                                                        color: Theme.textSecondary
                                                        font.family: Theme.fontFamily
                                                        font.pixelSize: 10
                                                        Layout.fillWidth: true
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
                                                        validator: RegExpValidator { regExp: /^[0-9]{1,10}$/ }
                                                        onTextEdited: hircEditorPage.setPending(
                                                                          track.obj_id, "pl",
                                                                          modelData.index, text
                                                                      )
                                                    }
                                                    Text {
                                                        text: "@ " + modelData.abs_offset_in_pck
                                                        color: Theme.textSecondary
                                                        font.family: Theme.fontFamily
                                                        font.pixelSize: 10
                                                        Layout.fillWidth: true
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
                                                    text: qsTranslate("Application", "Loop (ms)")
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
                                                                ? track.loop_ms.toFixed(2) : ""
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
                                                    validator: DoubleValidator { bottom: 0; decimals: 6 }
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

                                        // Volume (visible if AkPropBundle Volume present — works for
                                        // MusicTrack AND container types: MusicSegment / RanSeqCntr / SwitchCntr)
                                        Rectangle {
                                            Layout.fillWidth: true
                                            height: 30
                                            radius: Theme.radiusSmall / 3
                                            color: Qt.darker(Theme.primaryAccent, 6.5)
                                            visible: track.has_volume === true

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
                                                    validator: DoubleValidator { bottom: -100; top: 24; decimals: 4 }
                                                    onTextEdited: hircEditorPage.setPending(
                                                                      track.obj_id, "vol", null, text
                                                                  )
                                                }
                                                Text {
                                                    text: "@ " + track.volume_offset_abs
                                                    color: Theme.textSecondary
                                                    font.family: Theme.fontFamily
                                                    font.pixelSize: 10
                                                    Layout.fillWidth: true
                                                    elide: Text.ElideRight
                                                }
                                            }
                                        }

                                        // ── Apply button (any HIRC entry with at least one editable field) ──
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
                                                    text: qsTranslate("Application", "Apply")
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
                                                    onClicked: hircEditorPage.applyPendingForTrack(track.obj_id, track)
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
                                text: hircEditorPage.wemAddPath || qsTranslate("Application", "(no .wem selected)")
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
                            validator: RegExpValidator { regExp: /^[0-9]{1,10}$/ }
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
                                text: qsTranslate("Application", "Add")
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
                                    hircEditorPage.addWemRequested(pck, wid, hircEditorPage.wemAddPath)
                                }
                            }
                        }
                    }
                }

                // ── Status bar ──────────────────────────────────────────
                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 28
                    radius: Theme.radiusMedium
                    color: Theme.surfaceDark

                    Text {
                        anchors.fill: parent
                        anchors.leftMargin: Theme.spacingMedium
                        anchors.rightMargin: Theme.spacingMedium
                        verticalAlignment: Text.AlignVCenter
                        text: hircEditorPage.statusText
                        color: Theme.textSecondary
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeSmall
                        elide: Text.ElideRight
                    }
                }
            }
        }
    }
}
