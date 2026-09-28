import xml.etree.ElementTree as ElementTree
from pathlib import Path

import pytest
from PyQt6.QtCore import QCoreApplication, QTranslator

from src.gui.translation_manager import TranslationManager

TRANSLATIONS_DIR = Path(__file__).resolve().parent.parent / "src" / "gui" / "translations"
SUPPORTED_CODES = [language["code"] for language in TranslationManager.SUPPORTED_LANGUAGES]


def parse_ts(language_code):
    return ElementTree.parse(TRANSLATIONS_DIR / f"zzar_{language_code}.ts").getroot()


def iter_messages(ts_root):
    for context in ts_root.iter("context"):
        context_name = context.findtext("name")
        for message in context.iter("message"):
            yield context_name, message


def test_supported_languages_are_unique_and_start_with_english():
    assert SUPPORTED_CODES[0] == "en"
    assert len(set(SUPPORTED_CODES)) == len(SUPPORTED_CODES)
    assert all(language["name"] for language in TranslationManager.SUPPORTED_LANGUAGES)


@pytest.mark.parametrize("language_code", SUPPORTED_CODES)
def test_every_supported_language_ships_source_and_compiled_files(language_code):
    assert (TRANSLATIONS_DIR / f"zzar_{language_code}.ts").is_file()
    assert (TRANSLATIONS_DIR / f"zzar_{language_code}.qm").is_file()


def test_every_translation_file_belongs_to_a_supported_language():
    shipped_codes = {path.stem.removeprefix("zzar_") for path in TRANSLATIONS_DIR.glob("zzar_*.*") if path.suffix in (".ts", ".qm")}
    assert shipped_codes == set(SUPPORTED_CODES)


@pytest.mark.parametrize("language_code", SUPPORTED_CODES)
def test_ts_file_is_valid_qt_linguist_xml(language_code):
    ts_root = parse_ts(language_code)
    assert ts_root.tag == "TS"
    assert ts_root.get("language").split("_")[0] == language_code
    messages = list(iter_messages(ts_root))
    assert messages
    for context_name, message in messages:
        assert context_name
        assert message.findtext("source")
        assert message.find("translation") is not None


@pytest.mark.parametrize("language_code", SUPPORTED_CODES)
def test_finished_translations_are_not_empty(language_code):
    empty_finished_sources = [
        message.findtext("source")
        for _, message in iter_messages(parse_ts(language_code))
        if message.find("translation").get("type") != "unfinished" and not (message.find("translation").text or "").strip()
    ]
    assert empty_finished_sources == []


@pytest.mark.parametrize("language_code", SUPPORTED_CODES)
def test_compiled_qm_matches_its_ts_source(qapp, language_code):
    translator = QTranslator()
    assert translator.load(str(TRANSLATIONS_DIR / f"zzar_{language_code}.qm"))
    QCoreApplication.installTranslator(translator)
    try:
        stale_sources = [
            message.findtext("source")
            for context_name, message in iter_messages(parse_ts(language_code))
            if message.find("translation").get("type") != "unfinished"
            and QCoreApplication.translate(context_name, message.findtext("source")) != (message.find("translation").text or "")
        ]
    finally:
        QCoreApplication.removeTranslator(translator)
    assert stale_sources == []
