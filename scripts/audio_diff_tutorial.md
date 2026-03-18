# audio_diff.py — Tutorial

This script extracts voice WEMs from ZZZ SoundBank PCK files and finds what changed between two game versions. Useful for figuring out which audio files were added or re-recorded in a patch.

## Basic workflow

**Step 1 — Extract the newer version**

```
python scripts/audio_diff.py extract /path/to/v2.2/En  audio_en_2.2
```

**Step 2 — Extract the older version**

```
python scripts/audio_diff.py extract /path/to/v2.1/En  audio_en_2.1
```

**Step 3 — Get only the changed files**

```
python scripts/audio_diff.py diff audio_en_2.2 audio_en_2.1 diff_audio_en_2.2
```

The `diff_audio_en_2.2` folder will contain only WEMs that are new or different in 2.2. A `diff_summary.json` is written there too with the full lists of added/changed/removed IDs.

---

## All-in-one shortcut

If you haven't extracted yet and just want the diff in one shot:

```
python scripts/audio_diff.py auto /path/to/v2.2/En /path/to/v2.1/En diff_audio_en_2.2
```

This extracts both versions (saved as `extracted_new_audio_en_2.2/` and `extracted_old_audio_en_2.2/` next to the diff folder) then diffs them. Re-running `extract` later is incremental — files that already exist with the same content are skipped.

---

## Where to find the PCK directory

Inside the game install or a downloaded audio zip, navigate to:

```
ZenlessZoneZero_Data/StreamingAssets/Audio/Windows/Full/En/
```

That folder is the `<pck_dir>` argument. The script only reads `SoundBank_*.pck` files from it.

---

## Output

- `<out_dir>/` — flat folder of `<wem_id>.wem` files
- `<diff_dir>/` — only the new/changed WEMs from the newer version
- `<diff_dir>/diff_summary.json` — lists of added, changed, and removed WEM IDs

Removed WEMs (present in old but gone in new) are listed in the summary JSON but not copied anywhere, since there's nothing to copy.
