import QtQuick 2.15

// Sits on top of its parent and swallows clicks and hover while active, so a locked input cannot fire.
// Wheel events are not handled, so they still reach the list or view underneath.
MouseArea {
    property bool active: false

    anchors.fill: parent
    z: 100000
    visible: active
    hoverEnabled: true
    acceptedButtons: Qt.AllButtons
    preventStealing: true
    cursorShape: Qt.ArrowCursor
}
