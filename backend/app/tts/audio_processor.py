"""Audio post-processing for narration clips (Pallika, Section 11.3 #4).

Edge-TTS returns MP3 with inconsistent loudness between voices and a variable
lead-in/lead-out silence. Concatenating those clips straight into a video gives
scenes that jump in volume and drift out of sync with the slide cuts. This module
applies three passes:

  1. High-pass filter  — removes sub-80 Hz rumble / DC offset
  2. Silence trimming  — strips leading and trailing dead air
  3. Loudness normalisation — brings every clip to a common target (-16 LUFS)

``leading_trim_seconds`` is returned so the caller can shift Edge-TTS word
boundaries by the same amount; without that correction the karaoke subtitles
would run ahead of the audio by the length of the removed lead-in.

pydub (with the ffmpeg binary bundled by imageio-ffmpeg) does the decoding.
If pydub is unavailable the module degrades to a no-op instead of failing the
whole generation job.
"""

import logging
import os

logger = logging.getLogger(__name__)

HIGH_PASS_CUTOFF_HZ = 80

try:
    from pydub import AudioSegment
    from pydub.silence import detect_leading_silence

    try:
        import imageio_ffmpeg

        _FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
        AudioSegment.converter = _FFMPEG
        AudioSegment.ffmpeg = _FFMPEG
    except Exception:  # pragma: no cover - falls back to a system ffmpeg
        _FFMPEG = None

    PYDUB_AVAILABLE = True
except Exception:  # pragma: no cover - dependency missing
    AudioSegment = None
    detect_leading_silence = None
    PYDUB_AVAILABLE = False

try:
    import numpy as np
    import pyloudnorm

    PYLOUDNORM_AVAILABLE = True
except Exception:
    PYLOUDNORM_AVAILABLE = False


def _segment_to_float_array(segment):
    """Return a float32 array in [-1, 1], shaped (samples,) or (samples, channels)."""
    samples = np.array(segment.get_array_of_samples()).astype(np.float32)
    peak = float(1 << (8 * segment.sample_width - 1))
    samples /= peak
    if segment.channels > 1:
        samples = samples.reshape((-1, segment.channels))
    return samples


def measure_loudness(segment) -> dict:
    """Measure integrated loudness.

    Uses pyloudnorm for true ITU-R BS.1770 LUFS when installed; otherwise falls
    back to pydub's RMS dBFS, which approximates but is NOT the same metric.
    The returned ``method`` field records which one was used so the report never
    claims LUFS accuracy it does not have.
    """
    if PYLOUDNORM_AVAILABLE:
        try:
            meter = pyloudnorm.Meter(segment.frame_rate)
            loudness = meter.integrated_loudness(_segment_to_float_array(segment))
            if loudness != float("-inf"):
                return {"loudness": float(loudness), "method": "pyloudnorm_lufs"}
        except Exception as exc:
            logger.debug("pyloudnorm measurement failed (%s), using dBFS", exc)
    return {"loudness": float(segment.dBFS), "method": "pydub_dbfs"}


def trim_silence(segment, threshold_db: float = -45.0, keep_padding_ms: int = 60):
    """Trim leading/trailing silence, keeping a short pad so speech is not clipped.

    Returns ``(segment, leading_trim_ms, trailing_trim_ms)``.
    """
    lead = detect_leading_silence(segment, silence_threshold=threshold_db)
    trail = detect_leading_silence(segment.reverse(), silence_threshold=threshold_db)

    # A fully silent clip reports the entire length as silence; leave it alone.
    if lead + trail >= len(segment):
        return segment, 0, 0

    lead_cut = max(0, lead - keep_padding_ms)
    trail_cut = max(0, trail - keep_padding_ms)
    end = len(segment) - trail_cut
    return segment[lead_cut:end], lead_cut, trail_cut


def normalize_loudness(segment, target_lufs: float = -16.0, max_gain_db: float = 30.0):
    """Apply a fixed gain so the clip sits at ``target_lufs``.

    Returns ``(segment, applied_gain_db, measurement)``.
    """
    measurement = measure_loudness(segment)
    current = measurement["loudness"]
    if current == float("-inf"):
        return segment, 0.0, measurement

    gain = target_lufs - current
    gain = max(-max_gain_db, min(max_gain_db, gain))
    return segment.apply_gain(gain), round(gain, 2), measurement


def process_audio_file(
    path: str,
    target_lufs: float = -16.0,
    silence_threshold_db: float = -45.0,
    apply_high_pass: bool = True,
) -> dict:
    """Post-process a narration MP3 in place and return the metrics.

    The returned dict always contains ``leading_trim_seconds`` (0.0 when nothing
    was trimmed or when processing was skipped), so callers can correct word
    timestamps unconditionally.
    """
    result = {
        "path": path,
        "applied": False,
        "leading_trim_seconds": 0.0,
        "trailing_trim_seconds": 0.0,
        "gain_db": 0.0,
        "reason": None,
    }

    if not PYDUB_AVAILABLE:
        result["reason"] = "pydub_unavailable"
        return result
    if not os.path.exists(path):
        result["reason"] = "file_missing"
        return result

    try:
        segment = AudioSegment.from_file(path)
        original_duration = len(segment) / 1000.0
        before = measure_loudness(segment)

        if apply_high_pass:
            segment = segment.high_pass_filter(HIGH_PASS_CUTOFF_HZ)

        segment, lead_ms, trail_ms = trim_silence(segment, threshold_db=silence_threshold_db)
        segment, gain_db, _ = normalize_loudness(segment, target_lufs=target_lufs)

        segment.export(path, format="mp3")
        after = measure_loudness(segment)

        result.update({
            "applied": True,
            "leading_trim_seconds": round(lead_ms / 1000.0, 3),
            "trailing_trim_seconds": round(trail_ms / 1000.0, 3),
            "gain_db": gain_db,
            "loudness_before": round(before["loudness"], 2),
            "loudness_after": round(after["loudness"], 2),
            "loudness_method": after["method"],
            "duration_before_seconds": round(original_duration, 3),
            "duration_after_seconds": round(len(segment) / 1000.0, 3),
            "target_lufs": target_lufs,
            "high_pass_hz": HIGH_PASS_CUTOFF_HZ if apply_high_pass else None,
        })
    except Exception as exc:
        logger.warning("Audio post-processing failed for %s: %s", path, exc)
        result["reason"] = f"error: {exc}"

    return result


def shift_word_boundaries(word_boundaries: list, offset_seconds: float) -> list:
    """Shift Edge-TTS word timings after leading silence was trimmed.

    Timestamps are clamped at zero and any word that ends before the new start
    of audio is dropped, so subtitles stay aligned with what is actually heard.
    """
    if not word_boundaries or not offset_seconds:
        return word_boundaries

    shifted = []
    for entry in word_boundaries:
        start = entry["start"] - offset_seconds
        end = entry["end"] - offset_seconds
        if end <= 0:
            continue
        shifted.append({
            **entry,
            "start": max(0.0, start),
            "end": end,
        })
    return shifted
