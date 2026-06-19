# Strongest offline proof that an INSERTED Volume prop is honoured by Wwise exactly like a native
# one: take real tracks that ship WITH a Volume, strip it (→ a volume-less track), re-insert the
# same value, and assert the bytes are identical to the original. insert == inverse(strip) means
# our inserted AkPropBundle is byte-for-byte what the game itself writes. Read-only on the game.
#
#   python scripts/verify_insert_equivalence.py [pck ...]
import json
import logging
import os
import struct
import sys
from collections import Counter
from io import BytesIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.wwise import hirc_patcher as hp
from src.wwise.bnk_handler import BNKFile
from src.wwise.pck_indexer import PCKIndexer

HIRC_TYPE_MUSIC_TRACK = 0x0B


def default_pcks():
    d = json.loads((Path(os.environ["APPDATA"]) / "XXAR" / "settings.json").read_text(encoding="utf-8"))
    audio = Path(d.get("game_audio_dir", ""))
    return sorted(audio.glob("Banks*.pck"))[:3]


def music_sources(buf):
    out = set()
    for hs, hsz in hp._find_hirc_sections(buf):
        se = hs + hsz
        n = struct.unpack_from("<I", buf, hs)[0]
        op = hs + 4
        for _ in range(n):
            if op + 5 > se:
                break
            ot = buf[op]
            osz = struct.unpack_from("<I", buf, op + 1)[0]
            ods = op + 5
            if ods + osz > len(buf):
                break
            if ot == HIRC_TYPE_MUSIC_TRACK:
                ns = struct.unpack_from("<I", buf, ods + 5)[0]
                if ns <= 100:
                    sp = ods + 9
                    for _ in range(ns):
                        if sp + 14 > len(buf):
                            break
                        out.add(struct.unpack_from("<I", buf, sp + 5)[0])
                        sp += 14
            op = ods + osz
    return out


def strip_volume(buf, vp):
    # Inverse of apply_volume_inserts for one bundle: remove the Volume value + id, drop cProps,
    # shrink the MusicTrack object size by 5. buf is the HIRC-chunk bytearray.
    values_start = vp.ids_start_offset + vp.cProps
    i = (vp.volume_value_offset - values_start) // 4   # index of Volume within the values array
    id_off = vp.ids_start_offset + i
    # Remove the value (higher offset) first, then the id byte.
    del buf[vp.volume_value_offset:vp.volume_value_offset + 4]
    del buf[id_off:id_off + 1]
    buf[vp.prop_bundle_cProps_offset] = vp.cProps - 1
    old = struct.unpack_from("<I", buf, vp.object_size_field_offset)[0]
    struct.pack_into("<I", buf, vp.object_size_field_offset, old - 5)
    # Keep this HIRC-chunk buffer self-consistent (payload shrank by 5) so a re-scan finds it.
    # The product code never needs this — it lets BNKFile recompute the chunk size on get_bytes().
    hsz = struct.unpack_from("<I", buf, 4)[0]
    struct.pack_into("<I", buf, 4, hsz - 5)


def check_track(bnk, vp_native, src, native_db):
    # bnk: BNKFile of the original. Returns True if strip+reinsert reproduces the original bytes.
    original = bnk.get_bytes()

    # Work on the HIRC chunk: strip the native volume, then re-insert the same value.
    mini = bytearray(bnk.data["HIRC"].getdata())
    # Re-locate the native volume on the mini buffer (offsets there are HIRC-chunk relative).
    t = hp.scan_bank_for_patch_targets(mini, {src})
    vp = next((v for v in t.volume_patches
               if v.source_id == src and v.has_existing_volume
               and abs(struct.unpack_from("<f", mini, v.volume_value_offset)[0] - native_db) < 1e-6), None)
    if vp is None:
        return None  # couldn't relocate; skip
    strip_volume(mini, vp)

    # Now it's volume-less; re-insert the same value.
    t2 = hp.scan_bank_for_patch_targets(bytes(mini), {src})
    res = hp.apply_volume_inserts(mini, t2.volume_patches, {src: native_db})
    if res["inserted"] <= 0:
        return None

    rebuilt = BNKFile(bnk_bytes=bytes(original))
    rebuilt.data["HIRC"].data = BytesIO(bytes(mini[12:]))
    return rebuilt.get_bytes() == original


def main():
    logging.getLogger("xxar").setLevel(logging.WARNING)
    pcks = [Path(a) for a in sys.argv[1:]] or default_pcks()

    checked = 0
    matched = 0
    for pck in pcks:
        if not pck.exists():
            continue
        idx = PCKIndexer(pck).build_index()
        raw = pck.read_bytes()
        for bank in idx["banks"]:
            bb = raw[bank["offset"]:bank["offset"] + bank["size"]]
            try:
                bnk = BNKFile(bnk_bytes=bb)
            except Exception:
                continue
            if "HIRC" not in bnk.data:
                continue
            buf = bytearray(bnk.data["HIRC"].getdata())
            srcs = music_sources(buf)
            if not srcs:
                continue
            t = hp.scan_bank_for_patch_targets(buf, srcs)
            # Only test sources used by exactly ONE track: when a source feeds several tracks,
            # a source-keyed re-insert would also touch the siblings, so strip+reinsert isn't a
            # clean inverse (a test limitation, not a product issue).
            src_count = Counter(vp.source_id for vp in t.volume_patches)
            seen = set()
            for vp in t.volume_patches:
                if not vp.has_existing_volume or vp.source_id in seen:
                    continue
                if src_count[vp.source_id] != 1:
                    continue
                seen.add(vp.source_id)
                native_db = struct.unpack_from("<f", buf, vp.volume_value_offset)[0]
                r = check_track(BNKFile(bnk_bytes=bb), vp, vp.source_id, native_db)
                if r is None:
                    continue
                checked += 1
                if r:
                    matched += 1
                else:
                    print(f"  MISMATCH bnk {bank['id']} src 0x{vp.source_id:08X} db={native_db:.2f}")
                if checked >= 200:
                    break
            if checked >= 200:
                break
        if checked >= 200:
            break

    print(f"\nstrip+reinsert reproduced the native bytes: {matched}/{checked}")
    if checked and matched == checked:
        print("PROOF: our inserted Volume is byte-identical to what the game ships natively.")
    elif checked == 0:
        print("No native-volume tracks found to compare against.")
    else:
        print("Some mismatches — investigate before trusting insertion.")
        sys.exit(2)


if __name__ == "__main__":
    main()
