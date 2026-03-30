import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15

Item {
    id: root
    objectName: "welcomeDialog"
    visible: false
    anchors.fill: parent
    z: 1500

    property bool closing: false
    property string selectedMode: ""
    property int currentPage: 1
    property string gameDirectory: ""
    property string gameDataFolderName: gameDataFolder
    property bool wwiseInstalled: false
    property bool isInstallingWwise: false
    property bool audioToolsInstalled: false
    property bool isInstallingAudioTools: false
    property bool isAutoDetecting: false
    property string selectedGame: ""
    property var selectedGames: []
    property int gameSetupIndex: 0
    property var gameDirectories: ({})
    property string currentGameDisplayName: ""

    signal modeSelected(string mode)
    signal gameSelected(string gameId)
    signal welcomeLanguageChanged(string langCode)
    signal browseGameDirClicked()
    signal autoDetectClicked()
    signal checkWwiseClicked()
    signal runWwiseSetupClicked()
    signal checkAudioToolsClicked()
    signal runAudioToolsSetupClicked()
    signal startTutorialClicked()

    Timer {
        id: hideTimer
        interval: 200
        onTriggered: {
            visible = false
            closing = false
            currentPage = 1
        }
    }

    Rectangle {
        anchors.fill: parent
        color: "#80000000"
        opacity: (!closing && visible) ? 1.0 : 0.0
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
            onClicked: {}
        }
    }

    Rectangle {
        id: dialog
        width: 700
        height: 600
        anchors.centerIn: parent
        color: "#252525"
        radius: 20
        border.color: "#3c3d3f"
        border.width: 1
        scale: (!closing && visible) ? 1.0 : 0.9
        opacity: (!closing && visible) ? 1.0 : 0.0
        Behavior on scale { NumberAnimation { duration: 200; easing.type: Easing.OutBack } }
        Behavior on opacity { NumberAnimation { duration: 200 } }

        Column {
            anchors.fill: parent
            anchors.margins: 40
            spacing: 20

            Text {
                text: qsTranslate("Application", "Welcome to %1!").replace("%1", appName)
                color: Theme.primaryAccent
                font.family: "Stretch Pro"
                font.pixelSize: 36
                font.letterSpacing: 2
                font.bold: false
                width: parent.width
                horizontalAlignment: Text.AlignHCenter
            }

            Text {
                text: currentPage === 1 ? qsTranslate("Application", "Which game do you want to mod?") :
                        currentPage === 2 ? qsTranslate("Application", "Choose how you want to use %1").replace("%1", appName) :
                        currentPage === 3 ? qsTranslate("Application", "Let's set up your game directory") + (selectedGames.length > 1 ? " — " + currentGameDisplayName : "") :
                        currentPage === 4 ? qsTranslate("Application", "Set up Wwise for mod creation") :
                        currentPage === 5 ? qsTranslate("Application", "Install audio conversion tools") :
                        qsTranslate("Application", "Everything looks good!")

                color: "#aaaaaa"
                font.family: "Alatsi"
                font.pixelSize: 16
                width: parent.width
                horizontalAlignment: Text.AlignHCenter
            }

            Row {
                spacing: 10
                anchors.horizontalCenter: parent.horizontalCenter

                Repeater {
                    model: (selectedMode === "maker" && Qt.platform.os === "windows") ? 6 : (selectedMode === "maker" ? 5 : 4)
                    Rectangle {
                        width: (selectedMode === "maker" && Qt.platform.os === "windows") ? 86 : (selectedMode === "maker" ? 108 : 140)
                        height: 6
                        radius: 3
                        color: index < currentPage ? Theme.primaryAccent : "#3c3d3f"
                        Behavior on color { ColorAnimation { duration: 200 } }
                    }
                }
            }

            Rectangle {
                width: parent.width
                height: 1
                color: "#3c3d3f"
            }

            StackLayout {
                width: parent.width
                height: parent.height - 220
                currentIndex: currentPage - 1

                // Page 1: Game selection (multi-select)
                Item {
                    function toggleGame(gameId) {
                        var games = selectedGames.slice()
                        var idx = games.indexOf(gameId)
                        if (idx === -1) {
                            games.push(gameId)
                        } else {
                            games.splice(idx, 1)
                        }
                        selectedGames = games
                    }

                    Row {
                        anchors.centerIn: parent
                        spacing: 20

                        Rectangle {
                            id: zzzCard
                            property bool isSelected: selectedGames.indexOf("zzz") !== -1
                            width: 180
                            height: Math.max(220, zzzColumn.implicitHeight + 40)
                            color: zzzMouseArea.containsMouse || isSelected ? "#2a2a2a" : "#1a1a1a"
                            radius: 15
                            border.color: isSelected ? "#d8fa00" : (zzzMouseArea.containsMouse ? "#d8fa00" : "#3c3d3f")
                            border.width: isSelected ? 3 : 2
                            scale: zzzMouseArea.pressed ? 0.97 : (zzzMouseArea.containsMouse ? 1.03 : 1.0)
                            Behavior on scale { NumberAnimation { duration: Theme.animationDuration } }
                            Behavior on color { ColorAnimation { duration: Theme.animationDuration } }
                            Behavior on border.color { ColorAnimation { duration: Theme.animationDuration } }

                            Rectangle {
                                width: 24; height: 24; radius: 12
                                color: "#d8fa00"
                                visible: zzzCard.isSelected
                                anchors.right: parent.right
                                anchors.top: parent.top
                                anchors.margins: 10
                                Text { anchors.centerIn: parent; text: "\u2713"; color: "#000000"; font.pixelSize: 14; font.bold: true }
                            }

                            Column {
                                id: zzzColumn
                                anchors.centerIn: parent
                                spacing: 15

                                Rectangle {
                                    width: 80; height: 80; radius: 40
                                    color: "#d8fa00"
                                    anchors.horizontalCenter: parent.horizontalCenter
                                    Text { anchors.centerIn: parent; text: "ZZZ"; color: "#000000"; font.family: "Stretch Pro"; font.pixelSize: 22 }
                                }

                                Text {
                                    text: "Zenless Zone Zero"
                                    color: "#ffffff"; font.family: "Audiowide"; font.pixelSize: 16
                                    width: 160; wrapMode: Text.WordWrap
                                    horizontalAlignment: Text.AlignHCenter
                                    anchors.horizontalCenter: parent.horizontalCenter
                                }
                            }

                            MouseArea {
                                id: zzzMouseArea
                                anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                                onClicked: parent.parent.parent.toggleGame("zzz")
                            }
                        }

                        Rectangle {
                            id: genshinCard
                            property bool isSelected: selectedGames.indexOf("genshin") !== -1
                            width: 180
                            height: Math.max(220, genshinColumn.implicitHeight + 40)
                            color: genshinMouseArea.containsMouse || isSelected ? "#2a2a2a" : "#1a1a1a"
                            radius: 15
                            border.color: isSelected ? "#34c27a" : (genshinMouseArea.containsMouse ? "#34c27a" : "#3c3d3f")
                            border.width: isSelected ? 3 : 2
                            scale: genshinMouseArea.pressed ? 0.97 : (genshinMouseArea.containsMouse ? 1.03 : 1.0)
                            Behavior on scale { NumberAnimation { duration: Theme.animationDuration } }
                            Behavior on color { ColorAnimation { duration: Theme.animationDuration } }
                            Behavior on border.color { ColorAnimation { duration: Theme.animationDuration } }

                            Rectangle {
                                width: 24; height: 24; radius: 12
                                color: "#34c27a"
                                visible: genshinCard.isSelected
                                anchors.right: parent.right
                                anchors.top: parent.top
                                anchors.margins: 10
                                Text { anchors.centerIn: parent; text: "\u2713"; color: "#000000"; font.pixelSize: 14; font.bold: true }
                            }

                            Column {
                                id: genshinColumn
                                anchors.centerIn: parent
                                spacing: 15

                                Rectangle {
                                    width: 80; height: 80; radius: 40
                                    color: "#34c27a"
                                    anchors.horizontalCenter: parent.horizontalCenter
                                    Text { anchors.centerIn: parent; text: "GI"; color: "#000000"; font.family: "Stretch Pro"; font.pixelSize: 26 }
                                }

                                Text {
                                    text: "Genshin Impact"
                                    color: "#ffffff"; font.family: "Audiowide"; font.pixelSize: 16
                                    width: 160; wrapMode: Text.WordWrap
                                    horizontalAlignment: Text.AlignHCenter
                                    anchors.horizontalCenter: parent.horizontalCenter
                                }
                            }

                            MouseArea {
                                id: genshinMouseArea
                                anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                                onClicked: parent.parent.parent.toggleGame("genshin")
                            }
                        }

                        Rectangle {
                            id: hsrCard
                            property bool isSelected: selectedGames.indexOf("hsr") !== -1
                            width: 180
                            height: Math.max(220, hsrColumn.implicitHeight + 40)
                            color: hsrMouseArea.containsMouse || isSelected ? "#2a2a2a" : "#1a1a1a"
                            radius: 15
                            border.color: isSelected ? "#3f9ec3" : (hsrMouseArea.containsMouse ? "#3f9ec3" : "#3c3d3f")
                            border.width: isSelected ? 3 : 2
                            scale: hsrMouseArea.pressed ? 0.97 : (hsrMouseArea.containsMouse ? 1.03 : 1.0)
                            Behavior on scale { NumberAnimation { duration: Theme.animationDuration } }
                            Behavior on color { ColorAnimation { duration: Theme.animationDuration } }
                            Behavior on border.color { ColorAnimation { duration: Theme.animationDuration } }

                            Rectangle {
                                width: 24; height: 24; radius: 12
                                color: "#3f9ec3"
                                visible: hsrCard.isSelected
                                anchors.right: parent.right
                                anchors.top: parent.top
                                anchors.margins: 10
                                Text { anchors.centerIn: parent; text: "\u2713"; color: "#000000"; font.pixelSize: 14; font.bold: true }
                            }

                            Column {
                                id: hsrColumn
                                anchors.centerIn: parent
                                spacing: 15

                                Rectangle {
                                    width: 80; height: 80; radius: 40
                                    color: "#3f9ec3"
                                    anchors.horizontalCenter: parent.horizontalCenter
                                    Text { anchors.centerIn: parent; text: "HSR"; color: "#000000"; font.family: "Stretch Pro"; font.pixelSize: 22 }
                                }

                                Text {
                                    text: "Honkai Star Rail"
                                    color: "#ffffff"; font.family: "Audiowide"; font.pixelSize: 16
                                    width: 160; wrapMode: Text.WordWrap
                                    horizontalAlignment: Text.AlignHCenter
                                    anchors.horizontalCenter: parent.horizontalCenter
                                }
                            }

                            MouseArea {
                                id: hsrMouseArea
                                anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                                onClicked: parent.parent.parent.toggleGame("hsr")
                            }
                        }
                    }
                }

                // Page 2: Mode selection
                Item {
                    Row {
                        anchors.centerIn: parent
                        spacing: 30

                        Rectangle {
                            width: 250
                            height: Math.max(280, installColumn.implicitHeight + 40)
                            color: installMouseArea.containsMouse ? "#2a2a2a" : "#1a1a1a"
                            radius: 15
                            border.color: installMouseArea.containsMouse ? Theme.primaryAccent : "#3c3d3f"
                            border.width: 2
                            scale: installMouseArea.pressed ? 0.97 : (installMouseArea.containsMouse ? 1.03 : 1.0)
                            Behavior on scale { NumberAnimation { duration: Theme.animationDuration } }
                            Behavior on color { ColorAnimation { duration: Theme.animationDuration } }
                            Behavior on border.color { ColorAnimation { duration: Theme.animationDuration } }

                            Column {
                                id: installColumn
                                anchors.centerIn: parent
                                spacing: 15

                                Image {
                                    source: "../assets/" + assetsDir + "/MiyabiMelon.png"
                                    width: 120
                                    height: 120
                                    fillMode: Image.PreserveAspectFit
                                    mipmap: true
                                    anchors.horizontalCenter: parent.horizontalCenter
                                }

                                Text {
                                    text: qsTranslate("Application", "Mod Manager")
                                    color: "#ffffff"
                                    font.family: "Audiowide"
                                    font.pixelSize: 22
                                    anchors.horizontalCenter: parent.horizontalCenter
                                    width: 220
                                    wrapMode: Text.WordWrap
                                    horizontalAlignment: Text.AlignHCenter
                                }

                                Text {
                                    text: qsTranslate("Application", "Download and install\n%1 mod packages").replace("%1", modFileExt)
                                    color: "#888888"
                                    font.family: "Alatsi"
                                    font.pixelSize: 14
                                    horizontalAlignment: Text.AlignHCenter
                                    anchors.horizontalCenter: parent.horizontalCenter
                                    width: 220
                                    wrapMode: Text.WordWrap
                                }
                            }

                            MouseArea {
                                id: installMouseArea
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: {
                                    selectedMode = "install"
                                    currentPage = 3
                                }
                            }
                        }

                        Rectangle {
                            width: 250
                            height: Math.max(280, makerColumn.implicitHeight + 40)
                            color: makerMouseArea.containsMouse ? "#2a2a2a" : "#1a1a1a"
                            radius: 15
                            border.color: makerMouseArea.containsMouse ? Theme.primaryAccent : "#3c3d3f"
                            border.width: 2
                            scale: makerMouseArea.pressed ? 0.97 : (makerMouseArea.containsMouse ? 1.03 : 1.0)
                            Behavior on scale { NumberAnimation { duration: Theme.animationDuration } }
                            Behavior on color { ColorAnimation { duration: Theme.animationDuration } }
                            Behavior on border.color { ColorAnimation { duration: Theme.animationDuration } }

                            Column {
                                id: makerColumn
                                anchors.centerIn: parent
                                spacing: 15

                                Image {
                                    source: "../assets/" + assetsDir + "/SunnaSmug.png"
                                    width: 120
                                    height: 120
                                    fillMode: Image.PreserveAspectFit
                                    mipmap: true
                                    anchors.horizontalCenter: parent.horizontalCenter
                                }

                                Text {
                                    text: qsTranslate("Application", "Mod Creator")
                                    color: "#ffffff"
                                    font.family: "Audiowide"
                                    font.pixelSize: 22
                                    anchors.horizontalCenter: parent.horizontalCenter
                                    width: 220
                                    wrapMode: Text.WordWrap
                                    horizontalAlignment: Text.AlignHCenter
                                }

                                Text {
                                    text: qsTranslate("Application", "Create and export your\nown %1 mod packages").replace("%1", modFileExt)
                                    color: "#888888"
                                    font.family: "Alatsi"
                                    font.pixelSize: 14
                                    horizontalAlignment: Text.AlignHCenter
                                    anchors.horizontalCenter: parent.horizontalCenter
                                    width: 220
                                    wrapMode: Text.WordWrap
                                }
                            }

                            MouseArea {
                                id: makerMouseArea
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: {
                                    selectedMode = "maker"
                                    currentPage = 3
                                }
                            }
                        }
                    }
                }

                Item {
                    Column {
                        anchors.centerIn: parent
                        width: parent.width
                        spacing: 20

                        Rectangle {
                            width: parent.width
                            height: gameDirColumn.height + 40
                            color: "#1a1a1a"
                            radius: 15
                            border.color: "#3c3d3f"
                            border.width: 1

                            Column {
                                id: gameDirColumn
                                anchors.left: parent.left
                                anchors.right: parent.right
                                anchors.top: parent.top
                                anchors.margins: 20
                                spacing: 15

                                Text {
                                    text: selectedGames.length > 1 ?
                                        (currentGameDisplayName || qsTranslate("Application", "Game Directory")) + "  (" + (gameSetupIndex + 1) + "/" + selectedGames.length + ")" :
                                        qsTranslate("Application", "Game Directory")
                                    color: Theme.primaryAccent
                                    font.family: "Audiowide"
                                    font.pixelSize: 20
                                }

                                Text {
                                    text: qsTranslate("Application", "Select the %1 folder from your game installation.").replace("%1", gameDataFolderName)
                                    color: "#888888"
                                    font.family: "Alatsi"
                                    font.pixelSize: 14
                                    wrapMode: Text.WordWrap
                                    width: parent.width
                                }

                                Row {
                                    width: parent.width
                                    spacing: 10

                                    Rectangle {
                                        width: parent.width - browseBtnWelcome.width - autoDetectBtnWelcome.width - 20
                                        height: 45
                                        color: "#252525"
                                        radius: 10
                                        border.color: "#555555"
                                        border.width: 1

                                        TextInput {
                                            id: gameDirInputWelcome
                                            anchors.fill: parent
                                            anchors.margins: 12
                                            color: "#ffffff"
                                            font.family: "Alatsi"
                                            font.pixelSize: 14
                                            verticalAlignment: Text.AlignVCenter
                                            clip: true
                                            text: gameDirectory

                                            onTextChanged: {
                                                gameDirectory = text
                                            }

                                            Text {
                                                anchors.fill: parent
                                                verticalAlignment: Text.AlignVCenter
                                                text: qsTranslate("Application", "Path to %1 folder...").replace("%1", gameDataFolderName)
                                                color: "#555555"
                                                font.family: "Alatsi"
                                                font.pixelSize: 14
                                                visible: gameDirInputWelcome.text.length === 0
                                            }
                                        }
                                    }

                                    Rectangle {
                                        id: browseBtnWelcome
                                        width: 100
                                        height: 45
                                        color: browseMouse.pressed ? Theme.accentDark : (browseMouse.containsMouse ? Theme.accentLight : Theme.primaryAccent)
                                        radius: Theme.radiusMedium
                                        scale: browseMouse.pressed ? 0.97 : (browseMouse.containsMouse ? 1.03 : 1.0)
                                        Behavior on scale { NumberAnimation { duration: Theme.animationDuration } }
                                        Behavior on color { ColorAnimation { duration: Theme.animationDuration } }

                                        Text {
                                            anchors.centerIn: parent
                                            text: qsTranslate("Application", "Browse")
                                            color: Theme.textOnAccent
                                            font.family: Theme.fontFamily
                                            font.pixelSize: Theme.fontSizeMedium
                                        }

                                        MouseArea {
                                            id: browseMouse
                                            anchors.fill: parent
                                            hoverEnabled: true
                                            cursorShape: Qt.PointingHandCursor
                                            onClicked: {
                                                console.log("[WelcomeDialog] Browse button clicked")
                                                browseGameDirClicked()
                                            }
                                        }
                                    }

                                    Rectangle {
                                        id: autoDetectBtnWelcome
                                        width: 145
                                        height: 45
                                        color: root.isAutoDetecting ? "#888888" : (autoDetectMouse.pressed ? Theme.accentDark : (autoDetectMouse.containsMouse ? Theme.accentLight : Theme.primaryAccent))
                                        radius: Theme.radiusMedium
                                        scale: autoDetectMouse.pressed ? 0.97 : (autoDetectMouse.containsMouse ? 1.03 : 1.0)
                                        opacity: root.isAutoDetecting ? 0.7 : 1.0
                                        Behavior on scale { NumberAnimation { duration: Theme.animationDuration } }
                                        Behavior on color { ColorAnimation { duration: Theme.animationDuration } }
                                        Behavior on opacity { NumberAnimation { duration: Theme.animationDuration } }

                                        Row {
                                            anchors.centerIn: parent
                                            spacing: 8

                                            Item {
                                                width: 16
                                                height: 16
                                                anchors.verticalCenter: parent.verticalCenter
                                                visible: root.isAutoDetecting

                                                RotationAnimation on rotation {
                                                    from: 0
                                                    to: 360
                                                    duration: 1000
                                                    loops: Animation.Infinite
                                                    running: root.isAutoDetecting
                                                }

                                                Canvas {
                                                    id: welcomeAutoDetectSpinnerCanvas
                                                    anchors.fill: parent
                                                    onPaint: {
                                                        var ctx = getContext("2d");
                                                        ctx.reset();
                                                        ctx.beginPath();
                                                        ctx.arc(8, 8, 6, 0, Math.PI * 1.5);
                                                        ctx.strokeStyle = Theme.accentDark;
                                                        ctx.lineWidth = 2;
                                                        ctx.stroke();
                                                    }

                                                    Connections {
                                                        target: uiTheme
                                                        function onThemeChanged() { welcomeAutoDetectSpinnerCanvas.requestPaint() }
                                                    }
                                                }
                                            }

                                            Text {
                                                anchors.verticalCenter: parent.verticalCenter
                                                text: root.isAutoDetecting ? qsTranslate("Application", "Searching...") : qsTranslate("Application", "Auto-Detect")
                                                color: Theme.textOnAccent
                                                font.family: Theme.fontFamily
                                                font.pixelSize: Theme.fontSizeMedium
                                            }
                                        }

                                        MouseArea {
                                            id: autoDetectMouse
                                            anchors.fill: parent
                                            hoverEnabled: !root.isAutoDetecting
                                            cursorShape: root.isAutoDetecting ? Qt.ArrowCursor : Qt.PointingHandCursor
                                            onClicked: {
                                                if (!root.isAutoDetecting) {
                                                    console.log("[WelcomeDialog] Auto-detect button clicked")
                                                    autoDetectClicked()
                                                }
                                            }
                                        }
                                    }
                                }

                                Text {
                                    text: gameDirectory.length > 0 ? qsTranslate("Application", "✓ Game directory set") : qsTranslate("Application", "⚠ No game directory configured")
                                    color: gameDirectory.length > 0 ? Theme.accentDark : "#e91a1a"
                                    font.family: "Alatsi"
                                    font.pixelSize: 13
                                }
                            }
                        }

                        Text {
                            text: qsTranslate("Application", "You can configure this later from the Settings page")
                            color: "#666666"
                            font.family: "Alatsi"
                            font.pixelSize: 12
                            font.italic: true
                            width: parent.width
                            horizontalAlignment: Text.AlignHCenter
                        }
                    }
                }

                Item {
                    Column {
                        anchors.centerIn: parent
                        width: parent.width
                        spacing: 20

                        Rectangle {
                            width: parent.width
                            height: wwiseColumn.height + 40
                            color: "#1a1a1a"
                            radius: 15
                            border.color: "#3c3d3f"
                            border.width: 1

                            Column {
                                id: wwiseColumn
                                anchors.left: parent.left
                                anchors.right: parent.right
                                anchors.top: parent.top
                                anchors.margins: 20
                                spacing: 15

                                Text {
                                    text: qsTranslate("Application", "Wwise Setup")
                                    color: Theme.primaryAccent
                                    font.family: "Audiowide"
                                    font.pixelSize: 20
                                }

                                Text {
                                    text: qsTranslate("Application", "Wwise is required to convert audio files for %1.").replace("%1", gameName)
                                    color: "#888888"
                                    font.family: "Alatsi"
                                    font.pixelSize: 14
                                    wrapMode: Text.WordWrap
                                    width: parent.width
                                }

                                Row {
                                    spacing: 10
                                    width: parent.width

                                    Text {
                                        text: qsTranslate("Application", "Status:")
                                        color: "#ffffff"
                                        font.family: "Alatsi"
                                        font.pixelSize: 16
                                    }

                                    Text {
                                        text: wwiseInstalled ? qsTranslate("Application", "INSTALLED ✓") : qsTranslate("Application", "NOT INSTALLED")
                                        color: wwiseInstalled ? Theme.accentDark : "#e91a1a"
                                        font.family: "Alatsi"
                                        font.pixelSize: 16
                                        font.bold: false
                                    }

                                    Item { width: 1; height: 1; Layout.fillWidth: true }

                                    Rectangle {
                                        width: 100
                                        height: 36
                                        color: checkBtnMouse.pressed ? "#444444" : (checkBtnMouse.containsMouse ? "#666666" : "#555555")
                                        radius: 20
                                        visible: !isInstallingWwise
                                        Behavior on color { ColorAnimation { duration: Theme.animationDuration } }

                                        Text {
                                            anchors.centerIn: parent
                                            text: qsTranslate("Application", "Check")
                                            color: "#ffffff"
                                            font.family: "Alatsi"
                                            font.pixelSize: 14
                                        }

                                        MouseArea {
                                            id: checkBtnMouse
                                            anchors.fill: parent
                                            hoverEnabled: true
                                            cursorShape: Qt.PointingHandCursor
                                            onClicked: checkWwiseClicked()
                                        }
                                    }
                                }

                                Rectangle {
                                    width: parent.width
                                    height: 50
                                    color: wwiseInstalled ? "#3c3d3f" : (setupBtnMouse.pressed ? Theme.accentDark : setupBtnMouse.containsMouse ? Theme.accentLight : Theme.primaryAccent)
                                    radius: 10
                                    opacity: (wwiseInstalled || isInstallingWwise) ? 0.5 : 1.0
                                    visible: !wwiseInstalled || isInstallingWwise
                                    Behavior on color { ColorAnimation { duration: 100 } }
                                    Behavior on opacity { NumberAnimation { duration: 150 } }

                                    Row {
                                        anchors.centerIn: parent
                                        spacing: 10

                                        Item {
                                            width: 20
                                            height: 20
                                            visible: isInstallingWwise

                                            RotationAnimation on rotation {
                                                from: 0
                                                to: 360
                                                duration: 1000
                                                loops: Animation.Infinite
                                                running: isInstallingWwise
                                            }

                                            Canvas {
                                                id: welcomeWwiseSpinnerCanvas
                                                anchors.fill: parent
                                                onPaint: {
                                                    var ctx = getContext("2d");
                                                    ctx.reset();
                                                    ctx.beginPath();
                                                    ctx.arc(10, 10, 7, 0, Math.PI * 1.5);
                                                    ctx.strokeStyle = Theme.accentDark;
                                                    ctx.lineWidth = 2.5;
                                                    ctx.stroke();
                                                }

                                                Connections {
                                                    target: uiTheme
                                                    function onThemeChanged() { welcomeWwiseSpinnerCanvas.requestPaint() }
                                                }
                                            }
                                        }

                                        Text {
                                            text: isInstallingWwise ? qsTranslate("Application", "Installing...") : qsTranslate("Application", "Run Automated Setup")
                                            color: "#000000"
                                            font.family: "Alatsi"
                                            font.pixelSize: 16
                                            font.bold: false
                                        }
                                    }

                                    MouseArea {
                                        id: setupBtnMouse
                                        anchors.fill: parent
                                        hoverEnabled: !wwiseInstalled && !isInstallingWwise
                                        cursorShape: (wwiseInstalled || isInstallingWwise) ? Qt.ArrowCursor : Qt.PointingHandCursor
                                        onClicked: {
                                            if (!wwiseInstalled && !isInstallingWwise) {
                                                isInstallingWwise = true
                                                runWwiseSetupClicked()
                                            }
                                        }
                                    }
                                }
                            }
                        }

                        Text {
                            text: wwiseInstalled ?
                                  qsTranslate("Application", "Wwise is installed and ready! You can start creating mods.") :
                                  qsTranslate("Application", "You can install Wwise later from the Settings page")
                            color: "#666666"
                            font.family: "Alatsi"
                            font.pixelSize: 12
                            font.italic: true
                            width: parent.width
                            horizontalAlignment: Text.AlignHCenter
                        }
                    }
                }

                Item {
                    Column {
                        anchors.centerIn: parent
                        width: parent.width
                        spacing: 20

                        Rectangle {
                            width: parent.width
                            height: audioToolsColumn.height + 40
                            color: "#1a1a1a"
                            radius: 15
                            border.color: "#3c3d3f"
                            border.width: 1

                            Column {
                                id: audioToolsColumn
                                anchors.left: parent.left
                                anchors.right: parent.right
                                anchors.top: parent.top
                                anchors.margins: 20
                                spacing: 15

                                Text {
                                    text: qsTranslate("Application", "Windows Audio Tools")
                                    color: Theme.primaryAccent
                                    font.family: "Audiowide"
                                    font.pixelSize: 20
                                }

                                Text {
                                    text: qsTranslate("Application", "FFmpeg and vgmstream are required to convert audio files.")
                                    color: "#888888"
                                    font.family: "Alatsi"
                                    font.pixelSize: 14
                                    wrapMode: Text.WordWrap
                                    width: parent.width
                                }

                                Row {
                                    spacing: 10
                                    width: parent.width

                                    Text {
                                        text: qsTranslate("Application", "Status:")
                                        color: "#ffffff"
                                        font.family: "Alatsi"
                                        font.pixelSize: 16
                                    }

                                    Text {
                                        text: audioToolsInstalled ? qsTranslate("Application", "INSTALLED ✓") : qsTranslate("Application", "NOT INSTALLED")
                                        color: audioToolsInstalled ? Theme.accentDark : "#e91a1a"
                                        font.family: "Alatsi"
                                        font.pixelSize: 16
                                        font.bold: false
                                    }

                                    Item { width: 1; height: 1; Layout.fillWidth: true }

                                    Rectangle {
                                        width: 100
                                        height: 36
                                        color: checkAudioToolsBtnMouse.pressed ? "#444444" : (checkAudioToolsBtnMouse.containsMouse ? "#666666" : "#555555")
                                        radius: 20
                                        visible: !isInstallingAudioTools
                                        Behavior on color { ColorAnimation { duration: Theme.animationDuration } }

                                        Text {
                                            anchors.centerIn: parent
                                            text: qsTranslate("Application", "Check")
                                            color: "#ffffff"
                                            font.family: "Alatsi"
                                            font.pixelSize: 14
                                        }

                                        MouseArea {
                                            id: checkAudioToolsBtnMouse
                                            anchors.fill: parent
                                            hoverEnabled: true
                                            cursorShape: Qt.PointingHandCursor
                                            onClicked: checkAudioToolsClicked()
                                        }
                                    }
                                }

                                Rectangle {
                                    width: parent.width
                                    height: 50
                                    color: audioToolsInstalled ? "#3c3d3f" : (audioToolsSetupBtnMouse.pressed ? Theme.accentDark : audioToolsSetupBtnMouse.containsMouse ? Theme.accentLight : Theme.primaryAccent)
                                    radius: 10
                                    opacity: (audioToolsInstalled || isInstallingAudioTools) ? 0.5 : 1.0
                                    visible: !audioToolsInstalled || isInstallingAudioTools
                                    Behavior on color { ColorAnimation { duration: 100 } }
                                    Behavior on opacity { NumberAnimation { duration: 150 } }

                                    Row {
                                        anchors.centerIn: parent
                                        spacing: 10

                                        Item {
                                            width: 20
                                            height: 20
                                            visible: isInstallingAudioTools

                                            RotationAnimation on rotation {
                                                from: 0
                                                to: 360
                                                duration: 1000
                                                loops: Animation.Infinite
                                                running: isInstallingAudioTools
                                            }

                                            Canvas {
                                                id: welcomeAudioToolsSpinnerCanvas
                                                anchors.fill: parent
                                                onPaint: {
                                                    var ctx = getContext("2d");
                                                    ctx.reset();
                                                    ctx.beginPath();
                                                    ctx.arc(10, 10, 7, 0, Math.PI * 1.5);
                                                    ctx.strokeStyle = Theme.accentDark;
                                                    ctx.lineWidth = 2.5;
                                                    ctx.stroke();
                                                }

                                                Connections {
                                                    target: uiTheme
                                                    function onThemeChanged() { welcomeAudioToolsSpinnerCanvas.requestPaint() }
                                                }
                                            }
                                        }

                                        Text {
                                            text: isInstallingAudioTools ? qsTranslate("Application", "Installing...") : qsTranslate("Application", "Install Audio Tools")
                                            color: "#000000"
                                            font.family: "Alatsi"
                                            font.pixelSize: 16
                                            font.bold: false
                                        }
                                    }

                                    MouseArea {
                                        id: audioToolsSetupBtnMouse
                                        anchors.fill: parent
                                        hoverEnabled: !audioToolsInstalled && !isInstallingAudioTools
                                        cursorShape: (audioToolsInstalled || isInstallingAudioTools) ? Qt.ArrowCursor : Qt.PointingHandCursor
                                        onClicked: {
                                            if (!audioToolsInstalled && !isInstallingAudioTools) {
                                                isInstallingAudioTools = true
                                                runAudioToolsSetupClicked()
                                            }
                                        }
                                    }
                                }
                            }
                        }

                        Text {
                            text: audioToolsInstalled ?
                                  qsTranslate("Application", "Audio tools are installed! You can now convert audio files.") :
                                  qsTranslate("Application", "You can install these tools later from the Settings page")
                            color: "#666666"
                            font.family: "Alatsi"
                            font.pixelSize: 12
                            font.italic: true
                            width: parent.width
                            horizontalAlignment: Text.AlignHCenter
                        }
                    }
                }

                Item {
                    Column {
                        anchors.centerIn: parent
                        spacing: 5
                        width: parent.width

                        Image {
                            source: "../assets/" + assetsDir + "/BurniceYay.png"
                            width: 240
                            height: 240
                            fillMode: Image.PreserveAspectFit
                            mipmap: true
                            anchors.horizontalCenter: parent.horizontalCenter

                        }

                        Text {
                            text: qsTranslate("Application", "You're all set!")
                            color: Theme.primaryAccent
                            font.family: "Audiowide"
                            font.pixelSize: 32
                            anchors.horizontalCenter: parent.horizontalCenter
                        }

                        Text {
                            text: selectedMode === "maker" ?
                                qsTranslate("Application", "%1 is configured for mod creation. Go make something!!").replace("%1", appName) :
                                qsTranslate("Application", "%1 is ready to manage some mods. Install something!").replace("%1", appName)
                            color: "#aaaaaa"
                            font.family: "Alatsi"
                            font.pixelSize: 16
                            horizontalAlignment: Text.AlignHCenter
                            width: parent.width * 0.8
                            anchors.horizontalCenter: parent.horizontalCenter
                        }
                    }
                }
            }

            Item { height: 10; width: 1 }

            Row {
                anchors.horizontalCenter: parent.horizontalCenter
                spacing: 15

                Rectangle {
                    visible: currentPage > 1
                    width: 120
                    height: visible ? 50 : 0
                    radius: Theme.radiusMedium
                    color: backMouse.containsMouse ? "#333333" : Theme.surfaceColor
                    scale: backMouse.pressed ? 0.97 : (backMouse.containsMouse ? 1.03 : 1.0)
                    Behavior on scale { NumberAnimation { duration: Theme.animationDuration } }
                    Behavior on color { ColorAnimation { duration: Theme.animationDuration } }

                    Text {
                        anchors.centerIn: parent
                        text: qsTranslate("Application", "< Back")
                        color: Theme.textPrimary
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeMedium
                    }

                    MouseArea {
                        id: backMouse
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: {
                            // Page 3 with multi-game: go back to previous game or to mode page
                            if (currentPage === 3) {
                                var dirs = gameDirectories
                                dirs[selectedGames[gameSetupIndex]] = gameDirectory
                                gameDirectories = dirs

                                if (gameSetupIndex > 0) {
                                    gameSetupIndex--
                                    var prevGame = selectedGames[gameSetupIndex]
                                    selectedGame = prevGame
                                    gameSelected(prevGame)
                                    setGameDirectory(gameDirectories[prevGame] || "")
                                    return
                                }
                                currentPage = 2
                            } else if (selectedMode === "install" && currentPage === 6) {
                                // Back to last game's directory page
                                gameSetupIndex = selectedGames.length - 1
                                var lastGame = selectedGames[gameSetupIndex]
                                selectedGame = lastGame
                                gameSelected(lastGame)
                                setGameDirectory(gameDirectories[lastGame] || "")
                                currentPage = 3
                            } else if (selectedMode === "maker" && currentPage === 6 && Qt.platform.os !== "windows") {
                                currentPage = 4
                            } else {
                                currentPage = currentPage - 1
                            }
                        }
                    }
                }

                Rectangle {
                    property bool canContinue: {
                        if (currentPage === 1) return selectedGames.length > 0
                        if (currentPage === 2) return selectedMode !== ""
                        return true
                    }
                    width: 150
                    height: 50
                    radius: Theme.radiusMedium
                    opacity: canContinue ? 1.0 : 0.4
                    color: !canContinue ? "#555555" : continueMouse.pressed ? Theme.accentDark : (continueMouse.containsMouse ? Theme.accentLight : Theme.primaryAccent)
                    scale: continueMouse.pressed && canContinue ? 0.97 : (continueMouse.containsMouse && canContinue ? 1.03 : 1.0)
                    Behavior on scale { NumberAnimation { duration: Theme.animationDuration } }
                    Behavior on color { ColorAnimation { duration: Theme.animationDuration } }
                    Behavior on opacity { NumberAnimation { duration: Theme.animationDuration } }

                    Text {
                        anchors.centerIn: parent
                        text: currentPage === 6 ? qsTranslate("Application", "Start Tutorial") : qsTranslate("Application", "Continue >")
                        color: parent.canContinue ? Theme.textOnAccent : "#999999"
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeMedium
                    }

                    MouseArea {
                        id: continueMouse
                        anchors.fill: parent
                        hoverEnabled: parent.canContinue
                        cursorShape: parent.canContinue ? Qt.PointingHandCursor : Qt.ArrowCursor
                        onClicked: {
                            if (!parent.canContinue) return

                            // Page 1: Game selection → Mode selection
                            if (currentPage === 1) {
                                selectedGame = selectedGames[0]
                                gameSelected(selectedGames[0])
                                gameSetupIndex = 0
                                currentPage = 2
                                return
                            }

                            // Page 3: Game directory — cycle through selected games
                            if (currentPage === 3) {
                                // Save current game's directory
                                var dirs = gameDirectories
                                var curGame = selectedGames[gameSetupIndex]
                                dirs[curGame] = gameDirectory
                                gameDirectories = dirs

                                if (gameSetupIndex < selectedGames.length - 1) {
                                    // Next game
                                    gameSetupIndex++
                                    var nextGame = selectedGames[gameSetupIndex]
                                    selectedGame = nextGame
                                    gameSelected(nextGame)
                                    setGameDirectory(gameDirectories[nextGame] || "")
                                    return
                                }

                                // All games done — advance
                                if (selectedMode === "install") {
                                    currentPage = 6
                                } else {
                                    currentPage = 4
                                    checkWwiseClicked()
                                }
                                return
                            }

                            if (selectedMode === "install") {
                                if (currentPage === 6) {
                                    startTutorialClicked()
                                    modeSelected(selectedMode)
                                    hide()
                                }
                            } else if (selectedMode === "maker") {
                                if (currentPage === 4) {
                                    if (Qt.platform.os === "windows") {
                                        currentPage = 5
                                        checkAudioToolsClicked()
                                    } else {
                                        currentPage = 6
                                    }
                                } else if (currentPage === 5) {
                                    currentPage = 6
                                } else if (currentPage === 6) {
                                    startTutorialClicked()
                                    modeSelected(selectedMode)
                                    hide()
                                }
                            }
                        }
                    }
                }
            }

            Text {
                text: qsTranslate("Application", "Skip tutorial")
                color: skipTutorialMouse.containsMouse ? Theme.primaryAccent : "#888888"
                font.family: "Alatsi"
                font.pixelSize: 13
                width: parent.width
                horizontalAlignment: Text.AlignHCenter
                visible: false
                Behavior on color { ColorAnimation { duration: 100 } }

                MouseArea {
                    id: skipTutorialMouse
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: {
                        modeSelected(selectedMode)
                        hide()
                    }
                }
            }

            Item {
                width: parent.width
                height: 30
                visible: currentPage === 1

                Text {
                    text: qsTranslate("Application", "You can always change this later in settings")
                    color: "#666666"
                    font.family: "Alatsi"
                    font.pixelSize: 12
                    font.italic: true
                    anchors.centerIn: parent
                }

                Row {
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 6

                    ComboBox {
                        id: welcomeLanguageCombo
                        width: 120
                        height: 28
                        model: translationManager ? translationManager.availableLanguages : []
                        textRole: "name"

                        currentIndex: {
                            if (!translationManager) return 0
                            var langs = translationManager.availableLanguages
                            for (var i = 0; i < langs.length; i++) {
                                if (langs[i].code === translationManager.currentLanguage) return i
                            }
                            return 0
                        }

                        onActivated: {
                            var selectedLang = translationManager.availableLanguages[index]
                            welcomeLanguageChanged(selectedLang.code)
                        }

                        background: Rectangle {
                            HoverHandler { id: welcomeLangBgHover }
                            color: welcomeLanguageCombo.pressed ? Qt.darker("#333333", 1.2)
                                 : welcomeLangBgHover.hovered ? Qt.lighter("#333333", 1.1)
                                 : "#333333"
                            radius: 6
                            border.color: "#555555"
                            border.width: 1
                            Behavior on color { ColorAnimation { duration: 150 } }
                        }

                        contentItem: Text {
                            text: welcomeLanguageCombo.displayText
                            color: "#cccccc"
                            font.family: "Alatsi"
                            font.pixelSize: 12
                            verticalAlignment: Text.AlignVCenter
                            leftPadding: 8
                            rightPadding: 24
                        }

                        indicator: Rectangle {
                            x: welcomeLanguageCombo.width - width - 6
                            y: (welcomeLanguageCombo.height - height) / 2
                            width: 16
                            height: 16
                            color: "transparent"

                            Text {
                                anchors.centerIn: parent
                                text: "\u25BC"
                                color: "#888888"
                                font.pixelSize: 8
                            }
                        }

                        delegate: ItemDelegate {
                            id: welcomeLangDelegate
                            width: welcomeLanguageCombo.width - 8
                            height: 30

                            HoverHandler { id: welcomeLangDelegateHover }

                            background: Rectangle {
                                color: {
                                    if (welcomeLangDelegate.highlighted) return Theme.primaryAccent
                                    if (welcomeLangDelegateHover.hovered) return Qt.lighter("#1a1a1a", 1.3)
                                    return "#1a1a1a"
                                }
                                radius: 4
                                Behavior on color { ColorAnimation { duration: 100 } }
                            }

                            contentItem: Text {
                                text: modelData.name
                                color: welcomeLangDelegate.highlighted ? Theme.textOnAccent : "#cccccc"
                                font.family: "Alatsi"
                                font.pixelSize: 12
                                verticalAlignment: Text.AlignVCenter
                                leftPadding: 8
                            }
                        }

                        popup: Popup {
                            y: -contentItem.implicitHeight - 4
                            width: welcomeLanguageCombo.width
                            padding: 4

                            background: Rectangle {
                                color: "#1a1a1a"
                                radius: 6
                                border.color: "#555555"
                                border.width: 1
                            }

                            contentItem: ListView {
                                implicitHeight: contentHeight
                                model: welcomeLanguageCombo.popup.visible ? welcomeLanguageCombo.delegateModel : null
                                clip: true
                            }
                        }
                    }
                }
            }
        }
    }

    function show() {
        visible = true
        currentPage = 1
        selectedMode = ""
        selectedGame = ""
        selectedGames = []
        gameSetupIndex = 0
        gameDirectories = ({})
        gameDirectory = ""
        currentGameDisplayName = ""
    }

    function hide() {
        closing = true
        hideTimer.start()
    }

    function setGameDirectory(path) {
        gameDirectory = path
        if (gameDirInputWelcome) {
            gameDirInputWelcome.text = path
        }
    }
}
