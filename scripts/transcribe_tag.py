#!/usr/bin/env python3
# transcribe_tag.py -- Transcribe audio for all DB entries matching a tag,
# then rename each matching tag to '<Character> "transcribed text"' and add
# an 'autogen' tag.
# Usage:
# python scripts/transcribe_tag.py <tag> [--model tiny|base|small|medium|large]
# Examples:
# python scripts/transcribe_tag.py seed
# python scripts/transcribe_tag.py seed --model small
# Requirements:
# pip install openai-whisper   (or: pipx install openai-whisper)
# vgmstream-cli  (for WEM decoding)
# ffmpeg
# The script reads WEM bytes directly from the DB by hash -- it does NOT need
# the original PCK files.  WEM bytes are stored in the DB via add_sound().
# Wait -- actually the DB only stores hashes + metadata, not the raw bytes.
# So we need the original audio source.  The script will look up file_ids
# from the DB entry, then search for matching .wem files in a provided folder.
# Usage (with WEM folder):
# python scripts/transcribe_tag.py seed /path/to/wem/folder
# python scripts/transcribe_tag.py seed /path/to/wem/folder --model small

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.data.sound_database import SoundDatabase


def find_ffmpeg():
    p = shutil.which("ffmpeg")
    return p


def find_vgmstream():
    p = shutil.which("vgmstream-cli")
    return p


def wem_to_wav(wem_path, vgmstream_path, ffmpeg_path, tmp_dir):
    # Convert a WEM file to a 16kHz mono WAV. Returns Path to WAV or None.
    tmp_wav = Path(tmp_dir) / "audio.wav"
    tmp_pcm = Path(tmp_dir) / "audio_raw.wav"

    # Step 1: vgmstream WEM -> wav
    if vgmstream_path:
        result = subprocess.run(
            [vgmstream_path, "-o", str(tmp_pcm), str(wem_path)],
            capture_output=True, timeout=15,
        )
        if result.returncode != 0 or not tmp_pcm.exists():
            tmp_pcm = wem_path  # fall through to ffmpeg directly
    else:
        tmp_pcm = wem_path

    # Step 2: ffmpeg -> 16kHz mono wav (Whisper expects this)
    result = subprocess.run(
        [ffmpeg_path, "-y", "-i", str(tmp_pcm),
         "-ar", "16000", "-ac", "1", str(tmp_wav)],
        capture_output=True, timeout=15,
    )
    if result.returncode != 0 or not tmp_wav.exists():
        return None
    return tmp_wav


def transcribe(wav_path, model):
    # Run Whisper on a wav file, return transcript string.
    result = model.transcribe(str(wav_path), language="en", fp16=False)
    text = result.get("text", "").strip()
    # Clean up common Whisper artifacts
    text = text.strip("\"'")
    text = " ".join(text.split())
    return text


def main():
    parser = argparse.ArgumentParser(
        description="Transcribe DB entries matching a tag and rename the tag."
    )
    parser.add_argument("tag", help="Tag to search for (e.g. 'seed')")
    parser.add_argument("wem_dir", help="Folder containing the .wem files")
    parser.add_argument(
        "--model",
        default="base",
        choices=["tiny", "base", "small", "medium", "large"],
        help="Whisper model size (default: base)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be done without modifying the DB",
    )
    args = parser.parse_args()

    tag = args.tag.lower()
    wem_dir = Path(args.wem_dir)
    if not wem_dir.is_dir():
        print(f"Error: wem_dir not found: {wem_dir}")
        sys.exit(1)

    ffmpeg_path = find_ffmpeg()
    if not ffmpeg_path:
        print("Error: ffmpeg not found in PATH")
        sys.exit(1)

    vgmstream_path = find_vgmstream()
    if not vgmstream_path:
        print("Warning: vgmstream-cli not found -- WEM decoding may fail for some files")

    # Load Whisper
    try:
        import whisper
    except ImportError:
        print("Error: openai-whisper not installed.")
        print("  pip install openai-whisper")
        sys.exit(1)

    print(f"Loading Whisper model '{args.model}'...")
    model = whisper.load_model(args.model)

    db = SoundDatabase()

    # Find all entries with this exact tag (not substring)
    matches = {h: info for h, info in db.database.items()
               if any(t.lower() == tag for t in info.get("tags", []))}
    if not matches:
        print(f"No entries found with tag '{tag}'")
        sys.exit(0)

    print(f"Found {len(matches)} entries tagged '{tag}'")
    print()

    # Build a lookup: wem_id (int) -> wem file path
    wem_files = {int(p.stem): p for p in wem_dir.glob("*.wem") if p.stem.isdigit()}
    print(f"WEM folder has {len(wem_files)} files")
    print()

    updated = 0
    skipped = 0
    errors = 0

    for sound_hash, info in matches.items():
        # Skip entries that already have a real name
        if info.get("name", "").strip():
            print(f"  [skip] Already named: {info['name']}")
            skipped += 1
            continue

        # Skip entries already transcribed
        if "autogen" in info.get("tags", []):
            print(f"  [skip] Already has autogen tag: {info.get('file_ids', '')}")
            skipped += 1
            continue

        # Find a wem file for this entry
        wem_path = None
        for fid in info.get("file_ids", []):
            try:
                fid_int = int(fid)
            except (ValueError, TypeError):
                continue
            if fid_int in wem_files:
                wem_path = wem_files[fid_int]
                break

        if wem_path is None:
            print(f"  [skip] No WEM file found for file_ids={info.get('file_ids')} -- {info.get('name','')}")
            skipped += 1
            continue

        # Transcribe
        try:
            with tempfile.TemporaryDirectory(prefix="zzar_tr_") as tmp_dir:
                wav = wem_to_wav(wem_path, vgmstream_path, ffmpeg_path, tmp_dir)
                if wav is None:
                    print(f"  [error] Failed to decode {wem_path.name}")
                    errors += 1
                    continue
                text = transcribe(wav, model)
        except Exception as e:
            print(f"  [error] {wem_path.name}: {e}")
            errors += 1
            continue

        if not text:
            print(f"  [skip] Empty transcript for {wem_path.name}")
            skipped += 1
            continue

        # Build name: Seed "transcribed text"
        char_name = tag.capitalize()
        new_name = f'{char_name} "{text}"'

        # Keep all existing tags, just add autogen
        new_tags = list(info.get("tags", []))
        if "autogen" not in new_tags:
            new_tags.append("autogen")

        print(f"  {wem_path.name}  ->  {new_name}")

        if not args.dry_run:
            db.database[sound_hash]["name"] = new_name
            db.database[sound_hash]["tags"] = new_tags

        updated += 1

    if not args.dry_run and updated:
        db.save()

    print()
    print(f"Done.")
    print(f"  Transcribed: {updated}")
    print(f"  Skipped:     {skipped}")
    print(f"  Errors:      {errors}")
    if args.dry_run:
        print("  (dry run -- no changes written)")


if __name__ == "__main__":
    main()
