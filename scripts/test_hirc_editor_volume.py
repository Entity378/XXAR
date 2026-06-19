# Structural test for the HIRC Editor volume-INSERT path (read-only on the game install).
# Drives src.mods.hirc_mod_apply.apply_hirc_track_patches with a volume patch on a track that
# lacks a Volume prop, writing the overlay into a temp Persistent root, then asserts the overlay
# pck re-indexes, the bnk grew, and the track now carries the requested volume.
#
#   python scripts/test_hirc_editor_volume.py
import json
import logging
import os
import struct
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import src.core.app_config as app_config
from src.mods.hirc_mod_apply import apply_hirc_track_patches
from src.wwise import hirc_music as hm
from src.wwise import hirc_patcher as hp
from src.wwise.bnk_handler import BNKFile
from src.wwise.pck_indexer import PCKIndexer

TEST_DB = -4.5


def find_volume_less_track(pck_path):
    # Return (bnk_id, track_obj_id, source_id) for a MusicTrack lacking a Volume prop.
    idx = PCKIndexer(pck_path).build_index()
    raw = pck_path.read_bytes()
    for bank in idx["banks"]:
        bb = raw[bank["offset"]:bank["offset"] + bank["size"]]
        try:
            objs = hm._scan_bnk_music_objects(bb, 0)
        except Exception:
            continue
        for o in objs:
            if o.get("type") == "MusicTrack" and not o.get("has_volume") and o.get("sources"):
                return bank["id"], o["obj_id"], o["sources"][0]["source_id"]
    return None


def main():
    logging.getLogger("xxar").setLevel(logging.WARNING)
    app_config.switch_active_game("genshin")

    settings = json.loads((Path(os.environ["APPDATA"]) / "XXAR" / "settings.json").read_text(encoding="utf-8"))
    streaming = Path(settings["game_audio_dir"])
    pck = streaming / "Banks1.pck"
    if not pck.exists():
        print(f"pck not found: {pck}")
        sys.exit(1)

    found = find_volume_less_track(pck)
    if not found:
        print("no volume-less MusicTrack found")
        sys.exit(3)
    bnk_id, obj_id, src = found
    print(f"target: {pck.name} bnk {bnk_id} track 0x{obj_id:08X} src 0x{src:08X} -> {TEST_DB} dB")

    persistent = Path(tempfile.mkdtemp(prefix="xxar_persist_"))
    try:
        track_patches = [{
            "pck_name": pck.name, "bnk_id": bnk_id, "track_obj_id": obj_id,
            "source_remaps": [], "loop_ms": None, "volume_db": TEST_DB,
        }]
        summary = apply_hirc_track_patches(
            track_patches, str(streaming), str(persistent), fresh_clone=True
        )
        print("apply summary:", summary)
        assert summary["patched_files"] >= 1, "no files patched"
        assert summary["patched_bnks"] >= 1, "no bnks patched"

        overlay = persistent / "Banks1.pck"
        assert overlay.exists(), "overlay not written"

        # overlay re-indexes and the patched bnk grew + carries the inserted volume
        oidx = PCKIndexer(overlay).build_index()
        odata = overlay.read_bytes()
        binfo = next(b for b in oidx["banks"] if b["id"] == bnk_id)
        new_bnk = odata[binfo["offset"]:binfo["offset"] + binfo["size"]]

        orig_size = next(b for b in PCKIndexer(pck).build_index()["banks"] if b["id"] == bnk_id)["size"]
        assert binfo["size"] > orig_size, f"bnk did not grow ({orig_size} -> {binfo['size']})"

        rt = BNKFile(bnk_bytes=new_bnk)
        assert rt.get_bytes() == new_bnk, "patched bnk not stable"
        buf = bytearray(rt.data["HIRC"].getdata())
        targets = hp.scan_bank_for_patch_targets(buf, {src})
        vps = [v for v in targets.volume_patches if v.source_id == src and v.has_existing_volume]
        assert vps, "source has no volume after apply"
        val = struct.unpack_from("<f", buf, vps[0].volume_value_offset)[0]
        assert abs(val - TEST_DB) < 1e-6, f"volume reads {val}, want {TEST_DB}"

        print(f"PASS: bnk {orig_size} -> {binfo['size']} bytes, volume inserted = {val:.1f} dB, "
              f"overlay re-indexes ({len(oidx['banks'])} banks)")
    finally:
        try:
            (persistent / "Banks1.pck").unlink(missing_ok=True)
        except Exception:
            pass


if __name__ == "__main__":
    main()
