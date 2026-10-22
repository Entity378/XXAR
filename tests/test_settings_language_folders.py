import json
from types import SimpleNamespace

import pytest

from bridge_helpers import holding_game_lock
from helpers import build_pck, configure_game_in_settings, make_game_install, make_wem, read_settings
from overlay_builders import xxh64_tag
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

    (method, languages, moveable), = host.notifications
    assert method == "showMultipleLanguagesWarning"
    assert set(languages.split(", ")) == {"En", "Kr"}
    assert moveable == "Kr"


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


@pytest.fixture
def steam_install_with_english_downloaded_in_game(tmp_path):
    sfx_rel = "Full/SoundBank_SFX_0.pck"
    voice_rel = "Full/En/SoundBank_En_0.pck"
    sfx = build_pck(sounds=[(1, 0, make_wem(1))])
    voice = build_pck(sounds=[(2, 1, make_wem(2))])
    protected = {
        EN_PATCH: build_pck(sounds=[(3, 1, make_wem(3))]),
        "Full/En/Hotfix.pck": build_pck(sounds=[(4, 1, make_wem(4))]),
    }
    install = make_game_install(
        tmp_path, "zzz", streaming_files={sfx_rel: sfx},
        persistent_files={voice_rel: voice, **protected},
    )
    configure_game_in_settings(install)

    def entry(rel, content):
        return {
            "remoteName": f"Audio/Windows/{rel}", "md5": xxh64_tag(content),
            "fileSize": len(content), "isPatch": False, "tags": [3, 4],
        }

    base_catalog = {"files": [entry(sfx_rel, sfx)], "basePackages": ["Full"]}
    persist_catalog = {
        "files": [entry(voice_rel, voice), *(entry(rel, content) for rel, content in protected.items())],
        "basePackages": [],
    }
    base_path = install.data_dir / "StreamingAssets" / "audio_version"
    persist_path = install.data_dir / "Persistent" / "audio_version_persist"
    base_path.write_text(json.dumps(base_catalog, indent=2), encoding="utf-8")
    persist_path.write_text(json.dumps(persist_catalog, indent=2), encoding="utf-8")
    return SimpleNamespace(
        install=install, voice_rel=voice_rel, voice=voice, protected=protected,
        base_path=base_path, base_catalog=base_catalog, persist_path=persist_path,
        voice_entry=entry(voice_rel, voice),
    )


def test_moving_steam_voice_registers_the_verified_base_without_touching_persistent_catalog(
    qapp, host, steam_install_with_english_downloaded_in_game,
):
    env = steam_install_with_english_downloaded_in_game
    persistent_catalog_before = env.persist_path.read_bytes()

    host.on_move_language_to_streaming("En")

    assert (env.install.streaming_root / env.voice_rel).read_bytes() == env.voice
    assert (env.install.persistent_root / env.voice_rel).read_bytes() == env.voice
    assert json.loads(env.base_path.read_text(encoding="utf-8")) == {
        **env.base_catalog, "files": [*env.base_catalog["files"], env.voice_entry],
    }
    assert env.persist_path.read_bytes() == persistent_catalog_before
    for rel, content in env.protected.items():
        assert (env.install.persistent_root / rel).read_bytes() == content
        assert not (env.install.streaming_root / rel).exists()
    assert [method for method, *_ in host.notifications] == ["showSuccessToast", "hideLanguageWarningDialog"]


def test_invalid_steam_voice_is_not_bare_moved_after_preparation_fails(
    qapp, host, steam_install_with_english_downloaded_in_game,
):
    env = steam_install_with_english_downloaded_in_game
    changed_voice = build_pck(sounds=[(2, 1, make_wem(900))])
    (env.install.persistent_root / env.voice_rel).write_bytes(changed_voice)
    persistent_catalog_before = env.persist_path.read_bytes()
    base_catalog_before = env.base_path.read_bytes()

    host.on_move_language_to_streaming("En")

    assert not (env.install.streaming_root / env.voice_rel).exists()
    assert (env.install.persistent_root / env.voice_rel).read_bytes() == changed_voice
    assert env.base_path.read_bytes() == base_catalog_before
    assert env.persist_path.read_bytes() == persistent_catalog_before
    assert [method for method, *_ in host.notifications] == ["showErrorToast"]
