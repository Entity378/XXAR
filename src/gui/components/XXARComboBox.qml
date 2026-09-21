import QtQuick 2.15
import QtQuick.Controls 2.15

// A ComboBox that locks itself while a game-file write runs, unless allowDuringWrite is set.
ComboBox {
    id: control

    property bool allowDuringWrite: false
    readonly property bool writeLocked: !allowDuringWrite && gameWriteState.busy

    opacity: writeLocked ? 0.55 : 1.0
    onWriteLockedChanged: if (writeLocked) popup.close()
    Keys.onPressed: (event) => { event.accepted = control.writeLocked }

    WriteLock { active: control.writeLocked }
}
