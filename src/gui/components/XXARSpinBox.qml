import QtQuick 2.15
import QtQuick.Controls 2.15

// A SpinBox that locks itself while a game-file write runs, unless allowDuringWrite is set.
SpinBox {
    id: control

    property bool allowDuringWrite: false
    readonly property bool writeLocked: !allowDuringWrite && gameWriteState.busy

    opacity: writeLocked ? 0.55 : 1.0
    Keys.onPressed: (event) => { event.accepted = control.writeLocked }

    WriteLock { active: control.writeLocked }

    // An editable SpinBox types into its contentItem, which the Keys handler above never sees.
    Binding {
        target: control.contentItem
        property: "readOnly"
        value: true
        when: control.writeLocked && control.editable
    }
}
