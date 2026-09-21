import QtQuick 2.15

// A MouseArea that locks itself while a game-file write runs, unless allowDuringWrite is set.
// The lock is a WriteLock child rather than enabled, so an instance's own enabled binding cannot drop it.
MouseArea {
    id: area

    property bool allowDuringWrite: false
    property bool dimParentWhileLocked: true
    readonly property bool writeLocked: !allowDuringWrite && gameWriteState.busy

    WriteLock { active: area.writeLocked }

    Binding {
        target: area.parent
        property: "opacity"
        value: 0.55
        when: area.writeLocked && area.dimParentWhileLocked
    }
}
