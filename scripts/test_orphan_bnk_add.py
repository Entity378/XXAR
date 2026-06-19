# Structural test for the orphan-BNK apply fix (read-only on the game).
# Adds a real Patch.pck-only BNK into a copy of a SoundBank pck via PCKPacker.add_bnk_raw, merges a
# replacement WEM into it, rebuilds to a temp file, and asserts: the pck re-indexes, the bank id set
# is exactly original + the orphan, every pre-existing bank is byte-identical, and the added bank
# re-parses with the merged WEM. Never writes to the game install.
#
#   python scripts/test_orphan_bnk_add.py
import json
import logging
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.wwise.bnk_handler import BNKFile
from src.wwise.pck_indexer import PCKIndexer
from src.wwise.pck_packer import PCKPacker

ORPHAN_BNK = 2247887612  # ZZZ: 713-WEM container that lives only in Patch.pck


def paths():
    d = json.loads((Path(os.environ["APPDATA"]) / "XXAR" / "settings.json").read_text(encoding="utf-8"))
    audio = Path(d["game_audio_dir"])
    streaming = audio
    persistent = Path(d["persistent_audio_dir"])
    host = streaming / "SoundBank_SFX_8.pck"
    patch = persistent / "Patch.pck"
    backup = persistent / "Patch.pck.xxar_backup"
    return host, (backup if backup.exists() else patch)


def extract_bank_map(pck_path):
    idx = PCKIndexer(str(pck_path)).build_index()
    raw = Path(pck_path).read_bytes()
    return {b["id"]: raw[b["offset"]:b["offset"] + b["size"]] for b in idx["banks"]}, idx


def main():
    logging.getLogger("xxar").setLevel(logging.WARNING)
    host, patch = paths()
    if not host.exists() or not patch.exists():
        print(f"missing host/patch: {host} | {patch}")
        sys.exit(1)

    # Extract the orphan BNK bytes + lang from Patch.pck.
    pidx = PCKIndexer(str(patch)).build_index()
    bank = next((b for b in pidx["banks"] if b["id"] == ORPHAN_BNK), None)
    if bank is None:
        print(f"orphan BNK {ORPHAN_BNK} not found in {patch.name}")
        sys.exit(3)
    praw = patch.read_bytes()
    orphan_bytes = praw[bank["offset"]:bank["offset"] + bank["size"]]
    lang_id = bank["lang_id"]
    orphan_bnk = BNKFile(bnk_bytes=orphan_bytes)
    wem_ids = list(orphan_bnk.list_wems())
    target_wem = wem_ids[0]
    replacement = b"RIFFXXARtestwem" + bytes(2000)  # arbitrary bytes; merge just stores them
    print(f"host={host.name} orphan={ORPHAN_BNK} ({len(orphan_bytes):,} B, {len(wem_ids)} WEMs, lang={lang_id})")

    orig_banks, _ = extract_bank_map(host)
    assert ORPHAN_BNK not in orig_banks, "orphan must not pre-exist in host (test premise)"

    out_dir = Path(tempfile.mkdtemp(prefix="xxar_orphan_"))
    target = out_dir / host.name
    try:
        packer = PCKPacker(str(host), str(target))
        packer.load_original_pck()
        assert packer.add_bnk_raw(ORPHAN_BNK, orphan_bytes, lang_id=lang_id), "add_bnk_raw failed"
        assert not packer.add_bnk_raw(ORPHAN_BNK, orphan_bytes, lang_id=lang_id), "add_bnk_raw must reject a duplicate"
        packer.merge_bnk_wems(ORPHAN_BNK, {target_wem: replacement}, lang_id=lang_id)
        packer.pack(use_patching=False)
        packer.close()

        new_banks, new_idx = extract_bank_map(target)

        # 1) id set == original + orphan
        assert set(new_banks) == set(orig_banks) | {ORPHAN_BNK}, "bank id set mismatch"

        # 2) every pre-existing bank byte-identical
        for bid, b in orig_banks.items():
            assert new_banks[bid] == b, f"bank {bid} mutated"

        # 3) orphan bank re-parses and the merged WEM now holds the replacement
        rt = BNKFile(bnk_bytes=new_banks[ORPHAN_BNK])
        assert target_wem in rt.list_wems(), "merged WEM id missing after rebuild"
        assert rt.extract_wem(target_wem) == replacement, "merged WEM bytes not applied"
        assert len(list(rt.list_wems())) == len(wem_ids), "orphan WEM count changed"

        print(f"PASS: added orphan BNK ({len(orig_banks)} banks untouched), merged WEM {target_wem} -> {len(replacement)} B")
    finally:
        try:
            target.unlink(missing_ok=True)
            out_dir.rmdir()
        except Exception:
            pass


if __name__ == "__main__":
    main()
