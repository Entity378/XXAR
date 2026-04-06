# Converts all .wem files in a folder (recursively) to wav/mp3/ogg
# Usage: python scripts/convert_wems.py <input_dir> [--format wav|mp3|ogg] [--output dir]

import sys
import argparse
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.audio.converter import AudioConverter


def convert_wems(input_dir, output_dir, fmt):
    input_dir = Path(input_dir)
    output_dir = Path(output_dir)

    converter = AudioConverter()
    if not converter.vgmstream_path and not converter.ffmpeg_path:
        print("Error: vgmstream or ffmpeg not found. Install from Settings or add to PATH.")
        sys.exit(1)

    wem_files = list(input_dir.rglob("*.wem"))
    if not wem_files:
        print(f"No .wem files found in {input_dir}")
        return

    print(f"Converting {len(wem_files)} WEM(s) to {fmt}...")

    converted = 0
    failed = 0

    for wem in wem_files:
        rel = wem.relative_to(input_dir)
        out_path = output_dir / rel.with_suffix(f".{fmt}")
        out_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            if fmt == "wav":
                converter.wem_to_wav(str(wem), str(out_path))
            else:
                # wem -> wav -> target format via ffmpeg
                wav_tmp = out_path.with_suffix(".wav")
                converter.wem_to_wav(str(wem), str(wav_tmp))

                if not converter.ffmpeg_path:
                    print(f"  Skip {rel}: ffmpeg needed for {fmt} conversion")
                    failed += 1
                    continue

                import subprocess
                subprocess.run(
                    [converter.ffmpeg_path, "-y", "-i", str(wav_tmp), "-q:a", "2", str(out_path)],
                    check=True, capture_output=True,
                )
                wav_tmp.unlink()

            converted += 1
        except Exception as e:
            print(f"  Failed {rel}: {e}")
            failed += 1

    print(f"\nDone: {converted} converted, {failed} failed -> {output_dir}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Convert WEM files to playable audio")
    parser.add_argument("input_dir", help="Folder with .wem files (searched recursively)")
    parser.add_argument("--format", "-f", choices=["wav", "mp3", "ogg"], default="wav")
    parser.add_argument("--output", "-o", help="Output folder (default: <input_dir>_<format>)")
    args = parser.parse_args()

    out = args.output or f"{args.input_dir}_{args.format}"
    convert_wems(args.input_dir, out, args.format)
