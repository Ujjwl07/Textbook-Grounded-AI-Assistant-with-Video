"""Edge-TTS narration generator with word-boundary timestamps (Pallika).

Pipeline per scene:
    raw script text
      -> text_preprocessor.preprocess()   (subject-aware notation expansion)
      -> edge_tts.Communicate.stream()    (audio + WordBoundary events)
      -> audio_processor.process_audio_file()  (high-pass, trim, normalise)
      -> word boundaries shifted by the trimmed lead-in

The final shift matters: Edge-TTS timestamps are relative to the *untrimmed*
audio, so without it the karaoke subtitles drift ahead by the lead-in length.
"""

import logging

import edge_tts

from app.core.config import get_settings
from app.tts.audio_processor import process_audio_file, shift_word_boundaries
from app.tts.text_preprocessor import preprocess
from app.tts.tts_config import VOICE_MAP, get_voice_config

logger = logging.getLogger(__name__)


class TTSGenerator:
    def __init__(self, postprocess: bool = None):
        self.settings = get_settings()
        self.postprocess = (
            self.settings.audio_postprocess_enabled if postprocess is None else postprocess
        )

    def _preprocess_for_tts(self, text: str, subject: str) -> str:
        """Subject-aware normalisation of the script before synthesis."""
        config = get_voice_config(subject)
        return preprocess(text, subject, emphasis_words=config.get("emphasis_words"))

    async def generate_scene_audio(self, text: str, subject: str, output_path: str) -> dict:
        subject_key = (subject or "physics").lower()
        if subject_key not in VOICE_MAP:
            subject_key = "physics"

        config = get_voice_config(subject_key)
        text_processed = self._preprocess_for_tts(text, subject_key)

        communicate = edge_tts.Communicate(
            text=text_processed,
            voice=config["voice"],
            rate=config["rate"],
            pitch=config["pitch"],
            boundary="WordBoundary",
        )

        word_boundaries = []

        with open(output_path, "wb") as audio_file:
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    audio_file.write(chunk["data"])
                elif chunk["type"] == "WordBoundary":
                    # Offset and duration are in 100-nanosecond units (ticks).
                    # Convert to seconds (1 tick = 10^-7 seconds).
                    start_sec = chunk["offset"] * 1e-7
                    duration_sec = chunk["duration"] * 1e-7
                    word_boundaries.append({
                        "word": chunk["text"],
                        "start": start_sec,
                        "end": start_sec + duration_sec,
                        "duration": duration_sec,
                    })

        audio_metrics = {"applied": False, "leading_trim_seconds": 0.0}
        if self.postprocess:
            audio_metrics = process_audio_file(
                output_path,
                target_lufs=self.settings.audio_target_lufs,
                silence_threshold_db=self.settings.audio_silence_threshold_db,
            )
            trimmed = audio_metrics.get("leading_trim_seconds", 0.0)
            if trimmed:
                word_boundaries = shift_word_boundaries(word_boundaries, trimmed)
            if audio_metrics.get("reason"):
                logger.debug("Audio post-processing skipped: %s", audio_metrics["reason"])

        return {
            "audio_path": output_path,
            "word_boundaries": word_boundaries,
            "voice": config["voice"],
            "subject": subject_key,
            "processed_text": text_processed,
            "audio_metrics": audio_metrics,
        }
