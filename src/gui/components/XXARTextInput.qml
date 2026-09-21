import QtQuick 2.15

// A TextInput that locks itself while a game-file write runs, unless allowDuringWrite is set.
TextInput {
    id: control

    property bool allowDuringWrite: false
    readonly property bool writeLocked: !allowDuringWrite && gameWriteState.busy

    readOnly: writeLocked
    opacity: writeLocked ? 0.55 : 1.0

    WriteLock { active: control.writeLocked }
}
