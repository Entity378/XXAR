from types import SimpleNamespace

import pytest

from bridge_helpers import holding_game_lock
from helpers import build_pck, configure_game_in_settings, make_game_install, make_wem, read_settings
from src.gui.connectors import settings_connector

EN_PATCH = "Full/En/Patch.pck"
KR_SOUNDBANK = "Full/Kr/SoundBank_Kr_0.pck"
KR_STREAMED = "Full/Kr/Streamed_Kr_0.pck"


class LanguageFolderHost(settings_connector.SettingsConnector):
    # The language check and the move only need the settings and a root object to notify.

    def __init__(self, notifications):
        self.root = None
        self.notifications = notifications

    def load_settings(self):
        return read_settings()

    def on_alert_dialog_requested(self, title, message, sticker_path=""):
        self.notifications.append(("alert", title))


@pytest.fixture
def host(monkeypatch):
    notifications = []
    monkeypatch.setattr(settings_connector, "Q_ARG", lambda type_name, value: value)
    monkeypatch.setattr(settings_connector, "QMetaObject", SimpleNamespace(
        invokeMethod=lambda target, method, connection, *args: notifications.append((method, *args)),
    ))
    return LanguageFolderHost(notifications)


@pytest.fixture
def zzz_install_with_a_language_downloaded_in_game(tmp_path):
    # Kr was downloaded by the game, so it exists only in Persistent, while En comes from the launcher.
    install = make_game_install(
        tmp_path,
        "zzz",
        streaming_files={
            "Full/SoundBank_SFX_0.pck": build_pck(sounds=[(1, 0, make_wem(1))]),
            "Full/En/SoundBank_En_0.pck": build_pck(sounds=[(2, 1, make_wem(2))]),
        },
        persistent_files={
            EN_PATCH: build_pck(sounds=[(3, 1, make_wem(3))]),
            KR_SOUNDBANK: build_pck(sounds=[(4, 4, make_wem(4))]),
            KR_STREAMED: build_pck(sounds=[(5, 4, make_wem(5))]),
        },
    )
    configure_game_in_settings(install)
    return install


def test_a_language_downloaded_in_game_is_offered_for_the_move(host, zzz_install_with_a_language_downloaded_in_game):
    host.check_multiple_languages()

    (method, languages, moveable, hash_pcks), = host.notifications
    assert method == "showMultipleLanguagesWarning"
    assert set(languages.split(", ")) == {"En", "Kr"}
    assert (moveable, hash_pcks) == ("Kr", "")


def test_moving_a_language_lands_it_beside_the_launcher_languages(qapp, host, zzz_install_with_a_language_downloaded_in_game):
    install = zzz_install_with_a_language_downloaded_in_game
    kr_pcks = {rel: (install.persistent_root / rel).read_bytes() for rel in (KR_SOUNDBANK, KR_STREAMED)}

    host.on_move_language_to_streaming("Kr")

    assert {rel: (install.streaming_root / rel).read_bytes() for rel in kr_pcks} == kr_pcks
    assert not (install.persistent_root / "Full" / "Kr").exists()
    assert (install.persistent_root / EN_PATCH).exists()
    assert [method for method, *_ in host.notifications] == ["showSuccessToast", "hideLanguageWarningDialog"]


def test_no_language_moves_while_a_game_write_runs(qapp, host, zzz_install_with_a_language_downloaded_in_game):
    install = zzz_install_with_a_language_downloaded_in_game

    with holding_game_lock():
        host.on_move_language_to_streaming("Kr")

    assert (install.persistent_root / KR_SOUNDBANK).exists()
    assert not (install.streaming_root / KR_SOUNDBANK).exists()
    assert host.notifications == [("alert", "Operation In Progress")]
