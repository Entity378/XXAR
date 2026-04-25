import numpy as np
from scipy import signal
from scipy.ndimage import maximum_filter

from src.core.logger import get_logger
logger = get_logger(__name__)


SAMPLE_RATE = 48000
N_FFT = 4096
HOP = 2048

PEAK_TIME_WINDOW = 21
PEAK_FREQ_WINDOW = 3
PEAK_PERCENTILE = 85
PEAKS_PER_SECOND = 8

FAN_OUT = 3
DT_MIN_S = 0.1
DT_MAX_S = 3.0
DF_MAX_OCTAVES = 1.0

FREQ_BITS = 10
DT_BITS = 12
FREQ_Q_MAX = (1 << FREQ_BITS) - 1
DT_Q_MAX = (1 << DT_BITS) - 1


def extract_hashes(audio_data, sample_rate=SAMPLE_RATE):
    if audio_data is None or len(audio_data) < N_FFT:
        return []

    f, t, Sxx = signal.spectrogram(
        audio_data, sample_rate,
        nperseg=N_FFT, noverlap=N_FFT - HOP,
        window='hann', mode='magnitude',
    )
    if Sxx.size == 0:
        return []

    footprint = np.ones((PEAK_FREQ_WINDOW, PEAK_TIME_WINDOW))
    local_max = maximum_filter(Sxx, footprint=footprint, mode='constant', cval=0.0)
    peak_mask = (Sxx == local_max) & (Sxx > 0)

    if not peak_mask.any():
        return []

    thresh = np.percentile(Sxx[peak_mask], PEAK_PERCENTILE)
    peak_mask &= (Sxx >= thresh)

    f_idx, t_idx = np.nonzero(peak_mask)
    if len(f_idx) == 0:
        return []

    if PEAKS_PER_SECOND > 0:
        mags = Sxx[f_idx, t_idx]
        bucket = t[t_idx].astype(int)
        keep = np.ones(len(f_idx), dtype=bool)
        for b in np.unique(bucket):
            idx_in = np.where(bucket == b)[0]
            if len(idx_in) > PEAKS_PER_SECOND:
                bucket_mags = mags[idx_in]
                drop = idx_in[np.argsort(-bucket_mags)[PEAKS_PER_SECOND:]]
                keep[drop] = False
        f_idx = f_idx[keep]
        t_idx = t_idx[keep]
        if len(f_idx) == 0:
            return []

    order = np.lexsort((f_idx, t_idx))
    f_idx = f_idx[order]
    t_idx = t_idx[order]

    peak_times_s = t[t_idx]
    peak_freqs_hz = f[f_idx]

    nyquist = sample_rate / 2.0
    q_freqs = np.clip(
        (peak_freqs_hz / nyquist * FREQ_Q_MAX).astype(np.int64),
        0, FREQ_Q_MAX,
    )

    hashes = []
    n = len(peak_times_s)
    for anchor_idx in range(n):
        t1 = peak_times_s[anchor_idx]
        f1 = peak_freqs_hz[anchor_idx]
        if f1 <= 0:
            continue
        q_f1 = int(q_freqs[anchor_idx])

        pairs_found = 0
        for j in range(anchor_idx + 1, n):
            if pairs_found >= FAN_OUT:
                break
            dt = peak_times_s[j] - t1
            if dt < DT_MIN_S:
                continue
            if dt > DT_MAX_S:
                break

            f2 = peak_freqs_hz[j]
            if f2 <= 0:
                continue
            if abs(np.log2(f2 / f1)) > DF_MAX_OCTAVES:
                continue

            q_f2 = int(q_freqs[j])
            q_dt = min(DT_Q_MAX, int(round(dt * 1000)))

            h = (q_f1 << (FREQ_BITS + DT_BITS)) | (q_f2 << DT_BITS) | q_dt
            hashes.append((int(h), float(t1)))
            pairs_found += 1

    return hashes


def _ffmpeg_to_pcm(ffmpeg_path, input_path, sample_rate):
    import subprocess
    from src.core.subprocess_utils import SUBPROCESS_KWARGS as _subprocess_kwargs

    result = subprocess.run(
        [
            ffmpeg_path,
            '-i', str(input_path),
            '-ar', str(sample_rate),
            '-ac', '1',
            '-f', 's32le',
            '-acodec', 'pcm_s32le',
            '-',
        ],
        capture_output=True, check=True, timeout=120,
        **_subprocess_kwargs,
    )
    pcm = np.frombuffer(result.stdout, dtype=np.int32)
    return pcm.astype(np.float32) / 2147483648.0


def decode_file(ffmpeg_path, audio_path, sample_rate=SAMPLE_RATE):
    try:
        return _ffmpeg_to_pcm(ffmpeg_path, audio_path, sample_rate)
    except Exception as e:
        logger.error(f"[Constellation] Failed to decode {audio_path}: {e}")
        return None


def decode_wem_bytes(ffmpeg_path, wem_bytes, vgmstream_path, sample_rate=SAMPLE_RATE):
    import subprocess
    import tempfile
    from pathlib import Path
    from XXAR import get_temp_dir
    from src.core.subprocess_utils import SUBPROCESS_KWARGS as _subprocess_kwargs

    tmp_wem_path = None
    tmp_wav_path = None
    try:
        with tempfile.NamedTemporaryFile(
            suffix='.wem', delete=False, dir=str(get_temp_dir())
        ) as tmp:
            tmp.write(wem_bytes)
            tmp_wem_path = Path(tmp.name)

        with tempfile.NamedTemporaryFile(
            suffix='_intermediate.wav', delete=False, dir=str(get_temp_dir())
        ) as tmp:
            tmp_wav_path = Path(tmp.name)

        try:
            subprocess.run(
                [vgmstream_path, '-o', str(tmp_wav_path), str(tmp_wem_path)],
                capture_output=True, check=True, timeout=10,
                **_subprocess_kwargs,
            )
        except Exception as e:
            logger.debug(f"[Constellation] vgmstream skipped wem: {e}")
            return None

        return _ffmpeg_to_pcm(ffmpeg_path, tmp_wav_path, sample_rate)
    except Exception as e:
        logger.error(f"[Constellation] Failed to decode wem bytes: {e}")
        return None
    finally:
        for p in (tmp_wem_path, tmp_wav_path):
            if p is not None:
                try:
                    p.unlink()
                except Exception:
                    pass
