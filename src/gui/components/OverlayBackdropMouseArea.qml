import QtQuick 2.15

// hoverEnabled + accepted wheel keep the cursor from interacting with the page underneath.
// Clicks landing on dialog are swallowed, only clicks truly outside it emit clickedOutside().
MouseArea {
    property Item dialog
    signal clickedOutside()

    anchors.fill: parent
    hoverEnabled: true
    onWheel: wheel.accepted = true
    onClicked: {
        if (dialog && dialog.contains(mapToItem(dialog, mouse.x, mouse.y)))
            return
        clickedOutside()
    }
}
