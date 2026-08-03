import asyncio
import edge_tts
from app.tts.tts_config import VOICE_MAP

class TTSGenerator:
    def _preprocess_for_tts(self, text: str, subject: str) -> str:
        # Basic cleanup: remove markdown symbols or brackets if they slipped in
        text = text.replace('*', '').replace('_', '')
        return text

    async def generate_scene_audio(self, text: str, subject: str, output_path: str) -> dict:
        # Determine fallback subject key if not in map
        subject_key = subject.lower() if subject else 'physics'
        if subject_key not in VOICE_MAP:
            subject_key = 'physics'
            
        config = VOICE_MAP[subject_key]
        text_processed = self._preprocess_for_tts(text, subject_key)
        
        communicate = edge_tts.Communicate(
            text=text_processed,
            voice=config['voice'],
            rate=config['rate'],
            pitch=config['pitch'],
            boundary="WordBoundary"
        )
        
        word_boundaries = []
        
        with open(output_path, "wb") as audio_file:
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    audio_file.write(chunk["data"])
                elif chunk["type"] == "WordBoundary":
                    # Offset and duration are in 100-nanosecond units (ticks)
                    # Convert to seconds (1 tick = 10^-7 seconds)
                    start_sec = chunk["offset"] * 1e-7
                    duration_sec = chunk["duration"] * 1e-7
                    end_sec = start_sec + duration_sec
                    word_boundaries.append({
                        "word": chunk["text"],
                        "start": start_sec,
                        "end": end_sec,
                        "duration": duration_sec
                    })
                    
        return {
            "audio_path": output_path,
            "word_boundaries": word_boundaries
        }
