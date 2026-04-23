

import subprocess
import platform
from pathlib import Path
import shutil
from src.core.config_manager import get_tools_dir
from src.core.subprocess_utils import IS_WINDOWS as _is_windows, SUBPROCESS_KWARGS as _subprocess_kwargs

from src.core.logger import get_logger
logger = get_logger(__name__)

try:
    from src.audio.wwise_wrapper import WwiseConsole
    WWISE_AVAILABLE = True
except ImportError:
    WWISE_AVAILABLE = False

class AudioConverter:


    def __init__(self):

        self.ffmpeg_path = self._find_ffmpeg()
        self.vgmstream_path = self._find_vgmstream()
        self.wwise_console = WwiseConsole() if WWISE_AVAILABLE else None

    def _find_ffmpeg(self):


        if platform.system() == "Windows":

            tools_root = get_tools_dir()
            possible_paths = [
                tools_root / "audio" / "ffmpeg" / "ffmpeg-master-latest-win64-gpl" / "bin" / "ffmpeg.exe",
                tools_root / "audio" / "ffmpeg" / "bin" / "ffmpeg.exe",
            ]

            for local_ffmpeg in possible_paths:
                if local_ffmpeg.exists():
                    return str(local_ffmpeg.resolve())

        ffmpeg = shutil.which('ffmpeg')
        if not ffmpeg:

            if platform.system() == "Windows":
                return None

            raise RuntimeError("FFmpeg not found! Please install: sudo pacman -S ffmpeg")
        return ffmpeg

    def _find_vgmstream(self):


        if platform.system() == "Windows":

            local_vgmstream = get_tools_dir() / "audio" / "vgmstream" / "vgmstream-cli.exe"
            if local_vgmstream.exists():
                return str(local_vgmstream.resolve())

        vgmstream = shutil.which('vgmstream-cli')
        return vgmstream

    def refresh_tools(self):

        self.ffmpeg_path = self._find_ffmpeg()
        self.vgmstream_path = self._find_vgmstream()

    def wem_to_wav(self, wem_file, output_file=None):

        wem_file = Path(wem_file)
        if output_file is None:
            output_file = wem_file.with_suffix('.wav')
        else:
            output_file = Path(output_file)

        if not self.vgmstream_path and not self.ffmpeg_path:
            if platform.system() == "Windows":
                raise RuntimeError(
                    "Audio conversion tools not found.\n\n"
                    "Please install FFmpeg and vgmstream from the Settings page."
                )
            else:
                raise RuntimeError(
                    "Audio conversion tools not found.\n\n"
                    "Please install vgmstream-cli and ffmpeg:\n"
                    "  Arch Linux: sudo pacman -S vgmstream ffmpeg\n"
                    "  Ubuntu/Debian: sudo apt install vgmstream-cli ffmpeg"
                )

        if self.vgmstream_path:
            try:
                subprocess.run([
                    self.vgmstream_path,
                    '-o', str(output_file),
                    str(wem_file)
                ], check=True, capture_output=True, **_subprocess_kwargs)
                logger.info(f"Converted (vgmstream): {wem_file.name} -> {output_file.name}")
                return output_file
            except subprocess.CalledProcessError as e:
                logger.error(f"vgmstream failed, trying FFmpeg...")

        if self.ffmpeg_path:
            try:
                subprocess.run([
                    self.ffmpeg_path,
                    '-i', str(wem_file),
                    '-acodec', 'pcm_s16le',
                    '-ar', '48000',
                    '-y',
                    str(output_file)
                ], check=True, capture_output=True, text=True, **_subprocess_kwargs)
                logger.info(f"Converted (ffmpeg): {wem_file.name} -> {output_file.name}")
                return output_file
            except subprocess.CalledProcessError as e:
                pass

        if platform.system() == "Windows":
            raise RuntimeError(
                f"\n=== Failed to convert {wem_file.name} ===\n"
                f"WEM files require vgmstream-cli for conversion.\n\n"
                f"Please install the audio tools from the Settings page.\n"
            )
        else:
            raise RuntimeError(
                f"\n=== Failed to convert {wem_file.name} ===\n"
                f"WEM files use a custom Wwise audio format that requires vgmstream-cli.\n\n"
                f"Install vgmstream-cli:\n"
                f"  Arch Linux (AUR): yay -S vgmstream-cli-bin\n"
                f"  Ubuntu/Debian:    sudo apt install vgmstream-cli\n"
                f"  Or build from:    https://github.com/vgmstream/vgmstream\n\n"
                f"FFmpeg cannot decode this WEM file format.\n"
            )

    def any_to_wav(self, input_file, output_file=None, sample_rate=48000, channels=2, normalize=True, normalize_lufs=-9):

        input_file = Path(input_file)
        if output_file is None:
            candidate = input_file.with_suffix('.wav')
            if candidate == input_file:
                import tempfile
                tmp = tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
                tmp.close()
                output_file = Path(tmp.name)
            else:
                output_file = candidate
        else:
            output_file = Path(output_file)

        if not self.ffmpeg_path:
            if platform.system() == "Windows":
                raise RuntimeError(
                    "FFmpeg not found.\n\n"
                    "Please install the audio tools from the Settings page."
                )
            else:
                raise RuntimeError(
                    "FFmpeg not found.\n\n"
                    "Please install ffmpeg:\n"
                    "  Arch Linux: sudo pacman -S ffmpeg\n"
                    "  Ubuntu/Debian: sudo apt install ffmpeg"
                )

        try:
            if normalize:
                # Pass 1: measure integrated loudness
                measure_cmd = [
                    self.ffmpeg_path,
                    '-i', str(input_file),
                    '-af', f'loudnorm=I={normalize_lufs}:TP=-1.5:LRA=11:print_format=json',
                    '-f', 'null', '-'
                ]
                result = subprocess.run(
                    measure_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                    **_subprocess_kwargs
                )
                stderr_text = result.stderr.decode('utf-8', errors='replace')
                # Extract measured values from JSON block in stderr
                import re as _re
                json_match = _re.search(r'\{[^{}]+\}', stderr_text, _re.DOTALL)
                if json_match:
                    import json as _json
                    measured = _json.loads(json_match.group())
                    af = (
                        f"loudnorm=I={normalize_lufs}:TP=-1.5:LRA=11:linear=true"
                        f":measured_I={measured['input_i']}"
                        f":measured_TP={measured['input_tp']}"
                        f":measured_LRA={measured['input_lra']}"
                        f":measured_thresh={measured['input_thresh']}"
                        f":offset={measured['target_offset']}"
                    )
                else:
                    # Fallback to single-pass dynamic if parse fails
                    af = f'loudnorm=I={normalize_lufs}:TP=-1.5:LRA=11'
            else:
                af = None

            cmd = [self.ffmpeg_path, '-i', str(input_file)]
            if af:
                cmd.extend(['-af', af])
            cmd.extend([
                '-acodec', 'pcm_f32le',
                '-ar', str(sample_rate),
                '-ac', str(channels),
                '-y',
                str(output_file)
            ])

            result = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, **_subprocess_kwargs)
            if result.returncode != 0:
                stderr_msg = result.stderr.decode('utf-8', errors='replace').strip()
                # Extract the last meaningful line from ffmpeg stderr
                lines = [l for l in stderr_msg.splitlines() if l.strip()]
                short_reason = lines[-1] if lines else "unknown error"
                raise RuntimeError(f"FFmpeg failed to convert {input_file.name}: {short_reason}")
            norm_msg = f" (normalized to {normalize_lufs} LUFS)" if normalize else ""
            logger.info(f"Converted: {input_file.name} -> {output_file.name}{norm_msg}")
            return output_file
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to convert {input_file}: {e}")

    def wav_to_wem(self, wav_file, output_file=None, wwise_dir=None, normalize=False, normalize_lufs=-9):

        wav_file = Path(wav_file)

        if not WWISE_AVAILABLE or not self.wwise_console:
            raise RuntimeError(
                "Wwise is not installed.\n\n"
                "Please install Wwise from the Settings page to convert WAV files to WEM format."
            )

        if wwise_dir:
            wwise = WwiseConsole(wwise_dir)
        else:
            wwise = self.wwise_console

        if not wwise.is_installed():
            raise RuntimeError(
                "Wwise is not installed.\n\n"
                "Please install Wwise from the Settings page to convert WAV files to WEM format."
            )

        if output_file is None:
            output_dir = wav_file.parent
        else:
            output_file = Path(output_file)
            output_dir = output_file.parent

        try:
            if normalize:
                import tempfile
                with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp:
                    tmp_path = Path(tmp.name)
                try:
                    self.any_to_wav(wav_file, tmp_path, normalize=True, normalize_lufs=normalize_lufs)
                    result_wem = wwise.convert_to_wem(tmp_path, output_dir)
                    # Wwise names output after the input stem -- rename to match original
                    expected = output_dir / (tmp_path.stem + '.wem')
                    target = output_dir / (wav_file.stem + '.wem')
                    if expected.exists() and expected != target:
                        expected.rename(target)
                        result_wem = target
                finally:
                    tmp_path.unlink(missing_ok=True)
            else:
                result_wem = wwise.convert_to_wem(wav_file, output_dir)

            if output_file and result_wem != output_file:
                result_wem.rename(output_file)
                return output_file

            return result_wem

        except Exception as e:
            raise RuntimeError(f"Failed to convert {wav_file.name} to .wem: {e}")

    def batch_convert_wem_to_wav(self, input_dir, output_dir=None):

        input_dir = Path(input_dir)
        if output_dir is None:
            output_dir = input_dir / 'wav'
        else:
            output_dir = Path(output_dir)

        output_dir.mkdir(parents=True, exist_ok=True)

        wem_files = list(input_dir.glob('*.wem'))
        converted = []

        logger.info(f"\nConverting {len(wem_files)} .wem files to .wav...")

        for i, wem_file in enumerate(wem_files):
            try:
                output_file = output_dir / wem_file.with_suffix('.wav').name
                self.wem_to_wav(wem_file, output_file)
                converted.append(output_file)
            except Exception as e:
                logger.error(f"[{i+1}/{len(wem_files)}] Error: {e}")

        logger.info(f"\nConverted {len(converted)}/{len(wem_files)} files")
        return converted

    def batch_convert_to_wav(self, input_dir, output_dir=None, pattern='*', normalize=True, normalize_lufs=-9):

        input_dir = Path(input_dir)
        if output_dir is None:
            output_dir = input_dir / 'wav'
        else:
            output_dir = Path(output_dir)

        output_dir.mkdir(parents=True, exist_ok=True)

        audio_extensions = ['.mp3', '.flac', '.ogg', '.m4a', '.aac', '.opus', '.wma']
        audio_files = []

        for ext in audio_extensions:
            audio_files.extend(input_dir.glob(f'*{ext}'))

        converted = []

        logger.info(f"\nConverting {len(audio_files)} audio files to .wav...")

        for i, audio_file in enumerate(audio_files):
            try:
                output_file = output_dir / audio_file.with_suffix('.wav').name
                self.any_to_wav(audio_file, output_file, normalize=normalize, normalize_lufs=normalize_lufs)
                converted.append(output_file)
            except Exception as e:
                logger.error(f"[{i+1}/{len(audio_files)}] Error: {e}")

        logger.info(f"\nConverted {len(converted)}/{len(audio_files)} files")
        return converted

    def batch_convert_wav_to_wem(self, input_dir, output_dir=None, normalize=False, normalize_lufs=-9):

        input_dir = Path(input_dir)
        if output_dir is None:
            output_dir = input_dir / 'wem'
        else:
            output_dir = Path(output_dir)

        output_dir.mkdir(parents=True, exist_ok=True)

        if not WWISE_AVAILABLE or not self.wwise_console or not self.wwise_console.is_installed():
            raise RuntimeError(
                "Wwise is not installed.\n\n"
                "Please install Wwise from the Settings page to convert WAV files to WEM format."
            )

        wav_files = list(input_dir.glob('*.wav'))

        if not wav_files:
            logger.info(f"No .wav files found in {input_dir}")
            return []

        if not normalize:
            return self.wwise_console.batch_convert_to_wem(wav_files, output_dir)

        converted = []
        for wav_file in wav_files:
            try:
                self.wav_to_wem(wav_file, output_dir / wav_file.with_suffix('.wem').name,
                                normalize=True, normalize_lufs=normalize_lufs)
                converted.append(output_dir / wav_file.with_suffix('.wem').name)
            except Exception as e:
                logger.error(f"Error converting {wav_file.name}: {e}")
        return converted

def main():

    import sys

    if len(sys.argv) < 2:
        logger.info("Usage: python audio_converter.py <input_file_or_dir> [output] [--mode=MODE]")
        logger.info("")
        logger.info("Modes:")
        logger.info("  wem2wav  - Convert .wem to .wav (default)")
        logger.info("  any2wav  - Convert any audio format to .wav")
        logger.info("  wav2wem  - Convert .wav to .wem (requires Wwise)")
        logger.info("")
        logger.info("Examples:")
        logger.info("  python audio_converter.py extracted/")
        logger.info("  python audio_converter.py my_audio.mp3 output.wav")
        logger.info("  python audio_converter.py music_folder/ ./wav --mode=any2wav")
        logger.info("  python audio_converter.py audio.wav --mode=wav2wem")
        logger.info("  python audio_converter.py wav_folder/ ./wem --mode=wav2wem")
        sys.exit(1)

    input_path = Path(sys.argv[1])
    output_path = sys.argv[2] if len(sys.argv) > 2 and not sys.argv[2].startswith('--') else None

    mode = 'wem2wav'
    for arg in sys.argv:
        if arg.startswith('--mode='):
            mode = arg.split('=')[1]

    converter = AudioConverter()

    try:
        if input_path.is_dir():
            if mode == 'wav2wem':
                converter.batch_convert_wav_to_wem(input_path, output_path)
            elif mode in ['any2wav', 'mp32wav']:
                converter.batch_convert_to_wav(input_path, output_path)
            else:
                converter.batch_convert_wem_to_wav(input_path, output_path)
        else:

            if mode == 'wav2wem' or input_path.suffix == '.wav':
                converter.wav_to_wem(input_path, output_path)
            elif input_path.suffix == '.wem':
                converter.wem_to_wav(input_path, output_path)
            else:
                converter.any_to_wav(input_path, output_path)
    except Exception as e:
        logger.error(f"\n[X] Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
