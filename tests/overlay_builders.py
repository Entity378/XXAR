import hashlib
import json
import os
import struct

import xxhash

from helpers import build_bnk, build_pck, make_wem


def bank(bnk_id, wems, lang_id=0):
    return (bnk_id, lang_id, build_bnk(bnk_id, wems, language_id=lang_id))


def sound(wem_id, lang_id=0, seed=None):
    return (wem_id, lang_id, make_wem(wem_id if seed is None else seed))


def distinct_pck(seed, size=64):
    return build_pck(sounds=[(seed, 0, make_wem(seed, size))])


def xxh64_tag(content):
    return str(xxhash.xxh64(content).intdigest())


def md5_hex(content):
    return hashlib.md5(content).hexdigest()


def write_persist_manifest(install, overrides):
    # Maps each path under the Persistent audio root to the pristine bytes the game describes for it.
    persistent_top = install.data_dir / install.game.persistent_audio_subpath[0]
    manifest = persistent_top / "audio_version_persist"
    prefix = "/".join(install.game.persistent_audio_subpath[1:])
    files = [
        {"remoteName": f"{prefix}/{rel}", "md5": xxh64_tag(content), "fileSize": len(content), "isPatch": True}
        for rel, content in overrides.items()
    ]
    previous_mtime = manifest.stat().st_mtime if manifest.exists() else None
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps({"files": files}), encoding="utf-8")
    # The game rewrites the manifest on update, so its mtime always moves forward.
    if previous_mtime is not None:
        os.utime(manifest, (previous_mtime + 5, previous_mtime + 5))
    return manifest


def pkg_version_line(install, rel, content):
    prefix = install.streaming_root.relative_to(install.game_root).as_posix()
    return json.dumps({"remoteName": f"{prefix}/{rel}", "md5": md5_hex(content), "fileSize": len(content)})


def write_pkg_version(install, originals, manifest_name="pkg_version"):
    # Maps each path under the StreamingAssets audio root to its pristine bytes, as the launcher lists them.
    lines = [pkg_version_line(install, rel, content) for rel, content in originals.items()]
    manifest = install.game_root / manifest_name
    manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return manifest


def hash_sidecar_name(pck_name, content):
    stem = pck_name[:-len(".pck")]
    return f"{stem}_{md5_hex(content)}.hash"


def write_hash_sidecar(folder, pck_name, content):
    sidecar = folder / hash_sidecar_name(pck_name, content)
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    sidecar.write_bytes(b"")
    return sidecar


def bank_table_offsets(pck_bytes):
    # Maps each bank id to the offset of its 4-byte file_id in the pck bank table.
    header_size, _version, lang_map_size, banks_size, sounds_size = struct.unpack_from("<IIIII", pck_bytes, 4)
    size_fields = 16 if lang_map_size + banks_size + sounds_size + 0x10 < header_size else 12
    table_start = 12 + size_fields + lang_map_size
    bank_count = struct.unpack_from("<I", pck_bytes, table_start)[0]
    offsets = {}
    for index in range(bank_count):
        entry_offset = table_start + 4 + 20 * index
        offsets[struct.unpack_from("<I", pck_bytes, entry_offset)[0]] = entry_offset
    return offsets


def with_bank_ids_zeroed(pck_bytes, bnk_ids):
    offsets = bank_table_offsets(pck_bytes)
    zeroed = bytearray(pck_bytes)
    for bnk_id in bnk_ids:
        zeroed[offsets[bnk_id]:offsets[bnk_id] + 4] = b"\x00" * 4
    return bytes(zeroed)


def bnk_replacement(bnk_id, wem_id, wem_path="mod.wem", **extra):
    return {"bnk_id": bnk_id, "file_id": wem_id, "file_type": "bnk", "lang_id": 0, "wem_path": wem_path, **extra}


def wem_replacement(wem_id, wem_path="mod.wem", **extra):
    return {"bnk_id": None, "file_id": wem_id, "file_type": "wem", "lang_id": 0, "wem_path": wem_path, **extra}
