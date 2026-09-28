import io
import tarfile
from pathlib import Path

import pytest

from src.gui.backend import update_manager_bridge
from src.gui.backend.update_manager_bridge import (
    _find_installer_asset,
    _is_managed_install,
    _prune_stale_update_artifacts,
    _safe_extract_tar,
    clean_version_string,
    parse_version,
)


@pytest.mark.parametrize(
    "raw_version, expected_version",
    [
        ("v1.2.3", "1.2.3"),
        ("V1.2.3", "1.2.3"),
        ("XXAR-v1.2.3", "1.2.3"),
        ("  v1.1.4-alpha  ", "1.1.4-alpha"),
        ("1.2.3", "1.2.3"),
    ],
)
def test_clean_version_string(raw_version, expected_version):
    assert clean_version_string(raw_version) == expected_version


def test_parse_version_orders_releases_and_prereleases():
    ascending_versions = [
        "0.8.0-alpha",
        "0.8.0",
        "0.9.9",
        "1.0.0-dev",
        "1.0.0-alpha",
        "1.0.0-alpha.2",
        "1.0.0-beta",
        "1.0.0-beta.3",
        "1.0.0-rc1",
        "v1.0.0",
        "1.0.1",
        "XXAR-v1.1.0-alpha",
        "1.1.0",
        "1.1.4",
        "1.10.0",
    ]
    parsed_versions = [parse_version(version) for version in ascending_versions]
    assert parsed_versions == sorted(parsed_versions)
    assert len(set(parsed_versions)) == len(parsed_versions)


@pytest.mark.parametrize(
    "first_version, second_version",
    [("1.2", "1.2.0"), ("v1.2.0", "1.2.0"), ("XXAR-v1.2.0", "V1.2.0"), ("1.2.0-ALPHA", "1.2.0-alpha.0"), ("1.2.0-rc.1", "1.2.0-rc1")],
)
def test_parse_version_equivalent_spellings(first_version, second_version):
    assert parse_version(first_version) == parse_version(second_version)


def test_parse_version_tolerates_garbage():
    assert parse_version("1.x.3") == (1, 0, 3, 3, 0)
    assert parse_version("1.0.0-betaX") == (1, 0, 0, 1, 0)


def asset(name):
    return {"name": name, "browser_download_url": f"http://127.0.0.1/{name}", "url": f"http://127.0.0.1/api/{name}"}


@pytest.mark.parametrize(
    "asset_names, expected_name",
    [
        (["XXAR-Installer-v1.2.0.exe"], "XXAR-Installer-v1.2.0.exe"),
        (["XXAR-Setup-v1.0.2.exe"], "XXAR-Setup-v1.0.2.exe"),
        (["XXAR-Installer-v1.2.0.msi", "XXAR-Installer-v1.2.0.exe"], "XXAR-Installer-v1.2.0.exe"),
        (["XXAR-Installer-v1.2.0.msi", "XXAR-Setup-v1.2.0.exe"], "XXAR-Setup-v1.2.0.exe"),
        (["XXAR-Setup-v1.2.0.exe", "XXAR-Installer-v1.2.0.exe"], "XXAR-Installer-v1.2.0.exe"),
        (["XXAR-v1.2.0-portable.zip", "XXAR-Setup-v1.0.0.msi"], "XXAR-Setup-v1.0.0.msi"),
        (["XXAR-Installer-v1.2.0.EXE"], "XXAR-Installer-v1.2.0.EXE"),
    ],
)
def test_find_installer_asset_picks_the_newest_runnable_format(asset_names, expected_name):
    assert _find_installer_asset([asset(name) for name in asset_names])["name"] == expected_name


@pytest.mark.parametrize(
    "asset_names",
    [
        [],
        ["XXAR-v1.2.0-portable.zip"],
        ["XXAR-Installer-v1.2.0.msix", "XXAR-Installer-v1.2.0.appx"],
        ["Other-Installer-v1.2.0.exe", "Installer-XXAR-v1.2.0.exe"],
        ["XXAR-linux-x86_64.flatpak"],
    ],
)
def test_find_installer_asset_ignores_unknown_formats(asset_names):
    assert _find_installer_asset([asset(name) for name in asset_names]) is None


def test_find_installer_asset_tolerates_nameless_assets():
    assert _find_installer_asset([{"browser_download_url": "http://127.0.0.1/x"}]) is None


@pytest.fixture
def install_root(tmp_path, monkeypatch):
    root = tmp_path / "Local" / "XXAR" / "resources"
    root.mkdir(parents=True)
    monkeypatch.delenv("XXAR_UPDATE_FORCE_PORTABLE", raising=False)
    monkeypatch.setattr(update_manager_bridge, "_read_install_location", lambda: root)
    return root


def test_exe_under_the_registered_root_is_a_managed_install(install_root, monkeypatch):
    monkeypatch.setattr(update_manager_bridge, "_get_real_exe_path", lambda: str(install_root / "XXAR.exe"))
    assert _is_managed_install()


def test_force_portable_overrides_the_registry(install_root, monkeypatch):
    monkeypatch.setattr(update_manager_bridge, "_get_real_exe_path", lambda: str(install_root / "XXAR.exe"))
    monkeypatch.setenv("XXAR_UPDATE_FORCE_PORTABLE", "1")
    assert not _is_managed_install()


@pytest.mark.parametrize("exe_relative_path", ["../../Portable/XXAR.exe", "../resources-old/XXAR.exe"])
def test_exe_outside_the_registered_root_is_not_managed(install_root, monkeypatch, exe_relative_path):
    exe_path = (install_root / exe_relative_path).resolve()
    monkeypatch.setattr(update_manager_bridge, "_get_real_exe_path", lambda: str(exe_path))
    assert not _is_managed_install()


def test_missing_registry_marker_is_not_managed(monkeypatch):
    monkeypatch.delenv("XXAR_UPDATE_FORCE_PORTABLE", raising=False)
    monkeypatch.setattr(update_manager_bridge, "_read_install_location", lambda: None)
    assert not _is_managed_install()


def make_tar(tar_path, members):
    with tarfile.open(tar_path, "w:gz") as tar_file:
        for member_name, content in members.get("files", {}).items():
            tar_info = tarfile.TarInfo(member_name)
            tar_info.size = len(content)
            tar_file.addfile(tar_info, io.BytesIO(content))
        for link_name, link_target in members.get("symlinks", {}).items():
            tar_info = tarfile.TarInfo(link_name)
            tar_info.type = tarfile.SYMTYPE
            tar_info.linkname = link_target
            tar_file.addfile(tar_info)
    return tar_path


class PreFilterTarFile:
    # Mimics tarfile before Python 3.11.4, whose extractall has no filter argument.
    def __init__(self, tar_file):
        self._tar_file = tar_file

    def getmembers(self):
        return self._tar_file.getmembers()

    def extractall(self, path):
        self._tar_file.extractall(path, filter="fully_trusted")


@pytest.fixture(params=["data_filter", "manual_check"])
def extract_tar(request):
    def extract(tar_path, destination):
        with tarfile.open(tar_path, "r:gz") as tar_file:
            if request.param == "data_filter":
                _safe_extract_tar(tar_file, destination)
            else:
                _safe_extract_tar(PreFilterTarFile(tar_file), destination)

    return extract


def test_safe_extract_tar_extracts_regular_members(tmp_path, extract_tar):
    tar_path = make_tar(tmp_path / "update.tar.gz", {"files": {"XXAR": b"binary", "lib/libqt.so": b"lib"}})
    destination = tmp_path / "updates"
    destination.mkdir()
    extract_tar(tar_path, destination)
    assert (destination / "XXAR").read_bytes() == b"binary"
    assert (destination / "lib" / "libqt.so").read_bytes() == b"lib"


def test_safe_extract_tar_rejects_path_traversal(tmp_path, extract_tar):
    tar_path = make_tar(tmp_path / "evil.tar.gz", {"files": {"../escaped.txt": b"pwned"}})
    destination = tmp_path / "updates"
    destination.mkdir()
    with pytest.raises(Exception, match="(?i)traversal|outside"):
        extract_tar(tar_path, destination)
    assert not (tmp_path / "escaped.txt").exists()


def test_safe_extract_tar_rejects_escaping_symlinks(tmp_path, extract_tar):
    tar_path = make_tar(tmp_path / "evil.tar.gz", {"symlinks": {"XXAR": "../../outside/XXAR"}})
    destination = tmp_path / "updates"
    destination.mkdir()
    with pytest.raises(Exception, match="(?i)escaping|outside"):
        extract_tar(tar_path, destination)
    assert not Path(destination / "XXAR").exists()


def test_prune_removes_stale_update_downloads_only(tmp_path):
    update_dir = tmp_path / "updates"
    (update_dir / "staging").mkdir(parents=True)
    stale_names = ["XXAR-Installer-v1.0.0.exe", "XXAR-Setup-v0.9.0.msi", "XXAR-v1.0.0.zip", "XXAR-linux.tar.gz", "XXAR-linux-x86_64.flatpak"]
    kept_names = ["XXAR-Installer-v1.2.0.exe", "updater.log", "update_success", "notes.txt"]
    for file_name in stale_names + kept_names:
        (update_dir / file_name).write_bytes(b"x")
    (update_dir / "staging" / "payload.exe").write_bytes(b"x")
    _prune_stale_update_artifacts(update_dir, keep="XXAR-Installer-v1.2.0.exe")
    assert sorted(entry.name for entry in update_dir.iterdir()) == sorted(kept_names + ["staging"])
    assert (update_dir / "staging" / "payload.exe").exists()


def test_prune_without_keep_removes_every_download(tmp_path):
    (tmp_path / "XXAR-Installer-v1.2.0.exe").write_bytes(b"x")
    _prune_stale_update_artifacts(tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_prune_tolerates_a_missing_update_dir(tmp_path):
    _prune_stale_update_artifacts(tmp_path / "missing")
