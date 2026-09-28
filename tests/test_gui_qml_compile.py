from pathlib import Path

import pytest

pytestmark = pytest.mark.gui

GUI_DIR = Path(__file__).resolve().parent.parent / "src" / "gui"
QML_FILES = sorted([*(GUI_DIR / "qml").glob("*.qml"), *(GUI_DIR / "components").glob("*.qml")])


@pytest.fixture(scope="module")
def qml_engine(qapp):
    from PyQt6.QtQml import QQmlEngine

    engine = QQmlEngine()
    engine.addImportPath(str(GUI_DIR / "qml"))
    engine.addImportPath(str(GUI_DIR / "components"))
    yield engine
    engine.clearComponentCache()


def test_every_qml_file_is_collected():
    assert len(QML_FILES) >= 30
    assert GUI_DIR / "qml" / "MainWindow.qml" in QML_FILES


@pytest.mark.parametrize("qml_file", QML_FILES, ids=[f"{path.parent.name}/{path.name}" for path in QML_FILES])
def test_qml_file_compiles(qml_engine, qml_file):
    from PyQt6.QtCore import QUrl
    from PyQt6.QtQml import QQmlComponent

    component = QQmlComponent(qml_engine, QUrl.fromLocalFile(str(qml_file)))

    assert [error.toString() for error in component.errors()] == []
    assert component.status() == QQmlComponent.Status.Ready
