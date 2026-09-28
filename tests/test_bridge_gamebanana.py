import io
import json
import urllib.error
import zipfile

import pytest

from bridge_helpers import (
    STREAMED_PCK,
    game_lock_free,
    holding_game_lock,
    sandbox_app_environment,
    write_mod_package,
)
from helpers import make_wem, record_signal, wait_until, write_settings

SOUND_MOD_ID = 1001
NATIVE_MISC_MOD_ID = 2001
FOREIGN_MISC_MOD_ID = 2002
FILE_ID = 555
DOWNLOAD_URL = f"https://gamebanana.com/dl/{FILE_ID}"

SOUND_INDEX = {
    "_aRecords": [{"_idRow": SOUND_MOD_ID, "_sName": "Cool Sound", "_aSubmitter": {"_sName": "Alice"}, "_nDownloadCount": 5}],
    "_aMetadata": {"_nRecordCount": 1},
}
MISC_INDEX = {"_aRecords": [{"_idRow": NATIVE_MISC_MOD_ID, "_sName": "Native Mod"}, {"_idRow": FOREIGN_MISC_MOD_ID, "_sName": "Other Mod"}]}
SOUND_DETAILS = [
    "Cool Sound", "Alice", "<p>Great</p>", "", 10, 2, 1700000000,
    {str(FILE_ID): {"_sFile": "pack.zip", "_sDownloadUrl": DOWNLOAD_URL, "_nDownloadCount": 3, "_nFilesize": 100}},
    "",
]


@pytest.fixture
def sandbox(monkeypatch):
    return sandbox_app_environment(monkeypatch)


class FakeResponse:
    def __init__(self, body):
        self._body = io.BytesIO(body)
        self.headers = {"Content-Length": str(len(body))}

    def read(self, size=-1):
        return self._body.read(size)

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


@pytest.fixture
def fake_gamebanana(monkeypatch, tmp_path):
    from src.gui.backend import gamebanana_bridge

    routes = {}
    requested_urls = []

    def fake_urlopen(request, timeout=10):
        url = request.full_url
        requested_urls.append(url)
        for fragment, body in routes.items():
            if fragment in url:
                return FakeResponse(body if isinstance(body, bytes) else json.dumps(body).encode("utf-8"))
        raise urllib.error.URLError("offline in tests")

    monkeypatch.setattr(gamebanana_bridge, "_urlopen", fake_urlopen)
    monkeypatch.setattr(gamebanana_bridge, "_cache", {})
    monkeypatch.setattr(gamebanana_bridge, "_cache_dirty", False)
    monkeypatch.setattr(gamebanana_bridge, "_cache_path", lambda: tmp_path / "gamebanana_cache.json")
    return routes, requested_urls


@pytest.fixture
def gamebanana(qapp, sandbox, fake_gamebanana):
    from src.gui.backend.gamebanana_bridge import GameBananaBridge

    bridge = GameBananaBridge()
    yield bridge
    bridge._workers.shutdown()
    assert wait_until(game_lock_free)


def mod_archive(tmp_path, *mod_names):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for mod_name in mod_names:
            package = write_mod_package(tmp_path / "gb_packages" / f"{mod_name}.zzar", mod_name, {STREAMED_PCK: {21: make_wem(5, 64)}})
            archive.writestr(f"release/{mod_name}.zzar", package.read_bytes())
    return buffer.getvalue()


def test_fetch_mods_combines_sound_and_native_misc_mods(gamebanana, fake_gamebanana):
    routes, requested_urls = fake_gamebanana
    routes.update({
        "/Sound/Index": SOUND_INDEX,
        "/Mod/Index": MISC_INDEX,
        f"/Mod/{NATIVE_MISC_MOD_ID}/ProfilePage": {"_aRequirements": [["XXAR", ""]]},
        f"/Mod/{FOREIGN_MISC_MOD_ID}/ProfilePage": {"_aRequirements": [], "_aFiles": []},
        f"/Sound/{SOUND_MOD_ID}/ProfilePage": {"_aRequirements": [["XXAR", ""]]},
    })
    loading = record_signal(gamebanana.loadingStateChanged)
    loaded = record_signal(gamebanana.modsLoaded)
    totals = record_signal(gamebanana.totalModsCount)
    support = record_signal(gamebanana.modSupportUpdated)

    gamebanana.fetchMods(1, "default", "")

    assert wait_until(lambda: loaded and support)
    assert [(mod["id"], mod["name"], mod["item_type"]) for mod in loaded[0][0]] == [
        (SOUND_MOD_ID, "Cool Sound", "Sound"),
        (NATIVE_MISC_MOD_ID, "Native Mod", "Mod"),
    ]
    assert totals == [(1,)]
    assert support == [(SOUND_MOD_ID, True)]
    assert loading[0] == (True,) and loading[-1] == (False,)
    assert all("_aFilters[Generic_Game]=19567" in url for url in requested_urls if "/Index" in url)


def test_offline_fetch_ends_loading_with_an_empty_list(gamebanana):
    loading = record_signal(gamebanana.loadingStateChanged)
    loaded = record_signal(gamebanana.modsLoaded)

    gamebanana.fetchMods(1, "default", "")

    assert wait_until(lambda: loaded)
    assert loaded == [([],)]
    assert loading[-1] == (False,)


def test_switching_game_clears_the_list_and_targets_the_new_gamebanana_game(gamebanana, fake_gamebanana):
    routes, requested_urls = fake_gamebanana
    loaded = record_signal(gamebanana.modsLoaded)
    totals = record_signal(gamebanana.totalModsCount)

    assert gamebanana.set_active_game("genshin") is True
    assert gamebanana.set_active_game("genshin") is False
    gamebanana.fetchMods(1, "default", "")

    assert wait_until(lambda: len(loaded) == 2)
    assert loaded[0] == ([],) and totals[0] == (0,)
    assert any("_aFilters[Generic_Game]=8552" in url for url in requested_urls)


def test_mod_details_report_files_and_support(gamebanana, fake_gamebanana):
    routes, _ = fake_gamebanana
    routes.update({
        f"itemtype=Sound&itemid={SOUND_MOD_ID}": SOUND_DETAILS,
        f"/File/{FILE_ID}": {"_aArchiveFileTree": ["release/Cool Sound.zzar"]},
    })
    details = record_signal(gamebanana.modDetailsLoaded)

    gamebanana.fetchModDetails(SOUND_MOD_ID)

    assert wait_until(lambda: details)
    mod = details[0][0]
    assert (mod["id"], mod["name"], mod["author"], mod["mod_supported"]) == (SOUND_MOD_ID, "Cool Sound", "Alice", True)
    assert [(file["download_url"], file["has_mod_file"]) for file in mod["files"]] == [(DOWNLOAD_URL, True)]


def test_download_installs_the_mod_and_links_it_to_gamebanana(gamebanana, fake_gamebanana, tmp_path):
    routes, _ = fake_gamebanana
    routes[DOWNLOAD_URL] = mod_archive(tmp_path, "Cool Sound")
    installed = record_signal(gamebanana.installComplete)
    names = record_signal(gamebanana.installedModsChanged)
    install_states = record_signal(gamebanana.installStateChanged)

    gamebanana.downloadMod(DOWNLOAD_URL, "pack.zip", "Cool Sound", SOUND_MOD_ID)

    assert wait_until(lambda: installed and game_lock_free())
    assert installed == [("Installed: Cool Sound v1.0.0",)]
    assert names == [(["Cool Sound"],)]
    assert install_states == [(True,), (False,)]
    assert gamebanana.getInstalledModIds() == [SOUND_MOD_ID]
    assert gamebanana.getInstalledDownloadUrls() == [DOWNLOAD_URL]
    assert gamebanana.getInstalledModsByUrl() == {DOWNLOAD_URL: ["Cool Sound.zzar"]}


def test_archive_with_several_mods_asks_which_one_to_install(gamebanana, fake_gamebanana, tmp_path):
    routes, _ = fake_gamebanana
    routes[DOWNLOAD_URL] = mod_archive(tmp_path, "First", "Second")
    choices = record_signal(gamebanana.multipleModsFound)
    installed = record_signal(gamebanana.installComplete)

    gamebanana.downloadMod(DOWNLOAD_URL, "pack.zip", "Pack", SOUND_MOD_ID)
    assert wait_until(lambda: choices and game_lock_free())
    mod_entries, archive_path = choices[0]
    assert mod_entries == ["release/First.zzar", "release/Second.zzar"]
    gamebanana.installChosenMod(archive_path, mod_entries[1])

    assert wait_until(lambda: installed and game_lock_free())
    assert gamebanana.getInstalledModNames() == ["Second"]
    assert gamebanana.getModTotalsByUrl() == {DOWNLOAD_URL: 2}


def test_archive_without_a_mod_reports_the_install_failure(gamebanana, fake_gamebanana):
    routes, _ = fake_gamebanana
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("readme.txt", "no mod here")
    routes[DOWNLOAD_URL] = buffer.getvalue()
    errors = record_signal(gamebanana.errorOccurred)

    gamebanana.downloadMod(DOWNLOAD_URL, "pack.zip", "Empty", SOUND_MOD_ID)

    assert wait_until(lambda: errors and game_lock_free())
    assert errors == [("Install Failed", "No .zzar files found in the downloaded archive")]


def test_failed_download_reports_it(gamebanana):
    errors = record_signal(gamebanana.errorOccurred)

    gamebanana.downloadMod(DOWNLOAD_URL, "pack.zip", "Missing", SOUND_MOD_ID)

    assert wait_until(lambda: errors)
    assert errors[0][0] == "Download Failed"


def test_install_that_finishes_downloading_during_a_write_waits_for_the_lock(gamebanana, fake_gamebanana, tmp_path):
    routes, _ = fake_gamebanana
    routes[DOWNLOAD_URL] = mod_archive(tmp_path, "Cool Sound")
    downloaded = record_signal(gamebanana.downloadComplete)
    installed = record_signal(gamebanana.installComplete)

    with holding_game_lock():
        gamebanana.downloadMod(DOWNLOAD_URL, "pack.zip", "Cool Sound", SOUND_MOD_ID)
        assert wait_until(lambda: downloaded)
        assert not wait_until(lambda: installed, timeout=0.5)
        assert gamebanana.getInstalledModNames() == []

    assert wait_until(lambda: installed and game_lock_free())
    assert gamebanana.getInstalledModNames() == ["Cool Sound"]


def test_download_to_path_saves_where_the_user_chose(gamebanana, fake_gamebanana, sandbox, tmp_path):
    routes, _ = fake_gamebanana
    routes[DOWNLOAD_URL] = b"archive bytes"
    target = tmp_path / "chosen" / "pack.zip"
    sandbox.dialog_answers["save_file"] = str(target)
    saved = record_signal(gamebanana.nonNativeDownloadComplete)

    gamebanana.downloadModToPath(DOWNLOAD_URL, "pack.zip")

    assert wait_until(lambda: saved)
    assert saved == [(str(target),)]
    assert target.read_bytes() == b"archive bytes"


def test_download_to_path_cancelled_in_the_dialog_does_nothing(gamebanana, fake_gamebanana):
    _, requested_urls = fake_gamebanana

    gamebanana.downloadModToPath(DOWNLOAD_URL, "pack.zip")

    assert requested_urls == []
    assert not gamebanana._workers.is_running("download")


@pytest.mark.parametrize(("thumbnails_enabled", "expect_thumbnail"), [(False, False), (True, True)])
def test_thumbnails_are_fetched_only_when_enabled(gamebanana, fake_gamebanana, thumbnails_enabled, expect_thumbnail):
    routes, requested_urls = fake_gamebanana
    image_url = "https://images.gamebanana.com/img/ss/sounds/cool.png"
    routes.update({
        f"itemid={SOUND_MOD_ID}&fields=text": [f'<img src="{image_url}">'],
        image_url: b"png bytes",
    })
    write_settings({"enable_gb_thumbnails": thumbnails_enabled})
    thumbnails = record_signal(gamebanana.thumbnailUpdated)

    gamebanana.fetchThumbnail(SOUND_MOD_ID)

    assert wait_until(lambda: not gamebanana._workers.is_running("thumb"))
    assert wait_until(lambda: bool(thumbnails) is expect_thumbnail, timeout=2)
    if expect_thumbnail:
        assert thumbnails[0][0] == SOUND_MOD_ID and thumbnails[0][1].startswith("file://")
    else:
        assert requested_urls == []
