import xml.etree.ElementTree as ElementTree
from pathlib import Path

import pytest
from PyQt6.QtCore import QCoreApplication, QTranslator
from PyQt6.QtQml import QQmlComponent, QQmlEngine

from src.gui.translation_manager import TranslationManager
from helpers import record_signal

TRANSLATIONS_DIR = Path(__file__).resolve().parent.parent / "src" / "gui" / "translations"
pytestmark = pytest.mark.gui

LABEL_QML = b"""
import QtQml 2.15
QtObject { property string label: qsTranslate("Application", "Search") }
"""


def finished_messages(language_code):
    ts_root = ElementTree.parse(TRANSLATIONS_DIR / f"zzar_{language_code}.ts").getroot()
    for context in ts_root.iter("context"):
        context_name = context.findtext("name")
        for message in context.iter("message"):
            translation = message.find("translation")
            if translation.get("type") != "unfinished":
                yield context_name, message.findtext("source"), translation.text or ""


@pytest.fixture
def engine(qapp):
    qml_engine = QQmlEngine()
    yield qml_engine
    qml_engine.deleteLater()


@pytest.fixture
def translation_manager(engine):
    manager = TranslationManager(engine)
    yield manager
    QCoreApplication.removeTranslator(manager._translator)


def translated_search_label():
    return QCoreApplication.translate("Application", "Search")


def test_starts_in_english(translation_manager):
    assert translation_manager.currentLanguage == "en"
    assert translation_manager.property("currentLanguage") == "en"
    assert translation_manager.property("availableLanguages") == TranslationManager.SUPPORTED_LANGUAGES


def test_change_language_installs_the_compiled_translation(translation_manager):
    context_name, source_text, expected_translation = next(finished_messages("es"))
    language_changes = record_signal(translation_manager.languageChanged)
    translation_manager.changeLanguage("es")
    assert translation_manager.currentLanguage == "es"
    assert len(language_changes) == 1
    assert QCoreApplication.translate(context_name, source_text) == expected_translation


def test_change_language_retranslates_live_qml_bindings(engine, translation_manager):
    component = QQmlComponent(engine)
    component.setData(LABEL_QML, engine.baseUrl())
    qml_object = component.create()
    assert qml_object is not None, component.errorString()
    assert qml_object.property("label") == "Search"
    translation_manager.changeLanguage("es")
    assert qml_object.property("label") == translated_search_label()
    assert qml_object.property("label") != "Search"
    translation_manager.changeLanguage("en")
    assert qml_object.property("label") == "Search"


def test_back_to_english_removes_the_translator(translation_manager):
    translation_manager.changeLanguage("es")
    language_changes = record_signal(translation_manager.languageChanged)
    translation_manager.changeLanguage("en")
    assert translation_manager.currentLanguage == "en"
    assert len(language_changes) == 1
    assert translated_search_label() == "Search"


def test_same_language_is_a_noop(translation_manager):
    language_changes = record_signal(translation_manager.languageChanged)
    translation_manager.changeLanguage("en")
    assert language_changes == []


@pytest.mark.parametrize("unknown_code", ["xx", "", "../zzar_es"])
def test_unknown_language_is_rejected(translation_manager, unknown_code):
    language_changes = record_signal(translation_manager.languageChanged)
    translation_manager.changeLanguage(unknown_code)
    assert translation_manager.currentLanguage == "en"
    assert language_changes == []
    assert translated_search_label() == "Search"


def test_switching_between_translations_keeps_one_translator(translation_manager):
    translation_manager.changeLanguage("es")
    translation_manager.changeLanguage("ja")
    assert translation_manager.currentLanguage == "ja"
    assert translation_manager._translator.language() == "ja_JP"


def write_ts(directory, language_code, translation_attributes):
    messages = "".join(
        f"<message><source>Text {index}</source><translation{attributes}>T{index}</translation></message>"
        for index, attributes in enumerate(translation_attributes)
    )
    ts_text = f'<?xml version="1.0" encoding="utf-8"?><TS version="2.1" language="{language_code}"><context><name>Application</name>{messages}</context></TS>'
    (directory / f"zzar_{language_code}.ts").write_text(ts_text, encoding="utf-8")


def test_is_incomplete_follows_unfinished_markers(translation_manager, tmp_path):
    write_ts(tmp_path, "es", ["", ""])
    write_ts(tmp_path, "ja", ["", ' type="unfinished"'])
    translation_manager._translations_dir = tmp_path
    assert translation_manager.isIncomplete("en") is False
    assert translation_manager.isIncomplete("es") is False
    assert translation_manager.isIncomplete("ja") is True
    assert translation_manager.isIncomplete("fr") is True


def test_shipped_japanese_translation_is_flagged_incomplete(translation_manager):
    has_unfinished = 'type="unfinished"' in (TRANSLATIONS_DIR / "zzar_ja.ts").read_text(encoding="utf-8")
    assert translation_manager.isIncomplete("ja") is has_unfinished


def test_compiled_translator_file_loads_directly():
    translator = QTranslator()
    assert translator.load(str(TRANSLATIONS_DIR / "zzar_es.qm"))
    assert translator.language() == "es_ES"
