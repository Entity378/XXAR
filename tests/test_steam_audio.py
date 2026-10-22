import json
from pathlib import Path

import pytest
import xxhash

from src.mods import steam_audio
from src.mods.steam_audio import SteamAudioError, prepare_steam_audio


VOICE = "Full/En/SoundBank_En_0.pck"
OTHER = "Full/En/External_En_0.pck"
ORIGINAL = b"AKPK original English audio"
UPDATED = b"AKPK new English audio after a game update"
MODDED = b"AKPK modded audio, never adopt as an original"


def entry(rel, content, **extra):
    return {"remoteName": "Audio/Windows/" + rel,
            "md5": str(xxhash.xxh64(content).intdigest()),
            "fileSize": len(content), "isPatch": False, "tags": [3, 4], **extra}


def write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


@pytest.fixture
def install(tmp_path, monkeypatch):
    data = tmp_path / "game" / "ZenlessZoneZero_Data"
    streaming = data / "StreamingAssets" / "Audio" / "Windows"
    persistent = data / "Persistent" / "Audio" / "Windows"
    streaming.mkdir(parents=True)
    persistent.mkdir(parents=True)
    state = tmp_path / "app-state"
    monkeypatch.setattr(steam_audio, "get_game_state_dir", lambda game_id: state / game_id)
    unrelated = entry("Full/Streamed_SFX_0.pck", b"SFX", future_field={"keep": True})
    base = {"remoteParentDir": "", "unknown_root": "keep", "files": [unrelated]}
    (data / "StreamingAssets" / "audio_version").write_text(json.dumps(base))
    installed = {"remoteParentDir": "", "files": [unrelated, entry(VOICE, ORIGINAL),
                  entry(OTHER, ORIGINAL), entry("Full/En/Patch.pck", b"patch"),
                  entry("Full/En/Hotfix.pck", b"hotfix"), entry("Full/Jp/Unused.pck", b"not installed")]}
    for name in ("audio_version_persist", "audio_version_remote"):
        (data / "Persistent" / name).write_text(json.dumps(installed))
    for top in ("StreamingAssets", "Persistent"):
        (data / top / "audio_revision").write_bytes(b"revision unchanged")
    (data / "Persistent" / "base_version_hash").write_bytes(b"hash unchanged")
    write(persistent / VOICE, ORIGINAL)
    write(persistent / "Full/En/Patch.pck", b"patch")
    write(persistent / "Full/En/Hotfix.pck", b"hotfix")
    return data, streaming, persistent, state, base


def prepare(install):
    _, streaming, persistent, _, _ = install
    return prepare_steam_audio("zzz", streaming, persistent)


def snapshot(data):
    return {p.relative_to(data).as_posix(): p.read_bytes() for p in data.rglob("*") if p.is_file()}


def test_prepares_only_installed_verified_voices_and_preserves_game_metadata(install):
    data, streaming, persistent, state, base = install
    before = snapshot(data)
    result = prepare(install)
    assert result == {"prepared": True, "promoted": 1, "updated": 0, "registered": 1, "verified_rels": [VOICE]}
    assert (streaming / VOICE).read_bytes() == ORIGINAL
    manifest = json.loads((data / "StreamingAssets/audio_version").read_bytes())
    assert manifest["files"] == base["files"] + [entry(VOICE, ORIGINAL)]
    assert manifest["unknown_root"] == "keep"
    assert not (streaming / "Full/En/Patch.pck").exists()
    assert not (streaming / OTHER).exists()  # a purged/uninstalled story pack stays absent
    assert not (streaming / "Full/Jp/Unused.pck").exists()
    for name, content in before.items():
        if name != "StreamingAssets/audio_version":
            assert (data / name).read_bytes() == content
    backups = list(state.rglob("audio_version.before"))
    assert len(backups) == 1 and backups[0].read_bytes() == before["StreamingAssets/audio_version"]
    assert (persistent / VOICE).read_bytes() == ORIGINAL


def test_idempotent_after_modded_persistent_overlay_and_after_cleanup(install):
    data, streaming, persistent, state, _ = install
    prepare(install)
    manifest_before = (data / "StreamingAssets/audio_version").read_bytes()
    transaction_count = len(list(state.rglob("transaction.json")))
    write(persistent / VOICE, MODDED)
    result = prepare(install)
    assert result["prepared"] and result["verified_rels"] == [VOICE]
    assert result["promoted"] == result["updated"] == result["registered"] == 0
    assert (persistent / VOICE).read_bytes() == MODDED
    assert (data / "StreamingAssets/audio_version").read_bytes() == manifest_before
    (persistent / VOICE).unlink()
    assert prepare(install)["verified_rels"] == [VOICE]
    assert len(list(state.rglob("transaction.json"))) == transaction_count


@pytest.mark.parametrize("bad", [MODDED, ORIGINAL[:-1] + b"!"])
def test_bad_original_fails_before_any_game_write(install, bad):
    data, _, persistent, _, _ = install
    write(persistent / VOICE, bad)
    write(persistent / OTHER, ORIGINAL)  # a valid candidate must not be copied first
    before = snapshot(data)
    with pytest.raises(SteamAudioError, match="No verified original"):
        prepare(install)
    assert snapshot(data) == before


def test_refresh_adopts_verified_update_and_preserves_old_original_in_backups(install):
    data, streaming, persistent, state, _ = install
    prepare(install)
    installed_path = data / "Persistent/audio_version_persist"
    installed = json.loads(installed_path.read_bytes())
    installed["files"] = [entry(VOICE, UPDATED) if item["remoteName"].endswith("/SoundBank_En_0.pck") else item for item in installed["files"]]
    installed_path.write_text(json.dumps(installed))
    write(persistent / VOICE, UPDATED)
    result = prepare(install)
    assert result["updated"] == 1 and result["registered"] == 1
    assert (streaming / VOICE).read_bytes() == UPDATED
    assert any(path.read_bytes() == ORIGINAL for path in state.rglob("before/" + VOICE))


def test_refresh_with_unverified_update_keeps_every_game_file(install):
    data, _, persistent, _, _ = install
    prepare(install)
    installed_path = data / "Persistent/audio_version_persist"
    installed = json.loads(installed_path.read_bytes())
    installed["files"] = [entry(VOICE, UPDATED) if item["remoteName"].endswith("/SoundBank_En_0.pck") else item for item in installed["files"]]
    installed_path.write_text(json.dumps(installed))
    write(persistent / VOICE, MODDED)
    before = snapshot(data)
    with pytest.raises(SteamAudioError, match="No verified original"):
        prepare(install)
    assert snapshot(data) == before


def test_failed_commit_rolls_back_manifest_and_every_written_file(install, monkeypatch):
    data, streaming, persistent, state, _ = install
    write(persistent / OTHER, ORIGINAL)
    before = snapshot(data)
    real_atomic_bytes = steam_audio._atomic_bytes

    def fail_manifest_once(content, target):
        if target == data / "StreamingAssets/audio_version" and content != before["StreamingAssets/audio_version"]:
            raise OSError("injected manifest write failure")
        return real_atomic_bytes(content, target)

    monkeypatch.setattr(steam_audio, "_atomic_bytes", fail_manifest_once)
    with pytest.raises(SteamAudioError, match="preparation failed"):
        prepare(install)
    assert snapshot(data) == before
    assert not (streaming / VOICE).exists()
    assert json.loads(next(state.rglob("transaction.json")).read_bytes())["status"] == "rolled_back"


def test_missing_manifest_entry_fails_closed(install):
    data, _, persistent, _, _ = install
    write(persistent / "Full/En/Unknown.pck", ORIGINAL)
    before = snapshot(data)
    with pytest.raises(SteamAudioError, match="No game manifest entry"):
        prepare(install)
    assert snapshot(data) == before


def test_remote_manifest_is_fallback_only_when_local_manifest_missing(install):
    data, _, _, _, _ = install
    (data / "Persistent/audio_version_persist").unlink()
    assert prepare(install)["verified_rels"] == [VOICE]


def test_non_zzz_and_launcher_base_are_noops(install):
    data, streaming, persistent, _, base = install
    before = snapshot(data)
    assert not prepare_steam_audio("genshin", streaming, persistent)["prepared"]
    assert snapshot(data) == before
    base["files"].append(entry(VOICE, ORIGINAL))
    (data / "StreamingAssets/audio_version").write_text(json.dumps(base))
    before = snapshot(data)
    assert not prepare(install)["prepared"]
    assert snapshot(data) == before


def test_registration_survives_new_language_download(install):
    _, streaming, persistent, _, _ = install
    prepare(install)
    write(persistent / "Full/Jp/Unused.pck", b"not installed")
    assert prepare(install)["verified_rels"] == [VOICE, "Full/Jp/Unused.pck"]
    assert (streaming / "Full/Jp/Unused.pck").read_bytes() == b"not installed"


def test_transaction_requires_recovery_after_interrupted_commit(install):
    _, _, _, state, _ = install
    prepare(install)
    journal_path = next(state.rglob("transaction.json"))
    journal = json.loads(journal_path.read_bytes())
    journal["status"] = "committing"
    journal_path.write_text(json.dumps(journal))
    with pytest.raises(SteamAudioError, match="Incomplete Steam audio preparation"):
        prepare(install)


def test_legacy_installation_without_base_catalogue_is_not_detected_as_steam(install):
    data, _, _, _, _ = install
    (data / "StreamingAssets/audio_version").unlink()
    before = snapshot(data)
    assert not prepare(install)["prepared"]
    assert snapshot(data) == before


def test_rejects_traversal_and_duplicate_manifest_entries(install):
    data, _, _, _, _ = install
    path = data / "Persistent/audio_version_persist"
    installed = json.loads(path.read_bytes())
    installed["files"].append(entry("../escape.pck", ORIGINAL))
    path.write_text(json.dumps(installed))
    before = snapshot(data)
    with pytest.raises(SteamAudioError, match="unsafe resource path"):
        prepare(install)
    assert snapshot(data) == before
