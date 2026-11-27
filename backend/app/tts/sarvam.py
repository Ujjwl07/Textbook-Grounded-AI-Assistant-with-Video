"""Sarvam AI: Sarvam-Translate for NCERT text and the Bulbul v3 voice.

Lessons are scripted in English from the NCERT text. For a Hindi or Punjabi
lesson each scene's narration is translated with Sarvam-Translate, then voiced
with Bulbul v3. Bulbul returns audio only (no word timings), so the karaoke
captions use word times estimated from each word's length across the clip;
English narration keeps Edge-TTS and its exact word boundaries.
"""

import asyncio
import base64
import io
import logging
import re

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)

# Languages offered on the Search page. English needs no translation.
LANGUAGES = {
    "en-IN": "English",
    "hi-IN": "Hindi",
    "pa-IN": "Punjabi",
}
ENGLISH = "en-IN"

# Bulbul v3 speakers, matched to the English voices (female for Physics and
# Chemistry, male for Biology). Every v3 speaker covers all the languages above.
SPEAKERS = {"physics": "priya", "chemistry": "ritu", "biology": "aditya"}
DEFAULT_SPEAKER = "priya"

TRANSLATE_LIMIT = 1900   # Sarvam-Translate accepts at most 2,000 characters
TTS_LIMIT = 1500         # keep each Bulbul request comfortably short
ATTEMPTS = 3

_translations: dict = {}


class SarvamError(RuntimeError):
    pass


def is_configured() -> bool:
    return bool(get_settings().sarvam_api_key)


def _split(text: str, limit: int) -> list:
    """Split at sentence ends (., ?, !, । Danda) so each piece fits ``limit``."""
    text = (text or "").strip()
    if len(text) <= limit:
        return [text] if text else []
    sentences = re.split(r"(?<=[.!?।])\s+", text)
    pieces, current = [], ""
    for s in sentences:
        while len(s) > limit:  # a single overlong sentence: cut at a space
            cut = s.rfind(" ", 0, limit)
            cut = cut if cut > 0 else limit
            if current:
                pieces.append(current)
                current = ""
            pieces.append(s[:cut].strip())
            s = s[cut:].strip()
        if current and len(current) + 1 + len(s) > limit:
            pieces.append(current)
            current = s
        else:
            current = f"{current} {s}".strip()
    if current:
        pieces.append(current)
    return pieces


async def _post(path: str, payload: dict) -> dict:
    settings = get_settings()
    if not settings.sarvam_api_key:
        raise SarvamError("SARVAM_API_KEY is not set, so only English lessons can be made.")
    url = settings.sarvam_base_url.rstrip("/") + path
    headers = {"api-subscription-key": settings.sarvam_api_key}
    last = None
    for attempt in range(1, ATTEMPTS + 1):
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                r = await client.post(url, json=payload, headers=headers)
            if r.status_code == 200:
                return r.json()
            # Rate limits and server errors are worth another try; a 4xx is not.
            last = f"HTTP {r.status_code}: {r.text[:200]}"
            if r.status_code != 429 and r.status_code < 500:
                break
        except httpx.HTTPError as exc:
            last = f"{type(exc).__name__}: {exc}"
        if attempt < ATTEMPTS:
            await asyncio.sleep(1.5 * attempt)
    raise SarvamError(f"Sarvam {path} failed: {last}")


async def translate(text: str, target: str, source: str = ENGLISH) -> str:
    """Translate ``text`` into ``target`` with Sarvam-Translate (cached)."""
    if not text or target == source:
        return text
    key = (text, source, target)
    if key in _translations:
        return _translations[key]
    out = []
    for piece in _split(text, TRANSLATE_LIMIT):
        data = await _post("/translate", {
            "input": piece,
            "source_language_code": source,
            "target_language_code": target,
            "model": "sarvam-translate:v1",
        })
        out.append((data.get("translated_text") or "").strip())
    result = " ".join(x for x in out if x)
    if not result:
        raise SarvamError("Sarvam-Translate returned no text")
    if len(_translations) > 2000:
        _translations.clear()
    _translations[key] = result
    return result


def estimate_word_times(text: str, start: float, end: float) -> list:
    """Spread the words of ``text`` over [start, end] by length, with a little
    extra time after punctuation where the voice pauses."""
    words = (text or "").split()
    if not words or end <= start:
        return []
    weights = []
    for w in words:
        weight = len(w) + 2
        if w[-1] in ".!?।":
            weight += 5
        elif w[-1] in ",;:":
            weight += 3
        weights.append(weight)
    span = end - start
    total = float(sum(weights))
    t = start
    out = []
    for w, weight in zip(words, weights):
        d = span * weight / total
        out.append({"word": w, "start": round(t, 3), "end": round(t + d, 3), "duration": round(d, 3)})
        t += d
    return out


async def synthesize(text: str, language: str, subject: str, pace: float, output_path: str) -> float:
    """Voice ``text`` with Bulbul v3 into ``output_path`` (MP3). Returns seconds."""
    from pydub import AudioSegment

    speaker = SPEAKERS.get((subject or "").lower(), DEFAULT_SPEAKER)
    audio = AudioSegment.empty()
    for piece in _split(text, TTS_LIMIT):
        data = await _post("/text-to-speech", {
            "text": piece,
            "target_language_code": language,
            "speaker": speaker,
            "model": "bulbul:v3",
            "pace": float(pace),
        })
        for b64 in data.get("audios") or []:
            audio += AudioSegment.from_file(io.BytesIO(base64.b64decode(b64)), format="wav")
    if len(audio) == 0:
        raise SarvamError("Bulbul returned no audio")
    audio.export(output_path, format="mp3", bitrate="128k")
    return len(audio) / 1000.0
