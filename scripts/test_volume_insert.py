# Integration test for HIRC Volume insertion on REAL extracted BNKs (read-only on the game).
# Validates the Phase-1 core: insert a Volume (0x00) prop into MusicTracks that lack one,
# letting BNKFile recompute the HIRC chunk framing. Never writes to the game install.
#
#   python scripts/test_volume_insert.py [pck_path]
#
# Default pck is read from settings.json (active game's audio dir, first Banks*.pck).
import json
import logging
import os
import struct
import sys
from io import BytesIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.wwise.bnk_handler import BNKFile
from src.wwise.pck_indexer import PCKIndexer
from src.wwise import hirc_patcher as hp

HIRC_TYPE_MUSIC_TRACK = 0x0B
TEST_DB = -6.0


def default_pck():
    settings = Path(os.environ["APPDATA"]) / "XXAR" / "settings.json"
    d = json.loads(settings.read_text(encoding="utf-8"))
    audio = Path(d.get("game_audio_dir", ""))
    banks = sorted(audio.glob("Banks*.pck"))
    return banks[0] if banks else None


def hirc_mini_buffer(bnk):
    # The HIRC chunk bytes (b'HIRC' + size + entries + blob) so scan_* finds the magic.
    return bytearray(bnk.data["HIRC"].getdata())


def enumerate_music_sources(buf):
    # Walk HIRC MusicTrack objects, collect every referenced source id.
    sources = set()
    for hirc_start, hirc_size in hp._find_hirc_sections(buf):
        section_end = hirc_start + hirc_size
        num_objects = struct.unpack_from("<I", buf, hirc_start)[0]
        obj_pos = hirc_start + 4
        for _ in range(num_objects):
            if obj_pos + 5 > section_end:
                break
            obj_type = buf[obj_pos]
            obj_size = struct.unpack_from("<I", buf, obj_pos + 1)[0]
            obj_data_start = obj_pos + 5
            if obj_data_start + obj_size > len(buf):
                break
            if obj_type == HIRC_TYPE_MUSIC_TRACK:
                ns = struct.unpack_from("<I", buf, obj_data_start + 5)[0]
                if ns <= 100:
                    sp = obj_data_start + 9
                    for _ in range(ns):
                        if sp + 14 > len(buf):
                            break
                        sources.add(struct.unpack_from("<I", buf, sp + 5)[0])
                        sp += 14
            obj_pos = obj_data_start + obj_size
    return sources


def reassemble(bnk, mini_buffer):
    # Strip the 8-byte chunk header + 4-byte numObjects to recover the (grown) HIRC blob,
    # then let BNKFile recompute the chunk size on serialization.
    new_blob = bytes(mini_buffer[12:])
    bnk.data["HIRC"].data = BytesIO(new_blob)
    return bnk.get_bytes()


def find_targets(buf, sources):
    # Return one volume-less VolumePatchInfo with an empty bundle (cProps==0) and one with a
    # non-empty bundle (cProps>=1, the front-insert-into-existing-props path), if present.
    targets = hp.scan_bank_for_patch_targets(buf, sources)
    empty = next((v for v in targets.volume_patches
                  if not v.has_existing_volume and v.cProps == 0), None)
    nonempty = next((v for v in targets.volume_patches
                     if not v.has_existing_volume and v.cProps >= 1), None)
    return [v for v in (empty, nonempty) if v is not None]


def test_bnk(bnk_id, bnk_bytes):
    results = []
    bnk0 = BNKFile(bnk_bytes=bnk_bytes)
    if "HIRC" not in bnk0.data:
        return results
    sources = enumerate_music_sources(hirc_mini_buffer(bnk0))
    if not sources:
        return results
    for vp0 in find_targets(hirc_mini_buffer(bnk0), sources):
        # Fresh BNKFile + buffer per target so each insert is validated in isolation.
        results.append(_validate_insert(bnk_id, bnk_bytes, vp0))
    return results


def _validate_insert(bnk_id, bnk_bytes, vp):
    bnk = BNKFile(bnk_bytes=bnk_bytes)
    buf = hirc_mini_buffer(bnk)
    src = vp.source_id
    orig_hirc_size = struct.unpack_from("<I", buf, 4)[0]
    orig_total = len(bnk_bytes)

    res = hp.apply_volume_inserts(buf, [vp], {src: TEST_DB})
    assert res["inserted"] == 1, f"expected 1 insert, got {res}"
    assert res["total_shift"] == 5

    patched = reassemble(bnk, buf)

    # 1) exact growth
    assert len(patched) == orig_total + 5, f"size {orig_total} -> {len(patched)} (want +5)"

    # 2) BNKFile round-trips the patched bytes
    rt = BNKFile(bnk_bytes=patched)
    assert rt.get_bytes() == patched, "BNKFile round-trip is not byte-identical"

    # 3) HIRC chunk size grew by exactly 5
    rt_buf = hirc_mini_buffer(rt)
    new_hirc_size = struct.unpack_from("<I", rt_buf, 4)[0]
    assert new_hirc_size == orig_hirc_size + 5, f"HIRC size {orig_hirc_size} -> {new_hirc_size}"

    # 4) the track now HAS volume, value reads back, and 0x00 is at the front (sorted)
    targets = hp.scan_bank_for_patch_targets(rt_buf, {src})
    vps = [v for v in targets.volume_patches if v.source_id == src]
    assert vps, "source no longer found after insert"
    nvp = vps[0]
    assert nvp.has_existing_volume, "inserted volume not detected on re-scan"
    val = struct.unpack_from("<f", rt_buf, nvp.volume_value_offset)[0]
    assert abs(val - TEST_DB) < 1e-6, f"volume reads {val}, want {TEST_DB}"
    id_byte = rt_buf[nvp.ids_start_offset]
    assert id_byte == hp.VOLUME_PROP_ID, f"first prop id is {id_byte:#x}, want 0x00"

    return {"bnk_id": bnk_id, "source_id": src, "old_cprops": vp.cProps,
            "hirc": (orig_hirc_size, new_hirc_size), "value": val}


def run_pck(pck):
    idx = PCKIndexer(pck)
    index = idx.build_index()
    banks = index["banks"]
    passed = {"empty": 0, "nonempty": 0}
    with open(pck, "rb") as f:
        for b in banks:
            f.seek(b["offset"])
            bnk_bytes = f.read(b["size"])
            try:
                results = test_bnk(b["id"], bnk_bytes)
            except AssertionError as e:
                print(f"  FAIL bnk {b['id']}: {e}")
                sys.exit(2)
            for r in results:
                kind = "empty" if r["old_cprops"] == 0 else "nonempty"
                passed[kind] += 1
                print(f"  PASS bnk {r['bnk_id']}: src=0x{r['source_id']:08X} "
                      f"cProps {r['old_cprops']}->{r['old_cprops']+1} "
                      f"HIRC {r['hirc'][0]}->{r['hirc'][1]} vol={r['value']:.1f}dB")
    return passed


def main():
    # Quiet the per-chunk INFO spam; we only care about test results here.
    logging.getLogger("xxar").setLevel(logging.WARNING)

    if len(sys.argv) > 1:
        pcks = [Path(a) for a in sys.argv[1:]]
    else:
        d = default_pck()
        pcks = [d] if d else []

    total = {"empty": 0, "nonempty": 0}
    for pck in pcks:
        if not pck or not pck.exists():
            print(f"pck not found: {pck}")
            sys.exit(1)
        print(f"pck: {pck.name}")
        got = run_pck(pck)
        total["empty"] += got["empty"]
        total["nonempty"] += got["nonempty"]

    n = total["empty"] + total["nonempty"]
    if n == 0:
        print("No volume-less MusicTrack found to test (unexpected for music banks).")
        sys.exit(3)
    print(f"\nAll {n} insertion test(s) passed "
          f"(empty bundle: {total['empty']}, non-empty bundle: {total['nonempty']}).")
    if total["nonempty"] == 0:
        print("NOTE: no non-empty-bundle volume-less track encountered; "
              "scan more Banks*.pck to exercise that path.")


if __name__ == "__main__":
    main()
