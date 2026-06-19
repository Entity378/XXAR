# End-to-end structural test for the Phase-2 volume-insert REBUILD path (read-only on the game).
# Rebuilds a real pck into a temp file via BaseBrowserHandler._rebuild_pck_with_hirc_patches,
# then asserts: the pck re-indexes, patched bnks gained exactly +5 bytes per inserted track and
# now carry the Volume prop, and every OTHER bank/wem is byte-identical to the original.
#
#   python scripts/test_pck_rebuild.py [pck_path]
import json
import logging
import os
import struct
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.gui.backend.audio_games.base_handler import BaseBrowserHandler
from src.wwise import hirc_patcher as hp
from src.wwise.bnk_handler import BNKFile
from src.wwise.pck_indexer import PCKIndexer

HIRC_TYPE_MUSIC_TRACK = 0x0B
TEST_DB = -4.5


def default_pck():
    settings = Path(os.environ["APPDATA"]) / "XXAR" / "settings.json"
    d = json.loads(settings.read_text(encoding="utf-8"))
    audio = Path(d.get("game_audio_dir", ""))
    banks = sorted(audio.glob("Banks*.pck"))
    # Banks1 has a bnk with two volume-less tracks (empty + non-empty bundle).
    for b in banks:
        if b.name == "Banks1.pck":
            return b
    return banks[0] if banks else None


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


def volume_less_sources(bnk_bytes):
    # Sources of MusicTracks in this bnk that currently LACK a Volume prop.
    try:
        bnk = BNKFile(bnk_bytes=bnk_bytes)
    except Exception:
        return set()
    if "HIRC" not in bnk.data:
        return set()
    buf = bytearray(bnk.data["HIRC"].getdata())
    srcs = music_sources(buf)
    if not srcs:
        return set()
    targets = hp.scan_bank_for_patch_targets(buf, srcs)
    return {vp.source_id for vp in targets.volume_patches if not vp.has_existing_volume}


def expected_inserts(bnk_bytes, srcs):
    # Mirror apply_volume_inserts' dedup: one insert per distinct AkPropBundle (cProps offset).
    bnk = BNKFile(bnk_bytes=bnk_bytes)
    buf = bytearray(bnk.data["HIRC"].getdata())
    targets = hp.scan_bank_for_patch_targets(buf, srcs)
    bundles = {vp.prop_bundle_cProps_offset
               for vp in targets.volume_patches if not vp.has_existing_volume}
    return len(bundles)


def extract_map(pck_path):
    idx = PCKIndexer(pck_path)
    index = idx.build_index()
    data = pck_path.read_bytes()
    banks = {b["id"]: data[b["offset"]:b["offset"] + b["size"]] for b in index["banks"]}
    sounds = {s["id"]: (s["offset"], s["size"]) for s in index["sounds"]}
    return banks, sounds, data


def main():
    logging.getLogger("xxar").setLevel(logging.WARNING)
    pck = Path(sys.argv[1]) if len(sys.argv) > 1 else default_pck()
    if not pck or not pck.exists():
        print(f"pck not found: {pck}")
        sys.exit(1)
    print(f"pck: {pck.name}")

    orig_banks, orig_sounds, raw = extract_map(pck)
    print(f"banks={len(orig_banks)} sounds={len(orig_sounds)}")

    # Pick the bnk with the most volume-less music tracks.
    best_bnk, best_srcs = None, set()
    for bnk_id, bnk_bytes in orig_banks.items():
        vls = volume_less_sources(bnk_bytes)
        if len(vls) > len(best_srcs):
            best_bnk, best_srcs = bnk_id, vls
    if not best_srcs:
        print("No volume-less MusicTrack found in this pck.")
        sys.exit(3)
    print(f"target bnk {best_bnk}: {len(best_srcs)} volume-less track(s) -> inserting {TEST_DB} dB")

    source_ids = set(best_srcs)
    vol_map = {s: TEST_DB for s in best_srcs}
    dur_map = {}
    patched = set()

    out_dir = Path(tempfile.mkdtemp(prefix="xxar_rebuild_"))
    target = out_dir / pck.name
    try:
        ok = BaseBrowserHandler._rebuild_pck_with_hirc_patches(
            raw, target, pck, source_ids, dur_map, vol_map, patched
        )
        assert ok, "rebuild returned False"
        assert target.exists(), "no output pck written"

        new_banks, new_sounds, _ = extract_map(target)

        # 1) same id sets
        assert set(new_banks) == set(orig_banks), "bank id set changed"
        assert set(new_sounds) == set(orig_sounds), "sound id set changed"

        # 2) exactly the target bnk changed; everything else byte-identical
        changed = [bid for bid in orig_banks if new_banks[bid] != orig_banks[bid]]
        assert changed == [best_bnk], f"unexpected changed banks: {changed}"
        for bid in orig_banks:
            if bid != best_bnk:
                assert new_banks[bid] == orig_banks[bid], f"bank {bid} mutated"

        # 3) target bnk grew by exactly +5 per inserted track (a source may appear in several
        #    tracks, so growth is keyed on distinct bundles, not source count) and re-parses
        want = 5 * expected_inserts(orig_banks[best_bnk], best_srcs)
        grew = len(new_banks[best_bnk]) - len(orig_banks[best_bnk])
        assert grew == want, f"grew {grew}, want {want}"
        rt = BNKFile(bnk_bytes=new_banks[best_bnk])
        assert rt.get_bytes() == new_banks[best_bnk], "patched bnk not stable"

        # 4) each patched source now carries Volume reading back TEST_DB
        buf = bytearray(rt.data["HIRC"].getdata())
        targets = hp.scan_bank_for_patch_targets(buf, best_srcs)
        seen = {}
        for vp in targets.volume_patches:
            if vp.source_id in best_srcs and vp.has_existing_volume:
                seen[vp.source_id] = struct.unpack_from("<f", buf, vp.volume_value_offset)[0]
        for s in best_srcs:
            assert s in seen, f"source 0x{s:08X} has no volume after rebuild"
            assert abs(seen[s] - TEST_DB) < 1e-6, f"vol {seen[s]} != {TEST_DB}"

        # 5) all WEM payloads identical (sounds carry the audio; rebuild must not touch them)
        new_raw = target.read_bytes()
        for sid, (ooff, osz) in orig_sounds.items():
            noff, nsz = new_sounds[sid]
            assert raw[ooff:ooff + osz] == new_raw[noff:noff + nsz], f"wem {sid} changed"

        print(f"PASS: 1 bnk patched (+{grew} bytes, {grew // 5} volume(s) inserted), "
              f"{len(orig_banks)-1} banks + {len(orig_sounds)} wems byte-identical")
    finally:
        try:
            target.unlink(missing_ok=True)
            out_dir.rmdir()
        except Exception:
            pass


if __name__ == "__main__":
    main()
