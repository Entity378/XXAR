# transcribe_tag.py — Tutorial

This script finds all DB entries with a given tag, transcribes each one using Whisper, and renames the tag to `Character "transcribed text"`, adding an `autogen` tag. Entries that already have a name or already have `autogen` are skipped.

## Requirements

```
pipx install openai-whisper   # or: pip install openai-whisper (in a venv)
ffmpeg                        # for audio conversion
vgmstream-cli                 # for WEM decoding (optional but recommended)
```

> **Arch Linux note:** Use `pipx install openai-whisper` then run the script inside a venv where whisper is also installed, or use `python -m venv .venv && source .venv/bin/activate && pip install openai-whisper`.

---

## Basic usage

```
python scripts/transcribe_tag.py <tag> <wem_dir>
```

**Example:**

```
python scripts/transcribe_tag.py seed /home/user/Downloads/diff_audio_en_2.2

  pipx run --spec openai-whisper python transcribe_tag.py "alice" /home/pucas01/Downloads/ZZZ_Audio_Stuff/diff_audio_en_2.2

```

This will:
1. Find all DB entries tagged `seed`
2. Match them to `.wem` files in the given folder by file ID
3. Transcribe each one with Whisper
4. Replace the `seed` tag with `Seed "transcribed text"`
5. Add the `autogen` tag

---

## Dry run (no DB changes)

```
python scripts/transcribe_tag.py seed /path/to/wem_dir --dry-run
```

Prints what would happen without writing anything to the DB.

---

## Model size

```
python scripts/transcribe_tag.py seed /path/to/wem_dir --model small
```

Available sizes: `tiny`, `base` (default), `small`, `medium`, `large`. Larger models are slower but more accurate.

---

## Where to get the WEM files

Use `audio_diff.py` to extract and diff game audio first (see `audio_diff_tutorial.md`). The diff output folder works directly as the `wem_dir` argument.

---

## Output

Each processed entry gets its bare tag replaced:

```
seed  →  Seed "Wait, you're not from here either?"
```

And an `autogen` tag is added so you can find all auto-transcribed entries later.

Entries are skipped if:
- They already have a name set
- They already have the `autogen` tag
