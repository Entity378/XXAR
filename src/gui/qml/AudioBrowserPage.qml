import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import QtQuick.Window 2.15
import QtQuick.Effects
import "../components"
import "."

Item {
    id: audioBrowser
    objectName: "audioBrowserPage"
    clip: true
    property bool changesDialogOpen: changesOverlay.visible && !changesOverlay.closing

    function getMainWindow() {
        var item = audioBrowser
        while (item.parent) {
            item = item.parent
        }
        return item
    }

    signal languageTabChanged(int index)
    signal searchRequested(string query)
    signal clearSearchClicked()
    signal findMatchingSoundClicked()
    signal mergeWemToggled(bool checked)
    signal hideUselessPckToggled(bool checked)
    signal hideEmptyBnkToggled(bool checked)
    signal normalizeAudioToggled(bool checked)
    signal normalizeTargetLufsSet(int lufs)
    signal changeLoopPointModeSet(string pckFile, string trackerKey, string mode)
    signal changeLoopPointManualMsSet(string pckFile, string trackerKey, string durationText)
    signal changeVolumeEnabledSet(string pckFile, string trackerKey, bool enabled)
    signal changeVolumeDbSet(string pckFile, string trackerKey, string volumeDb)
    signal treeItemExpanded(string itemId, string itemType)

    signal treeItemDoubleClicked(string itemId, string itemType, string pckPath)
    signal treeItemRightClicked(string itemId, string itemType, string pckPath, real x, real y)
    signal tagSoundRequested(string itemId, string itemType, string pckPath)
    signal importModForEditingClicked()
    signal showChangesClicked()
    signal applyChangesClicked()
    signal exportModClicked()
    signal createModPackageRequested(string name, string author, string version, string description, string thumbnailPath)
    signal resetAllClicked()
    signal removeChangeRequested(string pckFile, string fileId)
    signal navigateToChangeClicked(string pckFile, string fileId, string itemType, string bnkId)
    signal playReplacementClicked(string wemPath)
    signal playOriginalClicked(string fileId, string itemType, string pckPath, string bnkId)
    signal playClicked()
    signal pauseClicked()
    signal stopClicked()
    signal volumeAdjusted(int value)
    signal seekRequested(real position)
    signal wipDialogRequested()
    signal openAudioFolderClicked(string folderType)
    signal downloadOfficialTagDbClicked()
    signal applyOfficialTagDb(bool merge)
    signal dismissTagDbNotify(bool dontShowAgain)
    signal openTagDbFolderClicked()
    signal cancelMatchClicked()
    signal matchResultNavigateClicked(string fileId, string itemType, string pckPath, string bnkId)

    property real contextMenuX: 0
    property real contextMenuY: 0
    property string gameDirectory: ""
    property string statusText: qsTranslate("Application", "Select a game audio directory to start")
    property string nowPlayingText: qsTranslate("Application", "Not playing")
    property real playbackProgress: 0.0
    property string timeText: "00:00 / 00:00"
    property int volume: 50
    property bool isPlaying: false
    property bool isPaused: false
    property bool playbackEnabled: false
    property bool mergeWemChecked: true
    property bool hideUselessPckChecked: true
    property bool hideEmptyBnkChecked: true
    property bool normalizeAudioChecked: true
    property int normalizeTargetLufs: -9
    property string highlightItemId: ""
    property int changesCount: 0
    property bool tagDbDownloading: false
    property int tagDbEntryCount: 0
    property bool tagDbNotifyVisible: false
    property int tagDbNewCount: 0
    property bool matchInProgress: false
    property int matchCurrent: 0
    property int matchTotal: 0

    property string highlightPckPath: ""
    property bool sortBySizeAsc: false
    property bool sortByDurationAsc: false

    function loopModeToIndex(mode) {
        if (mode === "manual") return 1
        if (mode === "disabled") return 2
        return 0
    }

    function loopIndexToMode(index) {
        if (index === 1) return "manual"
        if (index === 2) return "disabled"
        return "auto"
    }

    function pad2(n) {
        return n < 10 ? "0" + n : "" + n
    }

    function pad3(n) {
        if (n < 10) return "00" + n
        if (n < 100) return "0" + n
        return "" + n
    }

    function formatDurationMs(totalMs) {
        var ms = Math.max(0, Math.floor(Number(totalMs) || 0))
        var minutes = Math.floor(ms / 60000)
        var seconds = Math.floor((ms % 60000) / 1000)
        var millis = ms % 1000
        return pad2(minutes) + ":" + pad2(seconds) + ":" + pad3(millis)
    }

    ListModel { id: languageTabsModel }
    ListModel { id: treeModel }

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
                    visible: languageTabsModel.count > 0

                    Row {
                        id: langTabs
                        objectName: "tutorialLangTabs"
                        spacing: Theme.spacingSmall

                        property int currentIndex: 0

                        Repeater {
                            model: languageTabsModel

                            Item {
                                height: Theme.buttonHeight
                                width: tabLabel.implicitWidth + 28

                                Rectangle {
                                    anchors.fill: parent
                                    color: {
                                        var active = langTabs.currentIndex === index
                                        if (active) return Theme.primaryAccent
                                        return tabMouse.pressed ? Qt.darker(Theme.cardBackground, 1.1)
                                             : tabMouse.containsMouse ? Qt.lighter(Theme.cardBackground, 1.1)
                                             : Theme.cardBackground
                                    }
                                    radius: Theme.radiusMedium
                                    Behavior on color { ColorAnimation { duration: 100 } }
                                }

                                Text {
                                    id: tabLabel
                                    anchors.centerIn: parent
                                    text: model.label
                                    color: langTabs.currentIndex === index ? Theme.textOnAccent : Theme.textPrimary
                                    font.family: Theme.fontFamily
                                    font.pixelSize: Theme.fontSizeSmall
                                }

                                MouseArea {
                                    id: tabMouse
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: {
                                        langTabs.currentIndex = index
                                        languageTabChanged(index)
                                    }
                                }
                            }
                        }
                    }

                    Item { Layout.fillWidth: true }

                    ComboBox {
                        id: openFolderCombo
                        visible: gameDirectory !== ""
                        implicitWidth: findMatchingSoundBtn.width
                        Layout.preferredHeight: Theme.buttonHeight
                        model: ["StreamingAssets", "Persistent"]
                        displayText: qsTranslate("Application", "Open Game Folder")
                        z: 100

                        onActivated: {
                            var folderType = index === 0 ? "streaming" : "persistent"
                            openAudioFolderClicked(folderType)
                        }

                        background: Rectangle {
                            HoverHandler { id: abFolderBgHover }
                            color: openFolderCombo.pressed ? Qt.darker(Theme.primaryAccent, 1.1)
                                 : abFolderBgHover.hovered ? Qt.lighter(Theme.primaryAccent, 1.1)
                                 : Theme.primaryAccent
                            radius: Theme.radiusMedium
                            Behavior on color { ColorAnimation { duration: Theme.animationDuration } }
                            scale: openFolderCombo.pressed ? 0.97 : 1.0
                            Behavior on scale {
                                NumberAnimation { duration: Theme.animationDuration; easing.type: Theme.easingStandard }
                            }
                        }

                        contentItem: Text {
                            text: openFolderCombo.displayText
                            color: Theme.textOnAccent
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSizeMedium
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                            leftPadding: 24
                            rightPadding: 20
                        }

                        indicator: Rectangle {
                            x: openFolderCombo.width - width - 10
                            y: (openFolderCombo.height - height) / 2
                            width: 20
                            height: 20
                            color: "transparent"

                            Text {
                                anchors.centerIn: parent
                                text: "\u25BC"
                                color: Theme.textOnAccent
                                font.pixelSize: 10
                            }
                        }

                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onPressed: mouse.accepted = false
                        }

                        delegate: ItemDelegate {
                            id: abFolderDelegate
                            width: openFolderCombo.width - 8
                            height: Theme.buttonHeight
                            highlighted: openFolderCombo.highlightedIndex === index

                            HoverHandler { id: abFolderDelegateHover }

                            background: Rectangle {
                                color: {
                                    if (abFolderDelegate.highlighted) return Theme.primaryAccent
                                    if (abFolderDelegateHover.hovered) return Qt.lighter(Theme.surfaceDark, 1.3)
                                    return Theme.surfaceDark
                                }
                                radius: Theme.radiusSmall
                                Behavior on color { ColorAnimation { duration: 100 } }
                            }

                            contentItem: Text {
                                text: modelData
                                color: abFolderDelegate.highlighted ? Theme.textOnAccent : Theme.textPrimary
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSizeSmall
                                verticalAlignment: Text.AlignVCenter
                                leftPadding: 14
                            }
                        }

                        popup: Popup {
                            y: openFolderCombo.height + 4
                            width: openFolderCombo.width
                            padding: 4
                            z: 200

                            background: Rectangle {
                                color: Theme.surfaceDark
                                radius: Theme.radiusMedium
                                border.color: Qt.rgba(1, 1, 1, 0.1)
                                border.width: 1

                                layer.enabled: true
                                layer.effect: MultiEffect {
                                    shadowEnabled: true
                                    shadowHorizontalOffset: 0
                                    shadowVerticalOffset: 4
                                    shadowBlur: 0.50
                                    shadowColor: "#80000000"
                                }
                            }

                            contentItem: ListView {
                                clip: true
                                implicitHeight: contentHeight
                                model: openFolderCombo.popup.visible ? openFolderCombo.delegateModel : null
                                currentIndex: openFolderCombo.highlightedIndex
                                spacing: 2

                                ScrollIndicator.vertical: ScrollIndicator {
                                    active: true
                                }
                            }
                        }
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: Theme.spacingSmall

                    Rectangle {
                        Layout.fillWidth: true
                        height: Theme.buttonHeight
                        color: Theme.cardBackground
                        radius: Theme.radiusMedium

                        TextInput {
                            id: searchInput
                            objectName: "tutorialSearchInput"
                            anchors.fill: parent
                            anchors.leftMargin: 14
                            anchors.rightMargin: 14
                            verticalAlignment: Text.AlignVCenter
                            color: Theme.textPrimary
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSizeSmall
                            clip: true

                            Keys.onReturnPressed: searchRequested(text)

                            Text {
                                anchors.fill: parent
                                verticalAlignment: Text.AlignVCenter
                                color: Theme.textPrimary
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSizeSmall
                                text: qsTranslate("Application", "Search by ID, name, or tag")
                                visible: !searchInput.text && !searchInput.activeFocus
                            }
                        }
                    }

                    XXARButton {
                        text: qsTranslate("Application", "Search")
                        onClicked: searchRequested(searchInput.text)
                    }
                    XXARButton {
                        text: qsTranslate("Application", "Clear")
                        onClicked: {
                            searchInput.text = ""
                            clearSearchClicked()
                        }
                    }
                    XXARButton {
                        id: findMatchingSoundBtn
                        text: qsTranslate("Application", "Find Matching Sound")
                        buttonColor: Theme.primaryAccent
                        onClicked: audioMatchDialog.show()
                    }
                }

                Item {
                    width: optionsBtn.width
                    height: optionsBtn.height

                    Rectangle {
                        id: optionsBtn
                        width: optionsBtnRow.width + Theme.spacingMedium * 2
                        height: Theme.buttonHeight
                        radius: Theme.radiusMedium
                        color: optionsBtnMouse.pressed ? Qt.darker(Theme.cardBackground, 1.1) :
                               optionsBtnMouse.containsMouse ? Qt.lighter(Theme.cardBackground, 1.1) : Theme.cardBackground
                        Behavior on color { ColorAnimation { duration: Theme.animationDuration } }
                        scale: optionsBtnMouse.pressed ? 0.97 : 1.0
                        Behavior on scale { NumberAnimation { duration: Theme.animationDuration } }

                        Text {
                            id: optionsBtnRow
                            anchors.centerIn: parent
                            text: qsTranslate("Application", "Options")
                            color: Theme.textPrimary
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSizeMedium
                        }

                        MouseArea {
                            id: optionsBtnMouse
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: optionsPopup.visible ? optionsPopup.close() : optionsPopup.open()
                        }
                    }

                    Popup {
                        id: optionsPopup
                        y: optionsBtn.height + 4
                        padding: 0
                        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutsideParent

                        enter: Transition {
                            ParallelAnimation {
                                NumberAnimation { property: "opacity"; from: 0.0; to: 1.0; duration: 200 }
                                NumberAnimation { property: "scale"; from: 0.9; to: 1.0; duration: 200; easing.type: Easing.OutBack }
                            }
                        }

                        exit: Transition {
                            ParallelAnimation {
                                NumberAnimation { property: "opacity"; from: 1.0; to: 0.0; duration: 200 }
                                NumberAnimation { property: "scale"; from: 1.0; to: 0.9; duration: 200; easing.type: Easing.OutBack }
                            }
                        }

                        background: Item {}

                        contentItem: Rectangle {
                            color: Theme.surfaceDark
                            radius: Theme.radiusMedium
                            border.color: Qt.rgba(1, 1, 1, 0.1)
                            border.width: 1
                            implicitWidth: optionsCol.width + 24
                            implicitHeight: optionsCol.height + 24
                            transformOrigin: Item.TopLeft

                            Column {
                                id: optionsCol
                                anchors.centerIn: parent
                                spacing: 8

                            Row {
                                spacing: Theme.spacingSmall
                                visible: appName !== "SRAR"

                                Rectangle {
                                    width: 20
                                    height: 20
                                    radius: 4
                                    color: mergeWemChecked ? Theme.primaryAccent : Theme.cardBackground
                                    border.color: mergeWemChecked ? Theme.primaryAccent : Theme.textSecondary
                                    border.width: 1
                                    anchors.verticalCenter: parent.verticalCenter
                                    Behavior on color { ColorAnimation { duration: 100 } }

                                    Text {
                                        anchors.centerIn: parent
                                        text: "\u2713"
                                        color: Theme.textOnAccent
                                        font.pixelSize: 14
                                        font.bold: true
                                        visible: mergeWemChecked
                                    }

                                    MouseArea {
                                        anchors.fill: parent
                                        cursorShape: Qt.PointingHandCursor
                                        onClicked: {
                                            mergeWemChecked = !mergeWemChecked
                                            mergeWemToggled(mergeWemChecked)
                                        }
                                    }
                                }

                                Text {
                                    text: qsTranslate("Application", "Merge Streaming PCK")
                                    color: Theme.textPrimary
                                    font.family: Theme.fontFamily
                                    font.pixelSize: Theme.fontSizeSmall
                                    anchors.verticalCenter: parent.verticalCenter

                                    MouseArea {
                                        anchors.fill: parent
                                        cursorShape: Qt.PointingHandCursor
                                        onClicked: {
                                            mergeWemChecked = !mergeWemChecked
                                            mergeWemToggled(mergeWemChecked)
                                        }
                                    }
                                }
                            }

                            Row {
                                spacing: Theme.spacingSmall
                                visible: appName !== "SRAR"

                                Rectangle {
                                    width: 20
                                    height: 20
                                    radius: 4
                                    color: hideUselessPckChecked ? Theme.primaryAccent : Theme.cardBackground
                                    border.color: hideUselessPckChecked ? Theme.primaryAccent : Theme.textSecondary
                                    border.width: 1
                                    anchors.verticalCenter: parent.verticalCenter
                                    Behavior on color { ColorAnimation { duration: 100 } }

                                    Text {
                                        anchors.centerIn: parent
                                        text: "\u2713"
                                        color: Theme.textOnAccent
                                        font.pixelSize: 14
                                        font.bold: true
                                        visible: hideUselessPckChecked
                                    }

                                    MouseArea {
                                        anchors.fill: parent
                                        cursorShape: Qt.PointingHandCursor
                                        onClicked: {
                                            hideUselessPckChecked = !hideUselessPckChecked
                                            hideUselessPckToggled(hideUselessPckChecked)
                                        }
                                    }
                                }

                                Text {
                                    text: qsTranslate("Application", "Hide all non soundbank language PCK's")
                                    color: Theme.textPrimary
                                    font.family: Theme.fontFamily
                                    font.pixelSize: Theme.fontSizeSmall
                                    anchors.verticalCenter: parent.verticalCenter

                                    MouseArea {
                                        anchors.fill: parent
                                        cursorShape: Qt.PointingHandCursor
                                        onClicked: {
                                            hideUselessPckChecked = !hideUselessPckChecked
                                            hideUselessPckToggled(hideUselessPckChecked)
                                        }
                                    }
                                }
                            }

                            Row {
                                spacing: Theme.spacingSmall

                                Rectangle {
                                    width: 20
                                    height: 20
                                    radius: 4
                                    color: hideEmptyBnkChecked ? Theme.primaryAccent : Theme.cardBackground
                                    border.color: hideEmptyBnkChecked ? Theme.primaryAccent : Theme.textSecondary
                                    border.width: 1
                                    anchors.verticalCenter: parent.verticalCenter
                                    Behavior on color { ColorAnimation { duration: 100 } }

                                    Text {
                                        anchors.centerIn: parent
                                        text: "\u2713"
                                        color: Theme.textOnAccent
                                        font.pixelSize: 14
                                        font.bold: true
                                        visible: hideEmptyBnkChecked
                                    }

                                    MouseArea {
                                        anchors.fill: parent
                                        cursorShape: Qt.PointingHandCursor
                                        onClicked: {
                                            hideEmptyBnkChecked = !hideEmptyBnkChecked
                                            hideEmptyBnkToggled(hideEmptyBnkChecked)
                                        }
                                    }
                                }

                                Text {
                                    text: qsTranslate("Application", "Hide BNK files with no audio")
                                    color: Theme.textPrimary
                                    font.family: Theme.fontFamily
                                    font.pixelSize: Theme.fontSizeSmall
                                    anchors.verticalCenter: parent.verticalCenter

                                    MouseArea {
                                        anchors.fill: parent
                                        cursorShape: Qt.PointingHandCursor
                                        onClicked: {
                                            hideEmptyBnkChecked = !hideEmptyBnkChecked
                                            hideEmptyBnkToggled(hideEmptyBnkChecked)
                                        }
                                    }
                                }
                            }

                            Row {
                                spacing: Theme.spacingSmall

                                Rectangle {
                                    width: 20
                                    height: 20
                                    radius: 4
                                    color: normalizeAudioChecked ? Theme.primaryAccent : Theme.cardBackground
                                    border.color: normalizeAudioChecked ? Theme.primaryAccent : Theme.textSecondary
                                    border.width: 1
                                    anchors.verticalCenter: parent.verticalCenter
                                    Behavior on color { ColorAnimation { duration: 100 } }

                                    Text {
                                        anchors.centerIn: parent
                                        text: "\u2713"
                                        color: Theme.textOnAccent
                                        font.pixelSize: 14
                                        font.bold: true
                                        visible: normalizeAudioChecked
                                    }

                                    MouseArea {
                                        anchors.fill: parent
                                        cursorShape: Qt.PointingHandCursor
                                        onClicked: {
                                            normalizeAudioChecked = !normalizeAudioChecked
                                            normalizeAudioToggled(normalizeAudioChecked)
                                        }
                                    }
                                }

                                Text {
                                    text: qsTranslate("Application", "Normalize Audio on Replace")
                                    color: Theme.textPrimary
                                    font.family: Theme.fontFamily
                                    font.pixelSize: Theme.fontSizeSmall
                                    anchors.verticalCenter: parent.verticalCenter

                                    MouseArea {
                                        anchors.fill: parent
                                        cursorShape: Qt.PointingHandCursor
                                        onClicked: {
                                            normalizeAudioChecked = !normalizeAudioChecked
                                            normalizeAudioToggled(normalizeAudioChecked)
                                        }
                                    }
                                }
                            }

                            Row {
                                spacing: Theme.spacingSmall
                                visible: normalizeAudioChecked
                                leftPadding: 28

                                Text {
                                    text: qsTranslate("Application", "Target:")
                                    color: Theme.textSecondary
                                    font.family: Theme.fontFamily
                                    font.pixelSize: Theme.fontSizeSmall
                                    anchors.verticalCenter: parent.verticalCenter
                                }

                                Slider {
                                    id: lufsSlider
                                    from: -24
                                    to: -5
                                    stepSize: 1
                                    value: normalizeTargetLufs
                                    implicitWidth: 120
                                    anchors.verticalCenter: parent.verticalCenter

                                    onMoved: {
                                        normalizeTargetLufs = Math.round(value)
                                        normalizeTargetLufsSet(normalizeTargetLufs)
                                    }

                                    background: Rectangle {
                                        x: lufsSlider.leftPadding
                                        y: lufsSlider.topPadding + lufsSlider.availableHeight / 2 - height / 2
                                        width: lufsSlider.availableWidth
                                        height: 4
                                        radius: 2
                                        color: Theme.cardBackground

                                        Rectangle {
                                            width: lufsSlider.visualPosition * parent.width
                                            height: parent.height
                                            radius: 2
                                            color: Theme.primaryAccent
                                            opacity: 0.7
                                        }
                                    }

                                    handle: Rectangle {
                                        x: lufsSlider.leftPadding + lufsSlider.visualPosition * (lufsSlider.availableWidth - width)
                                        y: lufsSlider.topPadding + lufsSlider.availableHeight / 2 - height / 2
                                        width: 14
                                        height: 14
                                        radius: 7
                                        color: Theme.primaryAccent
                                    }
                                }

                                Text {
                                    text: normalizeTargetLufs === -9 ? qsTranslate("Application", "Default") : (normalizeTargetLufs + " LUFS")
                                    color: Theme.primaryAccent
                                    font.family: Theme.fontFamily
                                    font.pixelSize: Theme.fontSizeSmall
                                    anchors.verticalCenter: parent.verticalCenter
                                }
                            }

                            Rectangle {
                                width: parent.width
                                height: 1
                                color: Theme.cardBackground
                            }

                            Row {
                                spacing: 8

                                XXARButton {
                                    text: tagDbDownloading
                                        ? qsTranslate("Application", "Downloading...")
                                        : qsTranslate("Application", "Download Official Tags")
                                    buttonColor: tagDbDownloading ? Theme.disabledAccent : Theme.secondaryAccent
                                    enabled: !tagDbDownloading
                                    onClicked: {
                                        optionsPopup.close()
                                        downloadOfficialTagDbClicked()
                                    }
                                }

                                Rectangle {
                                    id: tagInfoCircle
                                    width: 20
                                    height: 20
                                    radius: 10
                                    color: tagInfoMouse.containsMouse ? Theme.primaryAccent : "#555555"
                                    anchors.verticalCenter: parent.verticalCenter
                                    z: 200
                                    Behavior on color { ColorAnimation { duration: 150 } }

                                    property bool popupHovered: tagInfoMouse.containsMouse || tagInfoPopupMouse.containsMouse

                                    Text {
                                        anchors.centerIn: parent
                                        text: "?"
                                        color: tagInfoMouse.containsMouse ? Theme.textOnAccent : "#cccccc"
                                        font.family: "Alatsi"
                                        font.pixelSize: 12
                                        font.bold: true
                                    }

                                    MouseArea {
                                        id: tagInfoMouse
                                        anchors.fill: parent
                                        hoverEnabled: true
                                        cursorShape: Qt.PointingHandCursor
                                        onEntered: {
                                            tagInfoHideTimer.stop()
                                            tagInfoPopup.visible = true
                                        }
                                        onExited: {
                                            tagInfoHideTimer.restart()
                                        }
                                    }

                                    Timer {
                                        id: tagInfoHideTimer
                                        interval: 100
                                        onTriggered: {
                                            if (!tagInfoCircle.popupHovered) {
                                                tagInfoPopup.visible = false
                                            }
                                        }
                                    }

                                    Rectangle {
                                        id: tagInfoPopup
                                        visible: false
                                        x: parent.width + 8
                                        y: -height / 2 + parent.height / 2 - 35
                                        width: 280
                                        height: tagInfoColumn.implicitHeight + 24
                                        color: "#1a1a1a"
                                        radius: 8
                                        border.color: "#555555"
                                        border.width: 1
                                        z: 1000

                                        MouseArea {
                                            id: tagInfoPopupMouse
                                            anchors.fill: parent
                                            hoverEnabled: true
                                            onEntered: {
                                                tagInfoHideTimer.stop()
                                                tagInfoPopup.visible = true
                                            }
                                            onExited: {
                                                tagInfoHideTimer.restart()
                                            }
                                        }

                                        Column {
                                            id: tagInfoColumn
                                            anchors.centerIn: parent
                                            width: parent.width - 20
                                            spacing: 12

                                            Text {
                                                id: tagInfoText
                                                width: parent.width
                                                text: qsTranslate("Application", "Tags help you identify and search\nfor audio files. The official tag\ndatabase provides community names\nand labels for game audio.")
                                                color: "#cccccc"
                                                font.family: "Alatsi"
                                                font.pixelSize: 15
                                                lineHeight: 1.4
                                                wrapMode: Text.WordWrap
                                            }

                                            Text {
                                                id: contributeLink
                                                width: parent.width
                                                text: qsTranslate("Application", "Want to contribute?")
                                                color: "#4a9eff"
                                                font.family: "Alatsi"
                                                font.pixelSize: 15
                                                font.underline: contributeMouse.containsMouse
                                                horizontalAlignment: Text.AlignHCenter

                                                MouseArea {
                                                    id: contributeMouse
                                                    anchors.fill: parent
                                                    hoverEnabled: true
                                                    cursorShape: Qt.PointingHandCursor
                                                    onEntered: {
                                                        tagInfoHideTimer.stop()
                                                        tagInfoPopup.visible = true
                                                    }
                                                    onExited: {
                                                        tagInfoHideTimer.restart()
                                                    }
                                                    onClicked: Qt.openUrlExternally("https://github.com/Entity378/XXAR/blob/main/data/CONTRIBUTING_TAGS.md")
                                                }
                                            }
                                        }
                                    }
                                }
                            }

                            XXARButton {
                                text: qsTranslate("Application", "Open Tag Database Folder")
                                buttonColor: Theme.disabledAccent
                                z: 10
                                onClicked: {
                                    optionsPopup.close()
                                    openTagDbFolderClicked()
                                }
                            }
                        }
                        }
                    }
                }

                Rectangle {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    color: Theme.surfaceDark
                    radius: Theme.radiusMedium

                    Row {
                        id: treeHeader
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.top: parent.top
                        anchors.margins: Theme.spacingSmall
                        height: 28
                        spacing: 0

                        property real colAvail: parent.width - 40

                        Text {
                            width: 40
                            text: "#"
                            color: Theme.textSecondary
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSizeSmall
                            font.bold: true
                            verticalAlignment: Text.AlignVCenter
                            horizontalAlignment: Text.AlignHCenter
                        }
                        Text {
                            width: treeHeader.colAvail * 0.42
                            text: qsTranslate("Application", "File")
                            color: Theme.textSecondary
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSizeSmall
                            font.bold: true
                            verticalAlignment: Text.AlignVCenter
                        }
                        Text {
                            width: treeHeader.colAvail * 0.13
                            text: qsTranslate("Application", "ID")
                            color: Theme.textSecondary
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSizeSmall
                            font.bold: true
                            verticalAlignment: Text.AlignVCenter
                        }
                        Rectangle {
                            width: treeHeader.colAvail * 0.15
                            height: parent.height
                            color: sizeHeaderMouse.containsMouse ? Qt.rgba(1, 1, 1, 0.05) : "transparent"

                            Text {
                                anchors.fill: parent
                                text: qsTranslate("Application", "Size ") + (sortBySizeAsc ? "\u25B2" : "\u25BC")
                                color: Theme.textSecondary
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSizeSmall
                                font.bold: true
                                verticalAlignment: Text.AlignVCenter
                            }

                            MouseArea {
                                id: sizeHeaderMouse
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: {
                                    sortBySizeAsc = !sortBySizeAsc
                                    sortTreeBySize()
                                }
                            }
                        }
                        Rectangle {
                            width: treeHeader.colAvail * 0.13
                            height: parent.height
                            color: durationHeaderMouse.containsMouse ? Qt.rgba(1, 1, 1, 0.05) : "transparent"

                            Text {
                                anchors.fill: parent
                                text: qsTranslate("Application", "Duration ") + (sortByDurationAsc ? "\u25B2" : "\u25BC")
                                color: Theme.textSecondary
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSizeSmall
                                font.bold: true
                                verticalAlignment: Text.AlignVCenter
                            }

                            MouseArea {
                                id: durationHeaderMouse
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: {
                                    sortByDurationAsc = !sortByDurationAsc
                                    sortTreeByDuration()
                                }
                            }
                        }
                        Text {
                            width: treeHeader.colAvail * 0.17
                            text: qsTranslate("Application", "Type")
                            color: Theme.textSecondary
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSizeSmall
                            font.bold: true
                            verticalAlignment: Text.AlignVCenter
                        }
                    }

                    Rectangle {
                        id: headerSep
                        anchors.top: treeHeader.bottom
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.leftMargin: Theme.spacingSmall
                        anchors.rightMargin: Theme.spacingSmall
                        height: 1
                        color: Theme.textSecondary
                        opacity: 0.3
                    }

                    ListView {
                        id: treeList
                        objectName: "tutorialTreeList"
                        anchors.top: headerSep.bottom
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.bottom: parent.bottom
                        anchors.margins: Theme.spacingSmall
                        anchors.topMargin: 4
                        clip: true
                        model: treeModel
                        boundsBehavior: Flickable.DragOverBounds
                        flickDeceleration: 5000
                        maximumFlickVelocity: 2500

                        ScrollBar.vertical: ScrollBar {
                            policy: ScrollBar.AsNeeded
                        }

                        Text {
                            anchors.centerIn: parent
                            text: qsTranslate("Application", "No audio files loaded.\nSelect a game directory to browse.")
                            color: Theme.textSecondary
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSizeNormal
                            horizontalAlignment: Text.AlignHCenter
                            visible: treeModel.count === 0
                        }

                        delegate: Rectangle {
                            id: treeItem
                            width: treeList.width
                            height: 30
                            property bool isHighlighted: highlightItemId !== "" && model.itemId === highlightItemId && model.pckPath === highlightPckPath
                            color: isHighlighted ? Qt.rgba(Theme.primaryAccent.r, Theme.primaryAccent.g, Theme.primaryAccent.b, 0.25)
                                 : itemMouse.containsMouse ? Qt.lighter(Theme.surfaceDark, 1.8) : "transparent"
                            radius: 4
                            Behavior on color { ColorAnimation { duration: 80 } }

                            Rectangle {
                                anchors.fill: parent
                                radius: parent.radius
                                color: (index % 2 === 1) ? Qt.rgba(1, 1, 1, 0.04) : Qt.rgba(1, 1, 1, 0.015)
                                visible: !isHighlighted && !itemMouse.containsMouse
                            }

                            property bool expanded: model.expanded || false
                            property int depth: model.depth || 0

                            Row {
                                anchors.fill: parent
                                anchors.leftMargin: Theme.spacingSmall
                                spacing: 0

                                Text {
                                    width: 40
                                    height: parent.height
                                    text: (index + 1)
                                    color: Theme.textSecondary
                                    font.family: Theme.fontFamily
                                    font.pixelSize: Theme.fontSizeSmall
                                    verticalAlignment: Text.AlignVCenter
                                    horizontalAlignment: Text.AlignHCenter
                                    opacity: 0.6
                                }

                                Item {
                                    width: parent.width - 40
                                    height: parent.height

                                    Row {
                                        anchors.fill: parent
                                        anchors.leftMargin: depth * 20
                                        spacing: 0

                                        Text {
                                            width: 20
                                            height: parent.height
                                            text: model.hasChildren ? (treeItem.expanded ? "\u25BC" : "\u25B6") : ""
                                            color: Theme.textSecondary
                                            font.pixelSize: 10
                                            verticalAlignment: Text.AlignVCenter
                                            horizontalAlignment: Text.AlignHCenter
                                        }

                                        Text {
                                            width: (treeList.width - 40 - 20 - depth * 20) * 0.42
                                            height: parent.height
                                            text: {
                                                if (model.itemType && model.itemType.indexOf("WEM") !== -1 && model.tags && model.tags !== "") {
                                                    return model.tags
                                                }
                                                return model.fileName || ""
                                            }
                                            color: model.isModified ? Theme.primaryAccent : Theme.textPrimary
                                            font.family: Theme.fontFamily
                                            font.pixelSize: Theme.fontSizeSmall
                                            verticalAlignment: Text.AlignVCenter
                                            elide: Text.ElideRight
                                        }

                                        Text {
                                            width: (treeList.width - 40 - 20 - depth * 20) * 0.13
                                            height: parent.height
                                            text: model.itemId || ""
                                            color: Theme.textPrimary
                                            font.family: Theme.fontFamily
                                            font.pixelSize: Theme.fontSizeSmall
                                            verticalAlignment: Text.AlignVCenter
                                            elide: Text.ElideRight
                                        }

                                        Text {
                                            width: (treeList.width - 40 - 20 - depth * 20) * 0.15
                                            height: parent.height
                                            text: model.fileSize || ""
                                            color: Theme.textPrimary
                                            font.family: Theme.fontFamily
                                            font.pixelSize: Theme.fontSizeSmall
                                            verticalAlignment: Text.AlignVCenter
                                        }

                                        Text {
                                            width: (treeList.width - 40 - 20 - depth * 20) * 0.13
                                            height: parent.height
                                            text: model.duration || ""
                                            color: Theme.textPrimary
                                            font.family: Theme.fontFamily
                                            font.pixelSize: Theme.fontSizeSmall
                                            verticalAlignment: Text.AlignVCenter
                                        }

                                        Text {
                                            width: (treeList.width - 40 - 20 - depth * 20) * 0.17
                                            height: parent.height
                                            text: model.itemType || ""
                                            color: Theme.textSecondary
                                            font.family: Theme.fontFamily
                                            font.pixelSize: Theme.fontSizeSmall
                                            verticalAlignment: Text.AlignVCenter
                                        }
                                    }
                                }
                            }

                            MouseArea {
                                id: itemMouse
                                anchors.fill: parent
                                hoverEnabled: true
                                acceptedButtons: Qt.LeftButton | Qt.RightButton
                                cursorShape: Qt.PointingHandCursor

                                onDoubleClicked: {
                                    treeItemDoubleClicked(model.itemId, model.itemType, model.pckPath || "")
                                }
                                onClicked: {
                                    if (mouse.button === Qt.RightButton) {
                                        var isWem = model.itemType.indexOf("WEM") !== -1
                                        if (isWem) {
                                            contextMenu.contextItemId = model.itemId
                                            contextMenu.contextItemType = model.itemType
                                            contextMenu.contextPckPath = model.pckPath || ""
                                            contextMenu.contextParentBnk = model.parentBnk || ""

                                            var pos = itemMouse.mapToItem(audioBrowser, mouse.x, mouse.y)
                                            contextMenuX = pos.x
                                            contextMenuY = pos.y
                                            contextMenu.visible = true
                                        }
                                    } else if (mouse.button === Qt.LeftButton && (model.hasChildren || false)) {

                                        treeItem.expanded = !treeItem.expanded
                                        treeModel.setProperty(index, "expanded", treeItem.expanded)
                                        if (treeItem.expanded) {
                                            if (model.itemType === "PCK") {
                                                audioBrowserBackend.expandPckItem(model.pckPath)
                                            } else {
                                                treeItemExpanded(model.itemId, model.itemType)
                                            }
                                        } else {

                                            var parentDepth = model.depth || 0
                                            var removeStart = index + 1
                                            var removeCount = 0
                                            while (removeStart + removeCount < treeModel.count &&
                                                   (treeModel.get(removeStart + removeCount).depth || 0) > parentDepth) {
                                                removeCount++
                                            }
                                            if (removeCount > 0) {
                                                treeModel.remove(removeStart, removeCount)
                                            }

                                            var collapseId = model.itemType === "PCK" ? model.pckPath : model.itemId
                                            audioBrowserBackend.onItemCollapsed(collapseId, model.itemType)
                                        }
                                    }
                                }
                            }
                        }
                    }

                    QtObject {
                        id: contextMenu
                        property string contextItemId: ""
                        property string contextItemType: ""
                        property string contextPckPath: ""
                        property string contextParentBnk: ""
                        property bool visible: false
                        function close() { visible = false }
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: Theme.spacingSmall

                    XXARButton {
                        objectName: "tutorialImportModBtn"
                        text: qsTranslate("Application", "Import %1 for Editing").replace("%1", modFileExt)
                        buttonColor: Theme.primaryAccent
                        onClicked: importModForEditingClicked()
                    }
                    XXARButton {
                        objectName: "tutorialShowChangesBtn"
                        text: changesCount > 0 ? qsTranslate("Application", "Show Changes (%1)").arg(changesCount) : qsTranslate("Application", "Show Changes")
                        onClicked: showChangesClicked()
                    }
                    XXARButton {
                        objectName: "tutorialExportBtn"
                        text: qsTranslate("Application", "Export as Mod Package")
                        onClicked: exportModClicked()
                    }
                    XXARButton {
                        objectName: "tutorialResetBtn"
                        text: qsTranslate("Application", "Reset All Changes")
                        buttonColor: Theme.disabledAccent
                        textColor: Theme.textPrimary
                        onClicked: resetAllClicked()
                    }
                    Item { Layout.fillWidth: true }
                }

                Rectangle {
                    objectName: "tutorialAudioPlayer"
                    Layout.fillWidth: true
                    height: 100
                    color: Theme.surfaceDark
                    radius: Theme.radiusMedium

                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: Theme.spacingSmall
                        spacing: 6

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: Theme.spacingSmall

                            Text {
                                text: nowPlayingText
                                color: Theme.textSecondary
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSizeSmall
                                font.italic: true
                                elide: Text.ElideRight
                                Layout.fillWidth: true
                            }

                            XXARButton {
                                text: "\u25B6 Play"
                                enabled: playbackEnabled
                                buttonColor: enabled ? Theme.primaryAccent : Theme.disabledAccent
                                onClicked: playClicked()
                            }
                            XXARButton {
                                text: "\u23F8 Pause"
                                enabled: isPlaying
                                buttonColor: enabled ? Theme.primaryAccent : Theme.disabledAccent
                                onClicked: pauseClicked()
                            }
                            XXARButton {
                                text: "\u23F9 Stop"
                                enabled: isPlaying || isPaused
                                buttonColor: enabled ? Theme.primaryAccent : Theme.disabledAccent
                                onClicked: stopClicked()
                            }
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: Theme.spacingSmall

                            Slider {
                                id: progressSlider
                                Layout.fillWidth: true
                                from: 0
                                to: 1.0
                                value: playbackProgress
                                onMoved: seekRequested(value)

                                background: Rectangle {
                                    x: progressSlider.leftPadding
                                    y: progressSlider.bottomPadding + progressSlider.availableHeight / 2 - height / 2
                                    width: progressSlider.availableWidth
                                    height: 4
                                    radius: 2
                                    color: Theme.cardBackground

                                    Rectangle {
                                        width: progressSlider.visualPosition * parent.width
                                        height: parent.height
                                        radius: 2
                                        color: Theme.primaryAccent
                                    }
                                }
                                handle: Rectangle {
                                    x: progressSlider.leftPadding + progressSlider.visualPosition * (progressSlider.availableWidth - width)
                                    y: progressSlider.bottomPadding + progressSlider.availableHeight / 2 - height / 2
                                    width: 14
                                    height: 14
                                    radius: 7
                                    color: progressSlider.pressed ? Qt.darker(Theme.primaryAccent, 1.1) : Theme.primaryAccent
                                }
                            }

                            Text {
                                text: timeText
                                color: Theme.textPrimary
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSizeSmall
                                Layout.preferredWidth: 100
                                horizontalAlignment: Text.AlignRight
                            }
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: Theme.spacingSmall

                            Text {
                                text: qsTranslate("Application", "Volume:")
                                color: Theme.textSecondary
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSizeSmall
                            }

                            Slider {
                                id: volumeSlider
                                Layout.preferredWidth: 150
                                from: 0
                                to: 100
                                value: volume
                                onMoved: {
                                    volume = value
                                    volumeAdjusted(value)
                                }

                                background: Rectangle {
                                    x: volumeSlider.leftPadding
                                    y: volumeSlider.bottomPadding + volumeSlider.availableHeight / 2 - height / 2
                                    width: volumeSlider.availableWidth
                                    height: 4
                                    radius: 2
                                    color: Theme.cardBackground

                                    Rectangle {
                                        width: volumeSlider.visualPosition * parent.width
                                        height: parent.height
                                        radius: 2
                                        color: Theme.primaryAccent
                                    }
                                }
                                handle: Rectangle {
                                    x: volumeSlider.leftPadding + volumeSlider.visualPosition * (volumeSlider.availableWidth - width)
                                    y: volumeSlider.bottomPadding + volumeSlider.availableHeight / 2 - height / 2
                                    width: 12
                                    height: 12
                                    radius: 6
                                    color: volumeSlider.pressed ? Qt.darker(Theme.primaryAccent, 1.1) : Theme.primaryAccent
                                }
                            }

                            Text {
                                text: Math.round(volumeSlider.value) + "%"
                                color: Theme.textPrimary
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSizeSmall
                                Layout.preferredWidth: 40
                            }

                            Item { Layout.fillWidth: true }
                        }
                    }
                }

                Text {
                    text: statusText
                    color: Theme.textSecondary
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeSmall
                    Layout.fillWidth: true
                    elide: Text.ElideRight
                }
            }
        }
    }

    function setGameDirectory(path) {
        gameDirectory = path
    }

    function setLanguageTabs(tabs) {
        var previousIndex = langTabs.currentIndex
        var previousLabel = ""
        if (previousIndex >= 0 && previousIndex < languageTabsModel.count) {
            previousLabel = languageTabsModel.get(previousIndex).label
        }

        languageTabsModel.clear()
        for (var i = 0; i < tabs.length; i++) {
            languageTabsModel.append({ "label": tabs[i] })
        }

        var restoredIndex = 0
        if (previousLabel !== "") {
            for (var j = 0; j < tabs.length; j++) {
                if (tabs[j] === previousLabel) {
                    restoredIndex = j
                    break
                }
            }
        }
        langTabs.currentIndex = restoredIndex
    }

    function clearTree() {
        treeModel.clear()
    }

    function addTreeItem(item) {
        treeModel.append({
            "fileName": item.fileName || "",
            "itemId": item.itemId || "",
            "fileSize": item.fileSize || "",
            "duration": item.duration || "",
            "itemType": item.itemType || "",
            "tags": item.tags || "",
            "hasChildren": item.hasChildren || false,
            "expanded": false,
            "depth": item.depth || 0,
            "pckPath": item.pckPath || "",
            "isModified": item.isModified || false,
            "parentBnk": item.parentBnk || "",
            "parentPck": item.parentPck || ""
        })
    }

    function addTreeItems(items) {
        if (items.length === 0) return

        var firstItem = items[0]
        var insertIdx = -1

        if (firstItem.parentBnk) {

            for (var k = 0; k < treeModel.count; k++) {
                if (treeModel.get(k).itemId === firstItem.parentBnk &&
                    treeModel.get(k).pckPath === firstItem.pckPath) {
                    insertIdx = k + 1

                    while (insertIdx < treeModel.count &&
                           treeModel.get(insertIdx).depth > treeModel.get(k).depth) {
                        insertIdx++
                    }
                    break
                }
            }
        } else if (firstItem.parentPck) {

            for (var j = 0; j < treeModel.count; j++) {
                if (treeModel.get(j).pckPath === firstItem.parentPck &&
                    treeModel.get(j).itemType === "PCK") {
                    insertIdx = j + 1

                    while (insertIdx < treeModel.count &&
                           treeModel.get(insertIdx).depth > 0) {
                        insertIdx++
                    }
                    break
                }
            }
        }

        for (var i = 0; i < items.length; i++) {
            var row = {
                "fileName": items[i].fileName || "",
                "itemId": items[i].itemId || "",
                "fileSize": items[i].fileSize || "",
                "duration": items[i].duration || "",
                "itemType": items[i].itemType || "",
                "tags": items[i].tags || "",
                "hasChildren": items[i].hasChildren || false,
                "expanded": false,
                "depth": items[i].depth || 0,
                "pckPath": items[i].pckPath || "",
                "isModified": items[i].isModified || false,
                "parentBnk": items[i].parentBnk || "",
                "parentPck": items[i].parentPck || ""
            }
            if (insertIdx >= 0) {
                treeModel.insert(insertIdx + i, row)
            } else {
                treeModel.append(row)
            }
        }
    }

    function setStatus(msg) {
        statusText = msg
    }

    function setNowPlaying(text) {
        nowPlayingText = text
    }

    function setPlaybackState(playing, paused, enabled) {
        isPlaying = playing
        isPaused = paused
        playbackEnabled = enabled
    }

    function setProgress(position, timeStr) {
        playbackProgress = position
        timeText = timeStr
    }

    function scrollToItem(fileId, pckPath, bnkId) {
        console.log("[QML] scrollToItem called: fileId=", fileId, "pckPath=", pckPath, "bnkId=", bnkId)
        console.log("[QML] treeModel.count=", treeModel.count)

        for (var i = 0; i < treeModel.count; i++) {
            var item = treeModel.get(i)
            if (item.itemId === fileId && item.pckPath === pckPath) {
                if (bnkId && item.parentBnk && item.parentBnk !== bnkId)
                    continue
                console.log("[QML] Found item at index", i, "scrolling to it")
                treeList.positionViewAtIndex(i, ListView.Center)
                highlightItemId = fileId
                highlightPckPath = pckPath
                highlightClearTimer.restart()
                return
            }
        }
        console.log("[QML] Item not found in tree model")
    }

    Timer {
        id: highlightClearTimer
        interval: 3000
        onTriggered: {
            highlightItemId = ""
            highlightPckPath = ""
        }
    }

    function showTagDialog(soundInfo) {

        tagNameInput.text = soundInfo.name || ""
        tagTagsInput.text = soundInfo.tags || ""
        tagNotesInput.text = soundInfo.notes || ""
        tagHashLabel.text = qsTranslate("Application", "Hash: ") + (soundInfo.hash || qsTranslate("Application", "Unknown"))

        tagDialog.currentItemId = soundInfo.itemId || ""
        tagDialog.currentItemType = soundInfo.itemType || ""
        tagDialog.currentPckPath = soundInfo.pckPath || ""

        tagOverlay.visible = true
        tagOverlay.closing = false
        tagNameInput.forceActiveFocus()
    }

    function showMetadataDialog(metadata) {

        if (metadata && Object.keys(metadata).length > 0) {
            metadataNameInput.text = metadata.name || ""
            metadataAuthorInput.text = metadata.author || ""
            metadataVersionInput.text = metadata.version || "1.0.0"
            metadataDescriptionInput.text = metadata.description || ""
            metadataThumbnailPathInput.text = metadata.thumbnail || ""
        } else {

            metadataNameInput.text = ""
            metadataAuthorInput.text = ""
            metadataVersionInput.text = "1.0.0"
            metadataDescriptionInput.text = ""
            metadataThumbnailPathInput.text = ""
        }

        metadataOverlay.visible = true
        metadataOverlay.closing = false
        metadataNameInput.forceActiveFocus()
    }

    function setThumbnailPath(path) {
        metadataThumbnailPathInput.text = path
    }

    function showChanges(changes) {
        changesModel.clear()
        for (var i = 0; i < changes.length; i++) {
            changesModel.append({
                "fileId": changes[i].fileId || "",
                "trackerKey": changes[i].trackerKey || changes[i].fileId || "",
                "pckFile": changes[i].pckFile || "",
                "pckPath": changes[i].pckPath || "",
                "fileType": changes[i].fileType || "",
                "itemType": changes[i].itemType || "",
                "bnkId": changes[i].bnkId || "",
                "dateModified": changes[i].dateModified || "",
                "taggedName": changes[i].taggedName || "",
                "sourceFile": changes[i].sourceFile || "",
                "wemPath": changes[i].wemPath || "",
                "loopPointSupported": changes[i].loopPointSupported || false,
                "loopPointEditable": changes[i].loopPointEditable || false,
                "loopPointMode": changes[i].loopPointMode || "auto",
                "loopPointManualMs": changes[i].loopPointManualMs || 0,
                "loopPointSuggestedMs": changes[i].loopPointSuggestedMs || 0,
                "volumeEditable": changes[i].volumeEditable || false,
                "volumeEnabled": changes[i].volumeEnabled !== false,
                "volumeDb": changes[i].volumeDb || 0.0
            })
        }
        changesOverlay.loopColumnVisible = changes.length > 0 && (changes[0].loopPointSupported || false)
        changesOverlay.volumeColumnVisible = changes.length > 0 && (changes[0].volumeEditable || false)
        changesTitle.text = qsTranslate("Application", "Current Changes") + " (" + changes.length + " " + (changes.length !== 1 ? qsTranslate("Application", "replacements") : qsTranslate("Application", "replacement")) + ")"
        changesOverlay.visible = true
        changesOverlay.closing = false
    }

    function closeChangesDialog() {
        changesOverlay.closing = true
        changesHideTimer.start()
    }

    function showSearchResults(query, results) {
        searchResultsModel.clear()
        for (var i = 0; i < results.length; i++) {
            searchResultsModel.append({
                "name": results[i].name || "",
                "fileId": results[i].fileId || "",
                "tags": results[i].tags || "",
                "itemType": results[i].type || "",
                "pckPath": results[i].pckPath || "",
                "bnkId": results[i].bnkId || ""
            })
        }
        searchResultsTitle.text = qsTranslate("Application", "Search Results for '%1' (%2 found)").arg(query).arg(results.length)
        searchResultsOverlay.visible = true
        searchResultsOverlay.closing = false
    }

    function onMatchStarted() {
        matchInProgress = true
        matchCurrent = 0
        matchTotal = 0
    }

    function onMatchFinished() {
        matchInProgress = false
    }

    function onMatchProgress(current, total) {
        matchCurrent = current
        matchTotal = total
    }

    function showMatchResults(results) {
        matchResultsModel.clear()
        for (var i = 0; i < results.length; i++) {
            var item = results[i]
            var scoreVal = parseFloat(item.score) || 0
            matchResultsModel.append({
                "score": scoreVal,
                "name": String(item.name || ""),
                "fileId": String(item.fileId || ""),
                "pckName": String(item.pckName || ""),
                "pckPath": String(item.pckPath || ""),
                "itemType": String(item.itemType || ""),
                "bnkId": String(item.bnkId || ""),
                "langId": String(item.langId || "0")
            })
        }
        matchResultsOverlay.visible = true
        matchResultsOverlay.closing = false
    }

    function updateTreeItemTag(itemId, itemType, pckPath, tagText) {

        for (var i = 0; i < treeModel.count; i++) {
            var item = treeModel.get(i)
            if (item.itemId === itemId && item.itemType === itemType && item.pckPath === pckPath) {
                treeModel.setProperty(i, "tags", tagText)
                break
            }
        }
    }

    function onTagDbDownloadStarted() {
        tagDbDownloading = true
    }

    function onTagDbDownloadReady(entryCount) {
        tagDbDownloading = false
        tagDbEntryCount = entryCount
        tagDbOverlay.visible = true
        tagDbOverlay.closing = false
    }

    function onTagDbDownloadError(message) {
        tagDbDownloading = false
    }

    function onTagDbImportComplete(count) {
    }

    function onNewTagDbAvailable(entryCount) {
        tagDbNewCount = entryCount
        tagDbNotifyVisible = true
        tagDbNotifyOverlay.closing = false
        notifyDontShowBox.checked = false
    }

    function sortTreeBySize() {

        function parseSizeToBytes(sizeStr) {
            if (!sizeStr || sizeStr === "") return 0
            var parts = sizeStr.trim().split(' ')
            if (parts.length !== 2) return 0
            var num = parseFloat(parts[0])
            var unit = parts[1].toUpperCase()

            switch(unit) {
                case "B": return num
                case "KB": return num * 1024
                case "MB": return num * 1024 * 1024
                case "GB": return num * 1024 * 1024 * 1024
                default: return 0
            }
        }

        var items = []
        for (var i = 0; i < treeModel.count; i++) {
            var item = treeModel.get(i)
            items.push({
                fileName: item.fileName,
                itemId: item.itemId,
                fileSize: item.fileSize,
                duration: item.duration,
                fileSizeBytes: parseSizeToBytes(item.fileSize),
                itemType: item.itemType,
                tags: item.tags,
                hasChildren: item.hasChildren,
                expanded: item.expanded,
                depth: item.depth,
                pckPath: item.pckPath,
                isModified: item.isModified,
                parentPck: item.parentPck || "",
                parentBnk: item.parentBnk || ""
            })
        }

        function sortAtDepth(depth) {
            var depthItems = []
            var depthIndices = []

            for (var i = 0; i < items.length; i++) {
                if (items[i].depth === depth) {
                    depthItems.push(items[i])
                    depthIndices.push(i)
                }
            }

            depthItems.sort(function(a, b) {
                if (sortBySizeAsc) {
                    return a.fileSizeBytes - b.fileSizeBytes
                } else {
                    return b.fileSizeBytes - a.fileSizeBytes
                }
            })

            for (var j = 0; j < depthItems.length; j++) {
                items[depthIndices[j]] = depthItems[j]
            }
        }

        var maxDepth = 0
        for (var k = 0; k < items.length; k++) {
            if (items[k].depth > maxDepth) maxDepth = items[k].depth
        }
        for (var d = 0; d <= maxDepth; d++) {
            sortAtDepth(d)
        }

        treeModel.clear()
        for (var m = 0; m < items.length; m++) {
            treeModel.append(items[m])
        }
    }

    function sortTreeByDuration() {

        function parseDurationToSeconds(durStr) {
            if (!durStr || durStr === "") return -1
            var clean = durStr.replace("~", "")
            var parts = clean.split(":")
            if (parts.length !== 2) return -1
            var mins = parseInt(parts[0])
            var secs = parseInt(parts[1])
            if (isNaN(mins) || isNaN(secs)) return -1
            return mins * 60 + secs
        }

        var items = []
        for (var i = 0; i < treeModel.count; i++) {
            var item = treeModel.get(i)
            items.push({
                fileName: item.fileName,
                itemId: item.itemId,
                fileSize: item.fileSize,
                duration: item.duration,
                durationSeconds: parseDurationToSeconds(item.duration),
                itemType: item.itemType,
                tags: item.tags,
                hasChildren: item.hasChildren,
                expanded: item.expanded,
                depth: item.depth,
                pckPath: item.pckPath,
                isModified: item.isModified,
                parentPck: item.parentPck || "",
                parentBnk: item.parentBnk || ""
            })
        }

        function sortAtDepth(depth) {
            var depthItems = []
            var depthIndices = []

            for (var i = 0; i < items.length; i++) {
                if (items[i].depth === depth) {
                    depthItems.push(items[i])
                    depthIndices.push(i)
                }
            }

            depthItems.sort(function(a, b) {
                if (sortByDurationAsc) {
                    return a.durationSeconds - b.durationSeconds
                } else {
                    return b.durationSeconds - a.durationSeconds
                }
            })

            for (var j = 0; j < depthItems.length; j++) {
                items[depthIndices[j]] = depthItems[j]
            }
        }

        var maxDepth = 0
        for (var k = 0; k < items.length; k++) {
            if (items[k].depth > maxDepth) maxDepth = items[k].depth
        }
        for (var d = 0; d <= maxDepth; d++) {
            sortAtDepth(d)
        }

        treeModel.clear()
        for (var m = 0; m < items.length; m++) {
            treeModel.append(items[m])
        }
    }

    Item {
        id: contextMenuPopup
        anchors.fill: parent
        visible: contextMenu.visible
        z: 5000

        MouseArea {
            anchors.fill: parent
            onClicked: contextMenu.close()
        }

        Rectangle {
            id: menuPanel
            x: contextMenuX
            y: contextMenuY
            width: 260
            implicitHeight: menuColumn.implicitHeight + 8
            color: Theme.surfaceDark
            border.color: Qt.rgba(1, 1, 1, 0.1)
            border.width: 1
            radius: Theme.radiusMedium

            layer.enabled: true
            layer.effect: MultiEffect {
                shadowEnabled: true
                shadowHorizontalOffset: 0
                shadowVerticalOffset: 4
                shadowBlur: 0.50
                shadowColor: "#80000000"
            }

            MouseArea { anchors.fill: parent }

            Column {
                id: menuColumn
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.margins: 4
                spacing: 2

                Rectangle {
                    width: parent.width
                    height: Theme.buttonHeightLarge
                    color: replaceArea.containsMouse ? (replaceArea.pressed ? Theme.primaryAccent : Qt.lighter(Theme.surfaceDark, 1.3)) : Theme.surfaceDark
                    radius: Theme.radiusSmall
                    Behavior on color { ColorAnimation { duration: 100 } }

                    Text {
                        anchors.fill: parent
                        leftPadding: 14
                        text: qsTranslate("Application", "Replace with Custom Audio...")
                        color: replaceArea.containsMouse && replaceArea.pressed ? Theme.textOnAccent : Theme.textPrimary
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeSmall
                        verticalAlignment: Text.AlignVCenter
                    }

                    MouseArea {
                        id: replaceArea
                        objectName: "tutorialReplaceArea"
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: {
                            contextMenu.close()
                            audioBrowserBackend.replaceWithCustomAudio(
                                contextMenu.contextItemId, contextMenu.contextItemType, contextMenu.contextPckPath, normalizeAudioChecked, contextMenu.contextParentBnk)
                        }
                    }
                }

                Rectangle {
                    width: parent.width
                    height: Theme.buttonHeightLarge
                    color: tagArea.containsMouse ? (tagArea.pressed ? Theme.primaryAccent : Qt.lighter(Theme.surfaceDark, 1.3)) : Theme.surfaceDark
                    radius: Theme.radiusSmall
                    Behavior on color { ColorAnimation { duration: 100 } }

                    Text {
                        anchors.fill: parent
                        leftPadding: 14
                        text: qsTranslate("Application", "Tag This Sound...")
                        color: tagArea.containsMouse && tagArea.pressed ? Theme.textOnAccent : Theme.textPrimary
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeSmall
                        verticalAlignment: Text.AlignVCenter
                    }

                    MouseArea {
                        id: tagArea
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: {
                            contextMenu.close()
                            tagSoundRequested(
                                contextMenu.contextItemId, contextMenu.contextItemType, contextMenu.contextPckPath)
                        }
                    }
                }

                Rectangle {
                    width: parent.width
                    height: Theme.buttonHeightLarge
                    color: muteArea.containsMouse ? (muteArea.pressed ? Theme.primaryAccent : Qt.lighter(Theme.surfaceDark, 1.3)) : Theme.surfaceDark
                    radius: Theme.radiusSmall
                    Behavior on color { ColorAnimation { duration: 100 } }

                    Text {
                        anchors.fill: parent
                        leftPadding: 14
                        text: qsTranslate("Application", "Mute Audio")
                        color: muteArea.containsMouse && muteArea.pressed ? Theme.textOnAccent : Theme.textPrimary
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeSmall
                        verticalAlignment: Text.AlignVCenter
                    }

                    MouseArea {
                        id: muteArea
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: {
                            contextMenu.close()
                            audioBrowserBackend.muteAudio(
                                contextMenu.contextItemId, contextMenu.contextItemType, contextMenu.contextPckPath, contextMenu.contextParentBnk)
                        }
                    }
                }

                Item {
                    width: parent.width
                    height: 1
                }

                Rectangle {
                    width: parent.width
                    height: Theme.buttonHeightLarge
                    color: playArea.containsMouse ? (playArea.pressed ? Theme.primaryAccent : Qt.lighter(Theme.surfaceDark, 1.3)) : Theme.surfaceDark
                    radius: Theme.radiusSmall
                    Behavior on color { ColorAnimation { duration: 100 } }

                    Text {
                        anchors.fill: parent
                        leftPadding: 14
                        text: qsTranslate("Application", "Play")
                        color: playArea.containsMouse && playArea.pressed ? Theme.textOnAccent : Theme.textPrimary
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeSmall
                        verticalAlignment: Text.AlignVCenter
                    }

                    MouseArea {
                        id: playArea
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: {
                            contextMenu.close()
                            treeItemDoubleClicked(
                                contextMenu.contextItemId, contextMenu.contextItemType, contextMenu.contextPckPath)
                        }
                    }
                }

                Rectangle {
                    width: parent.width
                    height: Theme.buttonHeightLarge
                    color: exportArea.containsMouse ? (exportArea.pressed ? Theme.primaryAccent : Qt.lighter(Theme.surfaceDark, 1.3)) : Theme.surfaceDark
                    radius: Theme.radiusSmall
                    Behavior on color { ColorAnimation { duration: 100 } }

                    Text {
                        anchors.fill: parent
                        leftPadding: 14
                        text: qsTranslate("Application", "Export as WAV...")
                        color: exportArea.containsMouse && exportArea.pressed ? Theme.textOnAccent : Theme.textPrimary
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeSmall
                        verticalAlignment: Text.AlignVCenter
                    }

                    MouseArea {
                        id: exportArea
                        objectName: "tutorialExportArea"
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: {
                            contextMenu.close()
                            audioBrowserBackend.exportAsWav(
                                contextMenu.contextItemId, contextMenu.contextItemType, contextMenu.contextPckPath, contextMenu.contextParentBnk)
                        }
                    }
                }

                Item {
                    width: parent.width
                    height: 1
                }

                Rectangle {
                    width: parent.width
                    height: Theme.buttonHeightLarge
                    color: copyIdArea.containsMouse ? (copyIdArea.pressed ? Theme.primaryAccent : Qt.lighter(Theme.surfaceDark, 1.3)) : Theme.surfaceDark
                    radius: Theme.radiusSmall
                    Behavior on color { ColorAnimation { duration: 100 } }

                    Text {
                        anchors.fill: parent
                        leftPadding: 14
                        text: qsTranslate("Application", "Copy ID")
                        color: copyIdArea.containsMouse && copyIdArea.pressed ? Theme.textOnAccent : Theme.textPrimary
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeSmall
                        verticalAlignment: Text.AlignVCenter
                    }

                    MouseArea {
                        id: copyIdArea
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: {
                            contextMenu.close()
                            clipboardHelper.setText(contextMenu.contextItemId)
                        }
                    }
                }
            }
        }
    }

    Item {
        id: searchResultsOverlay
        visible: false
        anchors.fill: parent
        z: 2000
        property bool closing: false

        Timer {
            id: searchHideTimer
            interval: 200
            onTriggered: {
                searchResultsOverlay.visible = false
                searchResultsOverlay.closing = false
            }
        }

        ListModel { id: searchResultsModel }

        Rectangle {
            anchors.fill: parent
            color: "#80000000"
            opacity: (!searchResultsOverlay.closing && searchResultsOverlay.visible) ? 1.0 : 0.0
            Behavior on opacity { NumberAnimation { duration: 200 } }

            MouseArea {
                anchors.fill: parent
                onClicked: {
                    searchResultsOverlay.closing = true
                    searchHideTimer.start()
                }
            }
        }

        Rectangle {
            id: searchDialog
            width: Math.min(650, parent.width - 60)
            height: Math.min(500, parent.height - 80)
            anchors.centerIn: parent
            color: Theme.surfaceColor
            radius: Theme.radiusLarge
            border.color: Theme.cardBackground
            border.width: 1
            scale: (!searchResultsOverlay.closing && searchResultsOverlay.visible) ? 1.0 : 0.9
            opacity: (!searchResultsOverlay.closing && searchResultsOverlay.visible) ? 1.0 : 0.0
            Behavior on scale { NumberAnimation { duration: 200; easing.type: Easing.OutBack } }
            Behavior on opacity { NumberAnimation { duration: 200 } }

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 20
                spacing: 12

                Text {
                    id: searchResultsTitle
                    text: qsTranslate("Application", "Search Results")
                    color: Theme.primaryAccent
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeNormal
                    font.bold: true
                    Layout.fillWidth: true
                }

                ListView {
                    id: searchResultsList
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    model: searchResultsModel
                    spacing: 2
                    boundsBehavior: Flickable.DragOverBounds
                    flickDeceleration: 5000
                    maximumFlickVelocity: 2500

                    ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

                    delegate: Rectangle {
                        width: searchResultsList.width
                        height: 36
                        color: resultMouse.containsMouse ? Qt.lighter(Theme.surfaceDark, 1.4) : Theme.surfaceDark
                        radius: 6
                        Behavior on color { ColorAnimation { duration: 80 } }

                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 12
                            anchors.rightMargin: 12
                            spacing: 10

                            Text {
                                text: model.name
                                color: Theme.textPrimary
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSizeSmall
                                elide: Text.ElideRight
                                Layout.fillWidth: true
                            }
                            Text {
                                text: model.fileId
                                color: Theme.textSecondary
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSizeSmall
                                Layout.preferredWidth: 100
                            }
                            Text {
                                visible: model.bnkId !== ""
                                text: model.bnkId !== "" ? qsTranslate("Application", "BNK: ") + model.bnkId : ""
                                color: Theme.textSecondary
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSizeSmall - 1
                                elide: Text.ElideRight
                                Layout.preferredWidth: model.bnkId !== "" ? 130 : 0
                            }
                            Text {
                                text: model.tags
                                color: Theme.secondaryAccent
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSizeSmall
                                elide: Text.ElideRight
                                Layout.preferredWidth: 140
                            }
                        }

                        MouseArea {
                            id: resultMouse
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: {

                                audioBrowserBackend.navigateToSearchResult(
                                    model.fileId, model.itemType, model.pckPath, model.bnkId)
                                searchResultsOverlay.closing = true
                                searchHideTimer.start()
                            }
                        }
                    }

                    Text {
                        anchors.centerIn: parent
                        text: qsTranslate("Application", "No results found.")
                        color: Theme.textSecondary
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeNormal
                        visible: searchResultsModel.count === 0
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    Item { Layout.fillWidth: true }
                    XXARButton {
                        text: qsTranslate("Application", "Close")
                        onClicked: {
                            searchResultsOverlay.closing = true
                            searchHideTimer.start()
                        }
                    }
                }
            }
        }
    }

    Item {
        id: matchResultsOverlay
        visible: false
        anchors.fill: parent
        z: 2000
        property bool closing: false

        Timer {
            id: matchHideTimer
            interval: 200
            onTriggered: {
                matchResultsOverlay.visible = false
                matchResultsOverlay.closing = false
            }
        }

        ListModel { id: matchResultsModel }

        Rectangle {
            anchors.fill: parent
            color: "#80000000"
            opacity: (!matchResultsOverlay.closing && matchResultsOverlay.visible) ? 1.0 : 0.0
            Behavior on opacity { NumberAnimation { duration: 200 } }

            MouseArea {
                anchors.fill: parent
                onClicked: {
                    matchResultsOverlay.closing = true
                    matchHideTimer.start()
                }
            }
        }

        Rectangle {
            id: matchDialog
            width: Math.min(750, parent.width - 60)
            height: Math.min(550, parent.height - 80)
            anchors.centerIn: parent
            color: Theme.surfaceColor
            radius: Theme.radiusLarge
            border.color: Theme.cardBackground
            border.width: 1
            scale: (!matchResultsOverlay.closing && matchResultsOverlay.visible) ? 1.0 : 0.9
            opacity: (!matchResultsOverlay.closing && matchResultsOverlay.visible) ? 1.0 : 0.0
            Behavior on scale { NumberAnimation { duration: 200; easing.type: Easing.OutBack } }
            Behavior on opacity { NumberAnimation { duration: 200 } }

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 20
                spacing: 12

                Text {
                    id: matchResultsTitle
                    text: qsTranslate("Application", "Match Results") + " (" + matchResultsModel.count + " " + qsTranslate("Application", "found") + ")"
                    color: Theme.primaryAccent
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeNormal
                    font.bold: true
                    Layout.fillWidth: true
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 10
                    visible: matchResultsModel.count > 0

                    Text {
                        text: qsTranslate("Application", "Score")
                        color: Theme.textSecondary
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeSmall
                        font.bold: true
                        Layout.preferredWidth: 60
                    }
                    Text {
                        text: qsTranslate("Application", "Sound")
                        color: Theme.textSecondary
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeSmall
                        font.bold: true
                        Layout.fillWidth: true
                    }
                    Text {
                        text: qsTranslate("Application", "File ID")
                        color: Theme.textSecondary
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeSmall
                        font.bold: true
                        Layout.preferredWidth: 100
                    }
                    Text {
                        text: qsTranslate("Application", "PCK")
                        color: Theme.textSecondary
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeSmall
                        font.bold: true
                        Layout.preferredWidth: 160
                    }
                }

                ListView {
                    id: matchResultsList
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    model: matchResultsModel
                    spacing: 2
                    boundsBehavior: Flickable.DragOverBounds
                    flickDeceleration: 5000
                    maximumFlickVelocity: 2500

                    ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

                    delegate: Rectangle {
                        width: matchResultsList.width
                        height: 40
                        color: matchResultMouse.containsMouse ? Qt.lighter(Theme.surfaceDark, 1.4) : Theme.surfaceDark
                        radius: 6
                        Behavior on color { ColorAnimation { duration: 80 } }

                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 12
                            anchors.rightMargin: 12
                            spacing: 10

                            XXARButton {
                                text: "▶"
                                Layout.preferredWidth: 45
                                Layout.preferredHeight: 28
                                buttonColor: Theme.primaryAccent
                                fontSize: 12
                                onClicked: {
                                    console.log("Play button clicked for:", model.fileId, model.itemType, model.pckPath)
                                    treeItemDoubleClicked(model.fileId, model.itemType, model.pckPath)
                                }
                            }

                            Rectangle {
                                width: 50
                                height: 22
                                radius: 11
                                color: {
                                    var s = model.score
                                    if (s >= 70) return "#2e7d32"
                                    if (s >= 50) return "#f57f17"
                                    if (s >= 30) return "#e65100"
                                    return "#c62828"
                                }
                                Layout.preferredWidth: 60
                                Layout.alignment: Qt.AlignVCenter

                                Text {
                                    anchors.centerIn: parent
                                    text: model.score + "%"
                                    color: "#ffffff"
                                    font.family: Theme.fontFamily
                                    font.pixelSize: 12
                                    font.bold: true
                                }
                            }
                            Text {
                                text: model.name
                                color: Theme.textPrimary
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSizeSmall
                                elide: Text.ElideRight
                                Layout.fillWidth: true
                            }
                            Text {
                                text: model.fileId
                                color: Theme.textSecondary
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSizeSmall
                                Layout.preferredWidth: 100
                            }
                            Text {
                                text: model.pckName
                                color: Theme.textSecondary
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSizeSmall
                                elide: Text.ElideRight
                                Layout.preferredWidth: 160
                            }
                        }

                        MouseArea {
                            id: matchResultMouse
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            propagateComposedEvents: true
                            onPressed: {

                                if (mouse.x <= 70) {
                                    mouse.accepted = false
                                }
                            }
                            onClicked: {

                                if (mouse.x > 70) {
                                    audioBrowserBackend.navigateToSearchResult(
                                        model.fileId, model.itemType, model.pckPath, model.bnkId)
                                    matchResultsOverlay.closing = true
                                    matchHideTimer.start()
                                }
                            }
                        }
                    }

                    Text {
                        anchors.centerIn: parent
                        text: qsTranslate("Application", "No matches found.")
                        color: Theme.textSecondary
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeNormal
                        visible: matchResultsModel.count === 0
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    Item { Layout.fillWidth: true }
                    XXARButton {
                        text: qsTranslate("Application", "Close")
                        onClicked: {
                            matchResultsOverlay.closing = true
                            matchHideTimer.start()
                        }
                    }
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
        property bool loopColumnVisible: false
        property bool volumeColumnVisible: false

        Timer {
            id: changesHideTimer
            interval: 200
            onTriggered: {
                changesOverlay.visible = false
                changesOverlay.closing = false
            }
        }

        ListModel { id: changesModel }

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

            MouseArea {
                anchors.fill: parent
                onClicked: {
                    changesOverlay.closing = true
                    changesHideTimer.start()
                }
            }
        }

        Rectangle {
            id: changesDialog
            width: Math.min(parent.width - 40, 900
                + (changesOverlay.loopColumnVisible ? 270 : 0)
                + (changesOverlay.volumeColumnVisible ? 100 : 0))
            height: Math.min(620, parent.height - 60)
            anchors.centerIn: parent
            color: Theme.surfaceColor
            radius: Theme.radiusLarge
            border.color: Theme.cardBackground
            border.width: 1
            scale: (!changesOverlay.closing && changesOverlay.visible) ? 1.0 : 0.9
            opacity: (!changesOverlay.closing && changesOverlay.visible) ? 1.0 : 0.0
            Behavior on scale { NumberAnimation { duration: 200; easing.type: Easing.OutBack } }
            Behavior on opacity { NumberAnimation { duration: 200 } }

            // Block mouse events from reaching the backdrop/page behind the dialog.
            // z: -1 keeps it below all child controls so buttons/combos still work.
            MouseArea {
                anchors.fill: parent
                z: -1
            }

            ColumnLayout {
                id: changesColumns
                anchors.fill: parent
                anchors.margins: 20
                spacing: 12

                // ── Column width definitions (single source of truth) ──
                // Fixed columns
                property int colFileId:   86
                property int colTagged:  150
                property int colType:    100
                property int colModified: 80
                property int colActions: 190
                // Optional columns (0 when hidden)
                property int colLoop: changesOverlay.loopColumnVisible ? 260 : 0
                property int colVol:  changesOverlay.volumeColumnVisible ? 90  : 0
                // Flexible "Replaced By" gets whatever is left
                property int _fixedTotal: colFileId + colTagged + colType + colModified + colActions + colLoop + colVol
                property int _rowSpacing: 8
                property int _rowPadding: 24  // 12 left + 12 right
                property int _gaps: 7 * _rowSpacing  // 8 columns → 7 gaps
                property int _availableWidth: changesDialog.width - 40 - _rowPadding - _gaps
                property int colReplaced: Math.max(80, _availableWidth - _fixedTotal)

                Text {
                    id: changesTitle
                    text: qsTranslate("Application", "Current Changes")
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

                    Row {
                        anchors.verticalCenter: parent.verticalCenter
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.leftMargin: 12
                        anchors.rightMargin: 12
                        spacing: changesColumns._rowSpacing

                        Repeater {
                            model: [
                                { label: qsTranslate("Application", "File ID"),     w: changesColumns.colFileId },
                                { label: qsTranslate("Application", "Tagged Name"),  w: changesColumns.colTagged },
                                { label: qsTranslate("Application", "Replaced By"),  w: changesColumns.colReplaced },
                                { label: qsTranslate("Application", "Type"),         w: changesColumns.colType },
                                { label: qsTranslate("Application", "Loop"),         w: changesColumns.colLoop },
                                { label: qsTranslate("Application", "Vol (dB)"),          w: changesColumns.colVol },
                                { label: qsTranslate("Application", "Modified"),     w: changesColumns.colModified },
                                { label: qsTranslate("Application", "Actions"),      w: changesColumns.colActions }
                            ]
                            Text {
                                text: modelData.label
                                width: modelData.w
                                visible: modelData.w > 0
                                color: Theme.textSecondary
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSizeSmall
                                font.bold: true
                                horizontalAlignment: modelData.label === qsTranslate("Application", "Actions") ? Text.AlignHCenter : Text.AlignLeft
                            }
                        }
                    }
                }

                ListView {
                    id: changesList
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    model: changesModel
                    spacing: 2
                    boundsBehavior: Flickable.DragOverBounds
                    flickDeceleration: 5000
                    maximumFlickVelocity: 2500

                    ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

                    delegate: Rectangle {
                        property int rowIndex: index
                        width: changesList.width
                        height: 36
                        color: changeMouse.containsMouse ? Qt.lighter(Theme.surfaceDark, 1.4) : Theme.surfaceDark
                        radius: 6
                        Behavior on color { ColorAnimation { duration: 80 } }

                        Row {
                            anchors.fill: parent
                            anchors.leftMargin: 12
                            anchors.rightMargin: 12
                            spacing: changesColumns._rowSpacing

                            Text {
                                text: model.fileId
                                width: changesColumns.colFileId
                                height: parent.height
                                verticalAlignment: Text.AlignVCenter
                                color: Theme.textPrimary
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSizeSmall
                                clip: true
                            }
                            Text {
                                text: model.taggedName || "-"
                                width: changesColumns.colTagged
                                height: parent.height
                                verticalAlignment: Text.AlignVCenter
                                color: model.taggedName ? Theme.primaryAccent : Theme.textSecondary
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSizeSmall
                                elide: Text.ElideRight
                                clip: true
                            }
                            Text {
                                text: model.sourceFile || "-"
                                width: changesColumns.colReplaced
                                height: parent.height
                                verticalAlignment: Text.AlignVCenter
                                color: Theme.textPrimary
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSizeSmall
                                elide: Text.ElideMiddle
                                clip: true
                            }
                            Text {
                                text: model.fileType
                                width: changesColumns.colType
                                height: parent.height
                                verticalAlignment: Text.AlignVCenter
                                color: Theme.secondaryAccent
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSizeSmall
                            }

                            Item {
                                visible: changesColumns.colLoop > 0
                                width: changesColumns.colLoop
                                height: 36

                                Row {
                                    anchors.verticalCenter: parent.verticalCenter
                                    spacing: 6
                                    visible: loopPointEditable

                                    ComboBox {
                                        id: rowLoopModeCombo
                                        model: [
                                            qsTranslate("Application", "Automatic"),
                                            qsTranslate("Application", "Manual"),
                                            qsTranslate("Application", "Disabled")
                                        ]
                                        width: 130
                                        implicitHeight: 28
                                        currentIndex: loopModeToIndex(loopPointMode || "auto")

                                        background: Rectangle {
                                            HoverHandler { id: loopModeBgHover }
                                            color: rowLoopModeCombo.pressed ? Qt.darker(Theme.cardBackground, 1.2)
                                                 : loopModeBgHover.hovered ? Qt.lighter(Theme.cardBackground, 1.1)
                                                 : Theme.cardBackground
                                            radius: Theme.radiusSmall
                                            border.color: "transparent"
                                            border.width: 0
                                            Behavior on color { ColorAnimation { duration: 120 } }
                                        }

                                        contentItem: Text {
                                            text: rowLoopModeCombo.displayText
                                            color: Theme.textPrimary
                                            font.family: Theme.fontFamily
                                            font.pixelSize: Theme.fontSizeSmall
                                            verticalAlignment: Text.AlignVCenter
                                            leftPadding: 10
                                            rightPadding: 26
                                        }

                                        indicator: Rectangle {
                                            x: rowLoopModeCombo.width - width - 8
                                            y: (rowLoopModeCombo.height - height) / 2
                                            width: 14
                                            height: 14
                                            color: "transparent"
                                            Text {
                                                anchors.centerIn: parent
                                                text: "\u25BC"
                                                color: Theme.textPrimary
                                                font.pixelSize: 9
                                            }
                                        }

                                        delegate: ItemDelegate {
                                            id: loopModeDelegate
                                            width: rowLoopModeCombo.width - 8
                                            height: 28
                                            highlighted: rowLoopModeCombo.highlightedIndex === index
                                            HoverHandler { id: loopModeDelegateHover }

                                            background: Rectangle {
                                                color: {
                                                    if (loopModeDelegate.highlighted) return Theme.primaryAccent
                                                    if (loopModeDelegateHover.hovered) return Qt.lighter(Theme.surfaceDark, 1.3)
                                                    return Theme.surfaceDark
                                                }
                                                radius: Theme.radiusSmall
                                                Behavior on color { ColorAnimation { duration: 100 } }
                                            }

                                            contentItem: Text {
                                                text: modelData
                                                color: loopModeDelegate.highlighted ? Theme.textOnAccent : Theme.textPrimary
                                                font.family: Theme.fontFamily
                                                font.pixelSize: Theme.fontSizeSmall
                                                verticalAlignment: Text.AlignVCenter
                                                leftPadding: 10
                                            }
                                        }

                                        popup: Popup {
                                            y: rowLoopModeCombo.height + 4
                                            width: rowLoopModeCombo.width
                                            padding: 4
                                            z: 3000

                                            background: Rectangle {
                                                color: Theme.surfaceDark
                                                radius: Theme.radiusSmall
                                                border.color: Qt.rgba(1, 1, 1, 0.1)
                                                border.width: 1
                                            }

                                            contentItem: ListView {
                                                clip: true
                                                implicitHeight: contentHeight
                                                model: rowLoopModeCombo.popup.visible ? rowLoopModeCombo.delegateModel : null
                                                currentIndex: rowLoopModeCombo.highlightedIndex
                                                spacing: 2
                                            }
                                        }

                                        onActivated: function(selectedIndex) {
                                            var selectedMode = loopIndexToMode(selectedIndex)
                                            if (selectedMode !== (loopPointMode || "auto")) {
                                                changesModel.setProperty(rowIndex, "loopPointMode", selectedMode)
                                                changeLoopPointModeSet(pckFile, trackerKey, selectedMode)
                                                if (selectedMode === "manual") {
                                                    var suggestedMs = Math.max(
                                                        1,
                                                        loopPointSuggestedMs || loopPointManualMs || 0
                                                    )
                                                    changesModel.setProperty(rowIndex, "loopPointManualMs", suggestedMs)
                                                    rowLoopManualSpin.value = suggestedMs
                                                    changeLoopPointManualMsSet(
                                                        pckFile,
                                                        trackerKey,
                                                        formatDurationMs(suggestedMs)
                                                    )
                                                }
                                            }
                                        }
                                    }

                                    SpinBox {
                                        id: rowLoopManualSpin
                                        from: 1
                                        to: 3600000
                                        width: 118
                                        implicitHeight: 28
                                        editable: true
                                        value: Math.max(1, loopPointManualMs || 0)
                                        visible: (loopPointMode || "auto") === "manual"
                                        textFromValue: function(value, locale) {
                                            return formatDurationMs(value)
                                        }
                                        valueFromText: function(text, locale) {
                                            var raw = String(text || "").trim()
                                            var m = raw.match(/^(\d+)\s*:\s*([0-5]?\d)\s*:\s*(\d{1,3})$/)
                                            if (m) {
                                                var mm = parseInt(m[1], 10)
                                                var ss = parseInt(m[2], 10)
                                                var mss = parseInt((m[3] + "000").slice(0, 3), 10)
                                                return Math.max(1, (mm * 60 + ss) * 1000 + mss)
                                            }
                                            if (/^\d+$/.test(raw)) {
                                                return Math.max(1, parseInt(raw, 10))
                                            }
                                            return Math.max(1, loopPointManualMs || 1)
                                        }

                                        background: Rectangle {
                                            HoverHandler { id: loopSpinBgHover }
                                            color: loopSpinBgHover.hovered
                                                ? Qt.lighter(Theme.cardBackground, 1.08)
                                                : Theme.cardBackground
                                            radius: Theme.radiusSmall
                                        }

                                        contentItem: TextInput {
                                            text: rowLoopManualSpin.textFromValue(rowLoopManualSpin.value, rowLoopManualSpin.locale)
                                            anchors.fill: parent
                                            anchors.leftMargin: 6
                                            anchors.rightMargin: 22
                                            font.family: Theme.fontFamily
                                            font.pixelSize: Theme.fontSizeSmall
                                            color: Theme.textPrimary
                                            horizontalAlignment: Text.AlignHCenter
                                            verticalAlignment: Text.AlignVCenter
                                            readOnly: !rowLoopManualSpin.editable
                                            validator: rowLoopManualSpin.validator
                                            inputMethodHints: Qt.ImhNone
                                            selectByMouse: true
                                            clip: true
                                            onTextEdited: {
                                                rowLoopManualSpin.value = rowLoopManualSpin.valueFromText(
                                                    text,
                                                    rowLoopManualSpin.locale
                                                )
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
                                            if ((loopPointMode || "auto") === "manual"
                                                    && value !== (loopPointManualMs || 0)) {
                                                changesModel.setProperty(rowIndex, "loopPointManualMs", value)
                                                changeLoopPointManualMsSet(
                                                    pckFile,
                                                    trackerKey,
                                                    formatDurationMs(value)
                                                )
                                            }
                                        }
                                    }

                                }

                                Text {
                                    anchors.verticalCenter: parent.verticalCenter
                                    visible: !loopPointEditable
                                    text: "-"
                                    color: Theme.textSecondary
                                    font.family: Theme.fontFamily
                                    font.pixelSize: Theme.fontSizeSmall
                                }
                            }

                            // Volume column
                            Item {
                                visible: changesColumns.colVol > 0
                                width: changesColumns.colVol
                                height: 36

                                Row {
                                    anchors.verticalCenter: parent.verticalCenter
                                    spacing: 4
                                    visible: volumeEditable

                                    CheckBox {
                                        id: volEnableCheck
                                        anchors.verticalCenter: parent.verticalCenter
                                        checked: volumeEnabled !== false
                                        width: 20; height: 20
                                        indicator: Rectangle {
                                            width: 16; height: 16
                                            radius: 3
                                            anchors.centerIn: parent
                                            color: volEnableCheck.checked ? Theme.primaryAccent : "transparent"
                                            border.color: volEnableCheck.checked ? Theme.primaryAccent : Theme.textSecondary
                                            border.width: 1
                                            Text {
                                                anchors.centerIn: parent
                                                text: "\u2713"
                                                color: Theme.textOnAccent
                                                font.pixelSize: 11
                                                font.bold: true
                                                visible: volEnableCheck.checked
                                            }
                                        }
                                        onCheckedChanged: {
                                            if (checked !== (volumeEnabled || false)) {
                                                changesModel.setProperty(rowIndex, "volumeEnabled", checked)
                                                changeVolumeEnabledSet(pckFile, trackerKey, checked)
                                            }
                                        }
                                    }

                                    SpinBox {
                                        anchors.verticalCenter: parent.verticalCenter
                                        visible: volEnableCheck.checked
                                        width: 62
                                        height: 28
                                        from: -960
                                        to: 240
                                        stepSize: 5
                                        value: Math.round((volumeDb || 0.0) * 10)
                                        editable: true

                                        textFromValue: function(value, locale) {
                                            return (value / 10.0).toFixed(1)
                                        }
                                        valueFromText: function(text, locale) {
                                            var v = parseFloat(text)
                                            if (isNaN(v)) return 0
                                            return Math.round(v * 10)
                                        }

                                        onValueModified: {
                                            var dbVal = value / 10.0
                                            changesModel.setProperty(rowIndex, "volumeDb", dbVal)
                                            changeVolumeDbSet(pckFile, trackerKey, dbVal.toFixed(1))
                                        }

                                        background: Rectangle {
                                            color: Theme.inputBackground || "#2a2a2a"
                                            border.color: Theme.cardBackground
                                            border.width: 1
                                            radius: Theme.radiusSmall
                                        }
                                        contentItem: TextInput {
                                            text: parent.textFromValue(parent.value, parent.locale)
                                            font.family: Theme.fontFamily
                                            font.pixelSize: 11
                                            color: Theme.textPrimary
                                            horizontalAlignment: Qt.AlignHCenter
                                            verticalAlignment: Qt.AlignVCenter
                                            readOnly: !parent.editable
                                            validator: DoubleValidator {
                                                bottom: -96.0
                                                top: 24.0
                                                decimals: 1
                                            }
                                        }
                                        up.indicator: Item { width: 0 }
                                        down.indicator: Item { width: 0 }
                                    }
                                }

                                Text {
                                    anchors.verticalCenter: parent.verticalCenter
                                    visible: !volumeEditable
                                    text: "-"
                                    color: Theme.textSecondary
                                    font.family: Theme.fontFamily
                                    font.pixelSize: Theme.fontSizeSmall
                                }
                            }

                            Text {
                                text: {
                                    var date = new Date(model.dateModified)
                                    if (isNaN(date.getTime())) return qsTranslate("Application", "Unknown")
                                    var now = new Date()
                                    var diffMs = now - date
                                    var diffMins = Math.floor(diffMs / 60000)
                                    var diffHours = Math.floor(diffMins / 60)
                                    var diffDays = Math.floor(diffHours / 24)
                                    if (diffMins < 1) return qsTranslate("Application", "Just now")
                                    if (diffMins < 60) return qsTranslate("Application", "%1m ago").arg(diffMins)
                                    if (diffHours < 24) return qsTranslate("Application", "%1h ago").arg(diffHours)
                                    if (diffDays < 7) return qsTranslate("Application", "%1d ago").arg(diffDays)
                                    return date.toLocaleDateString()
                                }
                                color: Theme.textSecondary
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSizeSmall
                                width: changesColumns.colModified
                                height: parent.height
                                verticalAlignment: Text.AlignVCenter
                            }

                            Item {
                                width: changesColumns.colActions
                                height: 36

                                Row {
                                    anchors.centerIn: parent
                                    spacing: 10

                                    XXARButton {
                                        text: qsTranslate("Application", "Play")
                                        width: 52
                                        height: 28
                                        buttonColor: Theme.primaryAccent
                                        fontSize: 12
                                        visible: model.wemPath !== ""
                                        onClicked: {
                                            playReplacementClicked(model.wemPath)
                                        }
                                    }

                                    XXARButton {
                                        text: qsTranslate("Application", "Orig")
                                        width: 60
                                        height: 28
                                        buttonColor: "#555555"
                                        fontSize: 11
                                        visible: model.pckPath !== ""
                                        onClicked: {
                                            playOriginalClicked(model.fileId, model.itemType, model.pckPath, model.bnkId)
                                        }
                                    }

                                    XXARButton {
                                        text: qsTranslate("Application", "Remove")
                                        width: 72
                                        height: 28
                                        buttonColor: Theme.disabledAccent
                                        fontSize: 11
                                        onClicked: {
                                            removeChangeRequested(model.pckFile, model.trackerKey)
                                        }
                                    }
                                }
                            }
                        }

                        MouseArea {
                            id: changeMouse
                            anchors.left: parent.left
                            anchors.top: parent.top
                            anchors.bottom: parent.bottom
                            anchors.right: parent.right
                            anchors.rightMargin: changesColumns.colLoop + changesColumns.colVol + changesColumns.colModified + changesColumns.colActions + 60
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: {

                                navigateToChangeClicked(model.pckFile, model.fileId, model.itemType, model.bnkId)

                                closeChangesDialog()
                            }
                        }
                    }

                    Text {
                        anchors.centerIn: parent
                        text: qsTranslate("Application", "No changes yet.\nReplace some audio files to see them here.")
                        color: Theme.textSecondary
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeNormal
                        horizontalAlignment: Text.AlignHCenter
                        visible: changesModel.count === 0
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: Theme.spacingSmall

                    Item { Layout.fillWidth: true }

                    XXARButton {
                        text: qsTranslate("Application", "Apply Changes")
                        buttonColor: Theme.primaryAccent
                        visible: changesModel.count > 0
                        onClicked: {
                            applyChangesClicked()
                            changesOverlay.closing = true
                            changesHideTimer.start()
                        }
                    }

                    XXARButton {
                        text: qsTranslate("Application", "Close")
                        onClicked: {
                            changesOverlay.closing = true
                            changesHideTimer.start()
                        }
                    }
                }
            }
        }
    }

    Item {
        id: tagOverlay
        visible: false
        anchors.fill: parent
        z: 2001
        property bool closing: false

        Timer {
            id: tagHideTimer
            interval: 200
            onTriggered: {
                tagOverlay.visible = false
                tagOverlay.closing = false
            }
        }

        Rectangle {
            anchors.fill: parent
            color: "#80000000"
            opacity: (!tagOverlay.closing && tagOverlay.visible) ? 1.0 : 0.0
            Behavior on opacity { NumberAnimation { duration: 200 } }

            MouseArea {
                anchors.fill: parent
                onClicked: {
                    tagOverlay.closing = true
                    tagHideTimer.start()
                }
            }
        }

        Rectangle {
            id: tagDialog
            width: Math.min(450, parent.width - 60)
            height: Math.min(400, parent.height - 80)
            anchors.centerIn: parent
            color: Theme.surfaceColor
            radius: Theme.radiusLarge
            border.color: Theme.cardBackground
            border.width: 1
            scale: (!tagOverlay.closing && tagOverlay.visible) ? 1.0 : 0.9
            opacity: (!tagOverlay.closing && tagOverlay.visible) ? 1.0 : 0.0
            Behavior on scale { NumberAnimation { duration: 200; easing.type: Easing.OutBack } }
            Behavior on opacity { NumberAnimation { duration: 200 } }

            property string currentItemId: ""
            property string currentItemType: ""
            property string currentPckPath: ""

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 20
                spacing: 12

                Text {
                    text: qsTranslate("Application", "Tag Sound")
                    color: Theme.primaryAccent
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeNormal
                    font.bold: true
                    Layout.fillWidth: true
                }

                Text {
                    text: qsTranslate("Application", "Name:")
                    color: Theme.textPrimary
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeSmall
                }
                Rectangle {
                    Layout.fillWidth: true
                    height: Theme.buttonHeight
                    color: Theme.cardBackground
                    radius: Theme.radiusMedium

                    TextInput {
                        id: tagNameInput
                        anchors.fill: parent
                        anchors.leftMargin: 14
                        anchors.rightMargin: 14
                        verticalAlignment: Text.AlignVCenter
                        color: Theme.textPrimary
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeSmall
                        clip: true
                        selectByMouse: true

                        Text {
                            anchors.fill: parent
                            verticalAlignment: Text.AlignVCenter
                            color: Theme.textSecondary
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSizeSmall
                            text: qsTranslate("Application", "e.g., Astra Ultimate Voice")
                            visible: !tagNameInput.text && !tagNameInput.activeFocus
                        }
                    }
                }

                Text {
                    text: qsTranslate("Application", "Tags (comma-separated):")
                    color: Theme.textPrimary
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeSmall
                }
                Rectangle {
                    Layout.fillWidth: true
                    height: Theme.buttonHeight
                    color: Theme.cardBackground
                    radius: Theme.radiusMedium

                    TextInput {
                        id: tagTagsInput
                        anchors.fill: parent
                        anchors.leftMargin: 14
                        anchors.rightMargin: 14
                        verticalAlignment: Text.AlignVCenter
                        color: Theme.textPrimary
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeSmall
                        clip: true
                        selectByMouse: true

                        Text {
                            anchors.fill: parent
                            verticalAlignment: Text.AlignVCenter
                            color: Theme.textSecondary
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSizeSmall
                            text: qsTranslate("Application", "e.g., astra, ultimate, voice")
                            visible: !tagTagsInput.text && !tagTagsInput.activeFocus
                        }
                    }
                }

                Text {
                    text: qsTranslate("Application", "Notes:")
                    color: Theme.textPrimary
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeSmall
                }
                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 80
                    color: Theme.cardBackground
                    radius: Theme.radiusMedium

                    TextEdit {
                        id: tagNotesInput
                        anchors.fill: parent
                        anchors.margins: 14
                        color: Theme.textPrimary
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeSmall
                        wrapMode: TextEdit.Wrap
                        selectByMouse: true
                        clip: true

                        Text {
                            anchors.fill: parent
                            color: Theme.textSecondary
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSizeSmall
                            text: qsTranslate("Application", "Additional notes...")
                            visible: !tagNotesInput.text && !tagNotesInput.activeFocus
                        }
                    }
                }

                Text {
                    id: tagHashLabel
                    text: qsTranslate("Application", "Hash: ")
                    color: Theme.textSecondary
                    font.family: Theme.fontFamily
                    font.pixelSize: 9
                    Layout.fillWidth: true
                }

                Item { Layout.fillHeight: true }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: Theme.spacingSmall

                    Item { Layout.fillWidth: true }

                    XXARButton {
                        text: qsTranslate("Application", "Cancel")
                        buttonColor: Theme.disabledAccent
                        onClicked: {
                            tagOverlay.closing = true
                            tagHideTimer.start()
                        }
                    }

                    XXARButton {
                        text: qsTranslate("Application", "Save")
                        buttonColor: Theme.primaryAccent
                        onClicked: {
                            var name = tagNameInput.text.trim()
                            if (!name) {

                                return
                            }

                            var tagsText = tagTagsInput.text.trim()
                            var tags = []
                            if (tagsText) {
                                var tagParts = tagsText.split(',')
                                for (var i = 0; i < tagParts.length; i++) {
                                    var tag = tagParts[i].trim()
                                    if (tag) tags.push(tag)
                                }
                            }

                            var notes = tagNotesInput.text.trim()

                            audioBrowserBackend.saveTag(
                                tagDialog.currentItemId,
                                tagDialog.currentItemType,
                                tagDialog.currentPckPath,
                                name,
                                tags.join(', '),
                                notes
                            )

                            tagOverlay.closing = true
                            tagHideTimer.start()
                        }
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
            onTriggered: {
                metadataOverlay.visible = false
                metadataOverlay.closing = false
            }
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

            MouseArea {
                anchors.fill: parent
                onClicked: {
                    metadataOverlay.closing = true
                    metadataHideTimer.start()
                }
            }
        }

        Rectangle {
            id: metadataDialog
            width: Math.min(500, parent.width - 60)
            height: Math.min(550, parent.height - 80)
            anchors.centerIn: parent
            color: Theme.surfaceColor
            radius: Theme.radiusLarge
            border.color: Theme.cardBackground
            border.width: 1
            scale: (!metadataOverlay.closing && metadataOverlay.visible) ? 1.0 : 0.9
            opacity: (!metadataOverlay.closing && metadataOverlay.visible) ? 1.0 : 0.0
            Behavior on scale { NumberAnimation { duration: 200; easing.type: Easing.OutBack } }
            Behavior on opacity { NumberAnimation { duration: 200 } }

            MouseArea {
                anchors.fill: parent
                onClicked: {

                }
            }

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

                Text {
                    text: qsTranslate("Application", "Name*:")
                    color: Theme.textPrimary
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeSmall
                }
                Rectangle {
                    Layout.fillWidth: true
                    height: Theme.buttonHeight
                    color: Theme.cardBackground
                    radius: Theme.radiusMedium

                    TextInput {
                        id: metadataNameInput
                        anchors.fill: parent
                        anchors.leftMargin: 14
                        anchors.rightMargin: 14
                        verticalAlignment: Text.AlignVCenter
                        color: Theme.textPrimary
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeSmall
                        clip: true

                        Text {
                            anchors.fill: parent
                            verticalAlignment: Text.AlignVCenter
                            color: Theme.textSecondary
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSizeSmall
                            text: qsTranslate("Application", "My Awesome Mod")
                            visible: !metadataNameInput.text && !metadataNameInput.activeFocus
                        }
                    }
                }

                Text {
                    text: qsTranslate("Application", "Author*:")
                    color: Theme.textPrimary
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeSmall
                }
                Rectangle {
                    Layout.fillWidth: true
                    height: Theme.buttonHeight
                    color: Theme.cardBackground
                    radius: Theme.radiusMedium

                    TextInput {
                        id: metadataAuthorInput
                        anchors.fill: parent
                        anchors.leftMargin: 14
                        anchors.rightMargin: 14
                        verticalAlignment: Text.AlignVCenter
                        color: Theme.textPrimary
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeSmall
                        clip: true

                        Text {
                            anchors.fill: parent
                            verticalAlignment: Text.AlignVCenter
                            color: Theme.textSecondary
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSizeSmall
                            text: qsTranslate("Application", "Your Name")
                            visible: !metadataAuthorInput.text && !metadataAuthorInput.activeFocus
                        }
                    }
                }

                Text {
                    text: qsTranslate("Application", "Version:")
                    color: Theme.textPrimary
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeSmall
                }
                Rectangle {
                    Layout.fillWidth: true
                    height: Theme.buttonHeight
                    color: Theme.cardBackground
                    radius: Theme.radiusMedium

                    TextInput {
                        id: metadataVersionInput
                        anchors.fill: parent
                        anchors.leftMargin: 14
                        anchors.rightMargin: 14
                        verticalAlignment: Text.AlignVCenter
                        color: Theme.textPrimary
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeSmall
                        text: "1.0.0"
                        clip: true
                    }
                }

                Text {
                    text: qsTranslate("Application", "Description:")
                    color: Theme.textPrimary
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeSmall
                }
                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 100
                    color: Theme.cardBackground
                    radius: Theme.radiusMedium

                    TextEdit {
                        id: metadataDescriptionInput
                        anchors.fill: parent
                        anchors.margins: 14
                        color: Theme.textPrimary
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeSmall
                        wrapMode: TextEdit.Wrap
                        clip: true

                        Text {
                            anchors.fill: parent
                            color: Theme.textSecondary
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSizeSmall
                            text: qsTranslate("Application", "Describe what your mod does...")
                            visible: !metadataDescriptionInput.text && !metadataDescriptionInput.activeFocus
                        }
                    }
                }

                Text {
                    text: qsTranslate("Application", "Thumbnail:")
                    color: Theme.textPrimary
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeSmall
                }
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8

                    Rectangle {
                        Layout.fillWidth: true
                        height: Theme.buttonHeight
                        color: Theme.cardBackground
                        radius: Theme.radiusMedium

                        TextInput {
                            id: metadataThumbnailPathInput
                            anchors.fill: parent
                            anchors.leftMargin: 14
                            anchors.rightMargin: 14
                            verticalAlignment: Text.AlignVCenter
                            color: Theme.textPrimary
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSizeSmall
                            readOnly: true
                            clip: true

                            Text {
                                anchors.fill: parent
                                verticalAlignment: Text.AlignVCenter
                                color: Theme.textSecondary
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSizeSmall
                                text: qsTranslate("Application", "Optional: Select thumbnail image")
                                visible: !metadataThumbnailPathInput.text
                            }
                        }
                    }

                    XXARButton {
                        text: qsTranslate("Application", "Browse")
                        onClicked: audioBrowserBackend.browseThumbnail()
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
                        onClicked: {
                            metadataOverlay.closing = true
                            metadataHideTimer.start()
                        }
                    }

                    XXARButton {
                        text: qsTranslate("Application", "Create Package")
                        buttonColor: Theme.primaryAccent
                        onClicked: {
                            var name = metadataNameInput.text.trim()
                            var author = metadataAuthorInput.text.trim()

                            if (!name || !author) {

                                return
                            }

                            var version = metadataVersionInput.text.trim() || "1.0.0"
                            var description = metadataDescriptionInput.text.trim()
                            var thumbnailPath = metadataThumbnailPathInput.text.trim()

                            createModPackageRequested(name, author, version, description, thumbnailPath)

                            metadataOverlay.closing = true
                            metadataHideTimer.start()
                        }
                    }
                }
            }
        }
    }

    Item {
        id: tagDbOverlay
        visible: false
        anchors.fill: parent
        z: 2003
        property bool closing: false

        Timer {
            id: tagDbHideTimer
            interval: 200
            onTriggered: {
                tagDbOverlay.visible = false
                tagDbOverlay.closing = false
            }
        }

        Rectangle {
            anchors.fill: parent
            color: "#80000000"
            opacity: (!tagDbOverlay.closing && tagDbOverlay.visible) ? 1.0 : 0.0
            Behavior on opacity { NumberAnimation { duration: 200 } }

            Image {
                anchors.fill: parent
                source: "../assets/" + assetsDir + "/gradient.png"
                fillMode: Image.Stretch
                mipmap: true
                opacity: 0.6
            }

            MouseArea {
                anchors.fill: parent
                onClicked: {
                    tagDbOverlay.closing = true
                    tagDbHideTimer.start()
                }
            }
        }

        Rectangle {
            id: tagDbDialog
            width: Math.min(500, parent.width - 40)
            height: tagDbCol.height + 60
            anchors.centerIn: parent
            color: "#252525"
            radius: 20
            border.color: "#3c3d3f"
            border.width: 1
            scale: (!tagDbOverlay.closing && tagDbOverlay.visible) ? 1.0 : 0.9
            opacity: (!tagDbOverlay.closing && tagDbOverlay.visible) ? 1.0 : 0.0
            Behavior on scale { NumberAnimation { duration: 200; easing.type: Easing.OutBack } }
            Behavior on opacity { NumberAnimation { duration: 200 } }

            Column {
                id: tagDbCol
                width: parent.width - 60
                anchors.centerIn: parent
                spacing: 25

                Item { height: 10; width: 1 }

                Image {
                    source: "../assets/" + assetsDir + "/ZhuYuanWrite.png"
                    width: 160
                    height: 160
                    fillMode: Image.PreserveAspectFit
                    mipmap: true
                    anchors.horizontalCenter: parent.horizontalCenter
                }

                Text {
                    text: qsTranslate("Application", "Official Tag Database")
                    color: Theme.primaryAccent
                    font.family: "Alatsi"
                    font.pixelSize: 24
                    width: parent.width
                    horizontalAlignment: Text.AlignHCenter
                    wrapMode: Text.WordWrap
                }

                Text {
                    text: qsTranslate("Application", "Downloaded %1 tag entries.\n\nHow would you like to apply them?").arg(tagDbEntryCount)
                    color: "#ffffff"
                    font.family: "Alatsi"
                    font.pixelSize: 16
                    width: parent.width
                    wrapMode: Text.WordWrap
                    horizontalAlignment: Text.AlignHCenter
                    lineHeight: 1.4
                }

                Text {
                    text: qsTranslate("Application", "Merge adds new entries and updates existing ones.\nReplace completely replaces your local database.")
                    color: "#999999"
                    font.family: "Alatsi"
                    font.pixelSize: 13
                    width: parent.width
                    wrapMode: Text.WordWrap
                    horizontalAlignment: Text.AlignHCenter
                    lineHeight: 1.3
                }

                RowLayout {
                    spacing: 20
                    width: parent.width

                    Item { Layout.fillWidth: true }

                    Rectangle {
                        width: 120
                        height: 45
                        color: Theme.disabledAccent
                        radius: Theme.radiusMedium
                        scale: tagDbCancelMouse.pressed ? 0.97 : (tagDbCancelMouse.containsMouse ? 1.03 : 1.0)
                        Behavior on scale { NumberAnimation { duration: Theme.animationDuration } }

                        Text {
                            anchors.centerIn: parent
                            text: qsTranslate("Application", "Cancel")
                            color: Theme.textPrimary
                            font.family: "Alatsi"
                            font.pixelSize: Theme.fontSizeNormal
                        }

                        MouseArea {
                            id: tagDbCancelMouse
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: {
                                tagDbOverlay.closing = true
                                tagDbHideTimer.start()
                            }
                        }
                    }

                    Rectangle {
                        width: 120
                        height: 45
                        color: Theme.dangerAccent
                        radius: Theme.radiusMedium
                        scale: tagDbReplaceMouse.pressed ? 0.97 : (tagDbReplaceMouse.containsMouse ? 1.03 : 1.0)
                        Behavior on scale { NumberAnimation { duration: Theme.animationDuration } }

                        Text {
                            anchors.centerIn: parent
                            text: qsTranslate("Application", "Replace")
                            color: Theme.textOnAccent
                            font.family: "Alatsi"
                            font.pixelSize: Theme.fontSizeNormal
                        }

                        MouseArea {
                            id: tagDbReplaceMouse
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: {
                                tagDbOverlay.closing = true
                                tagDbHideTimer.start()
                                applyOfficialTagDb(false)
                            }
                        }
                    }

                    Rectangle {
                        width: 120
                        height: 45
                        color: Theme.primaryAccent
                        radius: Theme.radiusMedium
                        scale: tagDbMergeMouse.pressed ? 0.97 : (tagDbMergeMouse.containsMouse ? 1.03 : 1.0)
                        Behavior on scale { NumberAnimation { duration: Theme.animationDuration } }

                        Text {
                            anchors.centerIn: parent
                            text: qsTranslate("Application", "Merge")
                            color: Theme.textOnAccent
                            font.family: "Alatsi"
                            font.pixelSize: Theme.fontSizeNormal
                        }

                        MouseArea {
                            id: tagDbMergeMouse
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: {
                                tagDbOverlay.closing = true
                                tagDbHideTimer.start()
                                applyOfficialTagDb(true)
                            }
                        }
                    }

                    Item { Layout.fillWidth: true }
                }

                Item { height: 5; width: 1 }
            }
        }
    }

    Item {
        id: tagDbNotifyOverlay
        visible: tagDbNotifyVisible
        anchors.fill: parent
        z: 2004
        property bool closing: false

        Timer {
            id: tagDbNotifyHideTimer
            interval: 200
            onTriggered: {
                tagDbNotifyVisible = false
                tagDbNotifyOverlay.closing = false
            }
        }

        Rectangle {
            anchors.fill: parent
            color: "#80000000"
            opacity: (!tagDbNotifyOverlay.closing && tagDbNotifyOverlay.visible) ? 1.0 : 0.0
            Behavior on opacity { NumberAnimation { duration: 200 } }

            Image {
                anchors.fill: parent
                source: "../assets/" + assetsDir + "/gradient.png"
                fillMode: Image.Stretch
                mipmap: true
                opacity: 0.6
            }

            MouseArea {
                anchors.fill: parent
                onClicked: {
                    tagDbNotifyOverlay.closing = true
                    tagDbNotifyHideTimer.start()
                    dismissTagDbNotify(false)
                }
            }
        }

        Rectangle {
            width: Math.min(500, parent.width - 40)
            height: notifyCol.height + 60
            anchors.centerIn: parent
            color: "#252525"
            radius: 20
            border.color: "#3c3d3f"
            border.width: 1
            scale: (!tagDbNotifyOverlay.closing && tagDbNotifyOverlay.visible) ? 1.0 : 0.9
            opacity: (!tagDbNotifyOverlay.closing && tagDbNotifyOverlay.visible) ? 1.0 : 0.0
            Behavior on scale { NumberAnimation { duration: 200; easing.type: Easing.OutBack } }
            Behavior on opacity { NumberAnimation { duration: 200 } }

            Column {
                id: notifyCol
                width: parent.width - 60
                anchors.centerIn: parent
                spacing: 25

                Item { height: 10; width: 1 }

                Image {
                    source: "../assets/" + assetsDir + "/EvelynCall.png"
                    width: 160
                    height: 160
                    fillMode: Image.PreserveAspectFit
                    mipmap: true
                    anchors.horizontalCenter: parent.horizontalCenter
                }

                Text {
                    text: qsTranslate("Application", "New Official Tags Available!")
                    color: Theme.primaryAccent
                    font.family: "Alatsi"
                    font.pixelSize: 22
                    width: parent.width
                    horizontalAlignment: Text.AlignHCenter
                    wrapMode: Text.WordWrap
                }

                Text {
                    text: qsTranslate("Application", "%1 tag entries are available for download.").arg(tagDbNewCount)
                    color: "#ffffff"
                    font.family: "Alatsi"
                    font.pixelSize: 15
                    width: parent.width
                    wrapMode: Text.WordWrap
                    horizontalAlignment: Text.AlignHCenter
                    lineHeight: 1.4
                }

                Text {
                    text: qsTranslate("Application", "You can always download them later from the Options menu on this page.")
                    color: "#999999"
                    font.family: "Alatsi"
                    font.pixelSize: 12
                    width: parent.width
                    wrapMode: Text.WordWrap
                    horizontalAlignment: Text.AlignHCenter
                    lineHeight: 1.3
                }

                Row {
                    anchors.horizontalCenter: parent.horizontalCenter
                    spacing: 8

                    Item {
                        id: notifyDontShowBox
                        width: 20
                        height: 20
                        anchors.verticalCenter: parent.verticalCenter

                        property bool checked: false

                        Rectangle {
                            anchors.fill: parent
                            radius: 4
                            color: "transparent"
                            border.color: notifyDontShowBox.checked ? Theme.primaryAccent : "#888888"
                            border.width: 2
                            Behavior on border.color { ColorAnimation { duration: 100 } }

                            Rectangle {
                                anchors.centerIn: parent
                                width: 12
                                height: 12
                                radius: 2
                                color: Theme.primaryAccent
                                visible: notifyDontShowBox.checked
                            }
                        }

                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: notifyDontShowBox.checked = !notifyDontShowBox.checked
                        }
                    }

                    Text {
                        text: qsTranslate("Application", "Don't show this again")
                        color: "#ffffff"
                        font.family: "Alatsi"
                        font.pixelSize: 14
                        anchors.verticalCenter: parent.verticalCenter

                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: notifyDontShowBox.checked = !notifyDontShowBox.checked
                        }
                    }
                }

                RowLayout {
                    spacing: 20
                    width: parent.width

                    Item { Layout.fillWidth: true }

                    Rectangle {
                        width: 120
                        height: 45
                        color: Theme.disabledAccent
                        radius: Theme.radiusMedium
                        scale: notifyDismissMouse.pressed ? 0.97 : (notifyDismissMouse.containsMouse ? 1.03 : 1.0)
                        Behavior on scale { NumberAnimation { duration: Theme.animationDuration } }

                        Text {
                            anchors.centerIn: parent
                            text: qsTranslate("Application", "Dismiss")
                            color: Theme.textPrimary
                            font.family: "Alatsi"
                            font.pixelSize: Theme.fontSizeNormal
                        }

                        MouseArea {
                            id: notifyDismissMouse
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: {
                                var dontShow = notifyDontShowBox.checked
                                tagDbNotifyOverlay.closing = true
                                tagDbNotifyHideTimer.start()
                                dismissTagDbNotify(dontShow)
                            }
                        }
                    }

                    Rectangle {
                        width: 150
                        height: 45
                        color: Theme.primaryAccent
                        radius: Theme.radiusMedium
                        scale: notifyDownloadMouse.pressed ? 0.97 : (notifyDownloadMouse.containsMouse ? 1.03 : 1.0)
                        Behavior on scale { NumberAnimation { duration: Theme.animationDuration } }

                        Text {
                            anchors.centerIn: parent
                            text: qsTranslate("Application", "Download Now")
                            color: Theme.textOnAccent
                            font.family: "Alatsi"
                            font.pixelSize: Theme.fontSizeNormal
                        }

                        MouseArea {
                            id: notifyDownloadMouse
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: {
                                var dontShow = notifyDontShowBox.checked
                                tagDbNotifyOverlay.closing = true
                                tagDbNotifyHideTimer.start()
                                dismissTagDbNotify(dontShow)
                                downloadOfficialTagDbClicked()
                            }
                        }
                    }

                    Item { Layout.fillWidth: true }
                }

                Item { height: 5; width: 1 }
            }
        }
    }

    AudioMatchDialog {
        id: audioMatchDialog
        objectName: "audioMatchDialog"
    }
}
