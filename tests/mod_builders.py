import hashlib
import json
import struct
from pathlib import Path
from types import SimpleNamespace

from helpers import build_bnk, build_pck, configure_game_in_settings, hirc_object, make_game_install, make_wem
from src.mods.package_manager import ModPackageManager
from src.mods.persistent_manager import PersistentModManager
from src.mods.persistent_originals import cleanup_persistent_overlay
from src.wwise.bnk_handler import BNKFile
from src.wwise.hirc_patcher import END_MARKER_ID
from src.wwise.pck_indexer import PCKIndexer

GAME_IDS = ("zzz", "genshin", "hsr")

SFX_BNK_ID = 1001
SECOND_SFX_BNK_ID = 1002
MUSIC_BNK_ID = 1003
VOICE_BNK_ID = 2001

EMBEDDED_WEM_ID = 110001
SHARED_WEM_ID = 110002
SECOND_SFX_BNK_WEM_ID = 110003
STREAMED_WEM_ID = 120001
SECOND_STREAMED_WEM_ID = 120002
VOICE_WEM_ID = 210001
VOICE_STREAMED_WEM_ID = 220001

VOICE_LANG_ID = 1
VOICE_LANGUAGES = {0: "sfx", VOICE_LANG_ID: "english"}

# Folders are relative to the StreamingAssets audio root that settings.json stores for each game.
LAYOUTS = {
    "zzz": SimpleNamespace(
        sfx_dir="Full", voice_dir="Full/En",
        soundbank="SoundBank_SFX_0.pck", streamed="Streamed_SFX_0.pck",
        voice_soundbank="SoundBank_En_0.pck", voice_streamed="Streamed_En_0.pck",
        music_pck="Streamed_SFX_1.pck",
    ),
    "genshin": SimpleNamespace(
        sfx_dir="", voice_dir="English(US)",
        soundbank="Banks0.pck", streamed="Streamed0.pck",
        voice_soundbank="BanksVO0.pck", voice_streamed="StreamedVO0.pck",
        music_pck="Music0.pck",
    ),
    "hsr": SimpleNamespace(
        sfx_dir="SFX", voice_dir="English",
        soundbank="Banks0.pck", streamed="Streamed0.pck",
        voice_soundbank="BanksVO0.pck", voice_streamed="StreamedVO0.pck",
        music_pck="Streamed1.pck",
    ),
}


def join_key(folder, name):
    return f"{folder}/{name}" if folder else name


class GameKeys:

    def __init__(self, game_id):
        layout = LAYOUTS[game_id]
        self.soundbank = join_key(layout.sfx_dir, layout.soundbank)
        self.streamed = join_key(layout.sfx_dir, layout.streamed)
        self.voice_soundbank = join_key(layout.voice_dir, layout.voice_soundbank)
        self.voice_streamed = join_key(layout.voice_dir, layout.voice_streamed)
        self.music = join_key(layout.sfx_dir, layout.music_pck)
        self.patch = join_key(layout.sfx_dir, "Patch.pck")


def standard_audio_files(game_id):
    keys = GameKeys(game_id)
    sfx_bnk = build_bnk(SFX_BNK_ID, {EMBEDDED_WEM_ID: make_wem(1), SHARED_WEM_ID: make_wem(2, 48)})
    second_sfx_bnk = build_bnk(SECOND_SFX_BNK_ID, {SECOND_SFX_BNK_WEM_ID: make_wem(3)})
    voice_bnk = build_bnk(VOICE_BNK_ID, {VOICE_WEM_ID: make_wem(6)}, language_id=VOICE_LANG_ID)
    return {
        keys.soundbank: build_pck(banks=[(SFX_BNK_ID, 0, sfx_bnk), (SECOND_SFX_BNK_ID, 0, second_sfx_bnk)]),
        keys.streamed: build_pck(sounds=[
            (SHARED_WEM_ID, 0, make_wem(2, 200)),
            (STREAMED_WEM_ID, 0, make_wem(4)),
            (SECOND_STREAMED_WEM_ID, 0, make_wem(5)),
        ]),
        keys.voice_soundbank: build_pck(banks=[(VOICE_BNK_ID, VOICE_LANG_ID, voice_bnk)], languages=VOICE_LANGUAGES),
        keys.voice_streamed: build_pck(sounds=[(VOICE_STREAMED_WEM_ID, VOICE_LANG_ID, make_wem(7))], languages=VOICE_LANGUAGES),
    }


def make_mod_env(root, game_id, streaming_files=None, persistent_files=None):
    audio_files = {**standard_audio_files(game_id), **(streaming_files or {})}
    install = make_game_install(Path(root) / "game", game_id, streaming_files=audio_files, persistent_files=persistent_files)
    configure_game_in_settings(install)
    tracker = PersistentModManager(game_id=game_id)
    manager = ModPackageManager(persistent_mod_manager=tracker, game_id=game_id)
    return SimpleNamespace(
        game=install.game,
        keys=GameKeys(game_id),
        streaming_root=install.streaming_root,
        persistent_root=install.persistent_root,
        game_root=install.game_root,
        manager=manager,
        tracker=tracker,
        work_dir=Path(root) / "work",
    )


def mod_entry(source_dir, wem_id, wem_bytes, bnk_id=None, lang_id=0, **audio_settings):
    # Stages one replacement in the tracker shape that create_mod_package consumes.
    source_dir = Path(source_dir)
    source_dir.mkdir(parents=True, exist_ok=True)
    wem_path = source_dir / f"source_{bnk_id}_{wem_id}_{len(list(source_dir.iterdir()))}.wem"
    wem_path.write_bytes(wem_bytes)
    tracker_key = f"{bnk_id}|{wem_id}" if bnk_id is not None else str(wem_id)
    info = {
        "wem_path": str(wem_path),
        "sound_name": "",
        "lang_id": lang_id,
        "bnk_id": bnk_id,
        "file_type": "bnk" if bnk_id is not None else "wem",
        **audio_settings,
    }
    return tracker_key, info


def package_mod(env, name, entries_by_pck, version="1.0.0", hirc_patches=None, thumbnail_path=None):
    # entries_by_pck maps a pck key to a list of mod_entry results.
    replacements = {pck_key: dict(entries) for pck_key, entries in entries_by_pck.items()}
    output_path = env.work_dir / f"{name.replace(' ', '_')}_{version}{env.game.mod_file_ext}"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    env.manager.create_mod_package(
        output_path,
        {"name": name, "author": "Tester", "version": version},
        replacements,
        thumbnail_path=thumbnail_path,
        hirc_patches=hirc_patches,
    )
    return output_path


def install_enabled(env, name, entries_by_pck, version="1.0.0", hirc_patches=None):
    package_path = package_mod(env, name, entries_by_pck, version=version, hirc_patches=hirc_patches)
    installed_mod_uuid = env.manager.install_mod(package_path)["uuid"]
    env.manager.set_mod_enabled(installed_mod_uuid, True)
    return installed_mod_uuid


def run_apply(env, conflict_preferences=None):
    # Mirrors ModManagerBridge._start_apply: overlay cleanup first, then apply_mods.
    modded_keys = set(env.tracker.get_all_replacements().keys())
    cleanup_persistent_overlay(env.game.id, env.streaming_root, env.persistent_root, modded_keys)
    return env.manager.apply_mods(env.streaming_root, env.persistent_root, conflict_preferences=conflict_preferences)


def write_pkg_version_manifest(env):
    # Writes launcher ground truth (JSON lines of remoteName, md5 and fileSize) for every StreamingAssets pck into the game root.
    streaming_prefix = env.streaming_root.relative_to(env.game_root).as_posix()
    manifest_lines = []
    for pck_path in sorted(env.streaming_root.rglob("*.pck")):
        pck_bytes = pck_path.read_bytes()
        remote_name = f"{streaming_prefix}/{pck_path.relative_to(env.streaming_root).as_posix()}"
        manifest_lines.append(json.dumps({"remoteName": remote_name, "md5": hashlib.md5(pck_bytes).hexdigest(), "fileSize": len(pck_bytes)}))
    (env.game_root / "pkg_version").write_text("\n".join(manifest_lines), encoding="utf-8")


def snapshot_files(root):
    root = Path(root)
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in sorted(root.rglob("*")) if path.is_file()}


def pck_entries(pck_path):
    # Returns the bytes of every pck entry keyed by (section, file_id, lang_id).
    indexer = PCKIndexer(str(pck_path))
    index = indexer.build_index()
    entries = {}
    with open(pck_path, "rb") as handle:
        for section in ("banks", "sounds", "externals"):
            for entry in index[section]:
                handle.seek(entry["offset"])
                entries[(section, entry["id"], entry["lang_id"])] = handle.read(entry["size"])
    return entries


def bank_bytes(pck_path, bnk_id):
    return next(data for (section, file_id, _), data in pck_entries(pck_path).items() if section == "banks" and file_id == bnk_id)


def bank_wems(pck_path, bnk_id):
    bnk = BNKFile(bnk_bytes=bank_bytes(pck_path, bnk_id))
    return {wem_id: bnk.extract_wem(wem_id) for wem_id in bnk.list_wems()}


def loose_wem(pck_path, wem_id):
    return next(data for (section, file_id, _), data in pck_entries(pck_path).items() if section != "banks" and file_id == wem_id)


def make_pcm_wem(duration_ms, sample_rate=1000):
    # Builds a RIFF with fmt and data chunks whose parsed duration is exactly duration_ms.
    data_size = duration_ms * sample_rate // 1000 * 2
    fmt_chunk = b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, sample_rate, sample_rate * 2, 2, 16)
    data_chunk = b"data" + struct.pack("<I", data_size) + b"\x00" * data_size
    body = b"WAVE" + fmt_chunk + data_chunk
    return b"RIFF" + struct.pack("<I", len(body)) + body


def music_track_object(track_id, source_id, play_at_ms, src_duration_ms, parent_id=0, props=None):
    # Builds a MusicTrack (0x0B) with one source, one playlist clip and an AkPropBundle of {prop_id: float}.
    props = props or {}
    body = struct.pack("<B", 0)
    body += struct.pack("<I", 1) + struct.pack("<IBIIB", 0x00040001, 2, source_id, 0, 0)
    body += struct.pack("<I", 1) + struct.pack("<III4d", 0, source_id, 0, play_at_ms, 0.0, 0.0, src_duration_ms)
    body += struct.pack("<II", 1, 0)
    body += struct.pack("<IB", 0, 0)
    body += struct.pack("<BB", 0, 0)
    body += struct.pack("<IB", parent_id, 0)
    body += struct.pack("<B", len(props)) + bytes(props.keys()) + b"".join(struct.pack("<f", value) for value in props.values())
    body += b"\x00" * 8
    return hirc_object(0x0B, track_id, body)


def music_segment_object(segment_id, child_track_ids, duration_ms):
    # Builds a MusicSegment (0x0A) listing its child tracks, followed by fDuration and an entry and an exit marker.
    children = struct.pack("<I", len(child_track_ids)) + b"".join(struct.pack("<I", child) for child in child_track_ids)
    padding = b"\x00" * max(0, 28 - len(children))
    markers = struct.pack("<I", 2)
    markers += struct.pack("<IdI", 1, 0.0, 0)
    markers += struct.pack("<IdI", END_MARKER_ID, duration_ms, 0)
    return hirc_object(0x0A, segment_id, children + padding + struct.pack("<d", duration_ms) + markers)


def sound_object(sound_id, source_id):
    # Builds a plain CAkSound (0x02), an SFX or voice node that the volume patch must never touch.
    return hirc_object(0x02, sound_id, struct.pack("<IBIIB", 0x00040001, 2, source_id, 0, 0) + b"\x00" * 16)


def read_music_track(bnk_bytes, track_id):
    # Returns (source_ids, [(source_id, fPlayAt, fSrcDuration)], {prop_id: float}) for one MusicTrack.
    hirc_start = bnk_bytes.index(b"HIRC") + 8
    object_count = struct.unpack_from("<I", bnk_bytes, hirc_start)[0]
    position = hirc_start + 4
    for _ in range(object_count):
        object_type, object_size, object_id = struct.unpack_from("<BII", bnk_bytes, position)
        data_start = position + 5
        if object_type == 0x0B and object_id == track_id:
            cursor = data_start + 5
            source_count = struct.unpack_from("<I", bnk_bytes, cursor)[0]
            cursor += 4
            source_ids = []
            for _ in range(source_count):
                source_ids.append(struct.unpack_from("<I", bnk_bytes, cursor + 5)[0])
                cursor += 14
            clip_count = struct.unpack_from("<I", bnk_bytes, cursor)[0]
            cursor += 4
            playlist = []
            for _ in range(clip_count):
                _, clip_source, _, play_at, _, _, src_duration = struct.unpack_from("<III4d", bnk_bytes, cursor)
                playlist.append((clip_source, play_at, src_duration))
                cursor += 44
            cursor += 8 + 5 + 2 + 5
            prop_count = bnk_bytes[cursor]
            prop_ids = list(bnk_bytes[cursor + 1:cursor + 1 + prop_count])
            values_start = cursor + 1 + prop_count
            props = {prop_id: struct.unpack_from("<f", bnk_bytes, values_start + 4 * index)[0] for index, prop_id in enumerate(prop_ids)}
            return source_ids, playlist, props
        position = data_start + object_size
    raise KeyError(track_id)


def read_segment_duration(bnk_bytes, segment_id):
    hirc_start = bnk_bytes.index(b"HIRC") + 8
    object_count = struct.unpack_from("<I", bnk_bytes, hirc_start)[0]
    position = hirc_start + 4
    for _ in range(object_count):
        object_type, object_size, object_id = struct.unpack_from("<BII", bnk_bytes, position)
        data_start = position + 5
        if object_type == 0x0A and object_id == segment_id:
            data_end = data_start + object_size
            return struct.unpack_from("<d", bnk_bytes, data_end - 2 * 16 - 4 - 8)[0]
        position = data_start + object_size
    raise KeyError(segment_id)
