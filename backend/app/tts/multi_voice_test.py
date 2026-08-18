"""Engine comparison: Edge-TTS vs gTTS vs Coqui-TTS (Pallika, Section 11.3 #6).

Measures, per engine and per subject, the objective properties we can compute
without human listeners: synthesis latency, real-time factor, output size,
sample rate and whether the engine returns word-level timestamps at all.

Subjective quality is a separate exercise — see voice_eval.py, which builds the
listening test whose MOS ratings go in the report.

gTTS and Coqui are optional. Engines that are not installed are reported as
"unavailable" rather than crashing the run, so the script works on any machine.

Run from the repo root:  python backend/app/tts/multi_voice_test.py
"""

import asyncio
import json
import os
import sys
import time
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.tts.audio_processor import PYDUB_AVAILABLE  # noqa: E402
from app.tts.text_preprocessor import preprocess  # noqa: E402
from app.tts.tts_config import get_voice_config  # noqa: E402

SAMPLE_TEXTS = {
    "physics": "Newton's second law states that force equals mass times acceleration, "
               "written as F equals m a. Always check your SI units before answering.",
    "biology": "During the light reaction of photosynthesis, water is split and NADP "
               "is reduced to NADPH, while ATP is synthesised by photophosphorylation.",
    "chemistry": "A tertiary alkyl halide follows the SN1 pathway through a carbocation "
                 "intermediate, whereas a primary halide prefers the SN2 mechanism.",
}

OUTPUT_DIR = BACKEND_DIR / "outputs" / "audio" / "engine_comparison"


def audio_duration_seconds(path: str):
    """Best-effort duration probe; returns None when no decoder is available."""
    if not PYDUB_AVAILABLE:
        return None
    try:
        from pydub import AudioSegment

        return len(AudioSegment.from_file(path)) / 1000.0
    except Exception:
        return None


def audio_sample_rate(path: str):
    if not PYDUB_AVAILABLE:
        return None
    try:
        from pydub import AudioSegment

        return AudioSegment.from_file(path).frame_rate
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Engine adapters — each returns (path, extra_info) or raises
# ---------------------------------------------------------------------------


async def synth_edge_tts(text: str, subject: str, out_path: str) -> dict:
    import edge_tts

    config = get_voice_config(subject)
    communicate = edge_tts.Communicate(
        text=text,
        voice=config["voice"],
        rate=config["rate"],
        pitch=config["pitch"],
        boundary="WordBoundary",
    )
    boundaries = 0
    with open(out_path, "wb") as fh:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                fh.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                boundaries += 1
    return {"word_timestamps": True, "word_count": boundaries, "voice": config["voice"]}


async def synth_gtts(text: str, subject: str, out_path: str) -> dict:
    from gtts import gTTS

    def _run():
        gTTS(text=text, lang="en", tld="co.in").save(out_path)

    # gTTS is blocking; keep the event loop responsive.
    await asyncio.to_thread(_run)
    return {"word_timestamps": False, "word_count": 0, "voice": "gtts:en-co.in"}


async def synth_coqui(text: str, subject: str, out_path: str) -> dict:
    from TTS.api import TTS as CoquiTTS

    model_name = "tts_models/en/ljspeech/tacotron2-DDC"

    def _run():
        engine = CoquiTTS(model_name=model_name, progress_bar=False)
        engine.tts_to_file(text=text, file_path=out_path)

    await asyncio.to_thread(_run)
    return {"word_timestamps": False, "word_count": 0, "voice": model_name}


ENGINES = [
    ("edge-tts", synth_edge_tts, "mp3"),
    ("gtts", synth_gtts, "mp3"),
    ("coqui-tts", synth_coqui, "wav"),
]


async def run_engine(name, fn, ext, subject, text) -> dict:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = str(OUTPUT_DIR / f"{subject}_{name}.{ext}")

    start = time.perf_counter()
    try:
        info = await fn(text, subject, out_path)
    except ImportError as exc:
        return {"engine": name, "subject": subject, "available": False, "reason": f"not installed ({exc.name})"}
    except Exception as exc:
        return {"engine": name, "subject": subject, "available": False, "reason": f"error: {exc}"}
    latency = time.perf_counter() - start

    duration = audio_duration_seconds(out_path)
    size = os.path.getsize(out_path) if os.path.exists(out_path) else 0

    row = {
        "engine": name,
        "subject": subject,
        "available": True,
        "latency_seconds": round(latency, 2),
        "audio_duration_seconds": round(duration, 2) if duration else None,
        "realtime_factor": round(latency / duration, 3) if duration else None,
        "size_bytes": size,
        "sample_rate_hz": audio_sample_rate(out_path),
        "offline": name == "coqui-tts",
        "path": out_path,
    }
    row.update(info)
    return row


async def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    print("=" * 76)
    print("TTS ENGINE COMPARISON — CPG-92 (Pallika)")
    print("=" * 76)

    rows = []
    for subject, raw_text in SAMPLE_TEXTS.items():
        # Every engine receives identically preprocessed text so the comparison
        # measures the engine, not the normalisation.
        text = preprocess(raw_text, subject, emphasis_words=get_voice_config(subject).get("emphasis_words"))
        print(f"\n[{subject}] {len(text.split())} words")
        for name, fn, ext in ENGINES:
            row = await run_engine(name, fn, ext, subject, text)
            rows.append(row)
            if row["available"]:
                print(f"  {name:<10} {row['latency_seconds']:>6.2f}s  "
                      f"audio {row['audio_duration_seconds']}s  "
                      f"RTF {row['realtime_factor']}  "
                      f"timestamps={row['word_timestamps']}")
            else:
                print(f"  {name:<10} unavailable — {row['reason']}")

    out_dir = BACKEND_DIR / "outputs" / "benchmarks"
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "tts_engine_comparison.json"
    report_path.write_text(json.dumps(rows, indent=2), encoding="utf-8")

    print(f"\nJSON written to {report_path}")
    print("Audio samples in", OUTPUT_DIR)


if __name__ == "__main__":
    asyncio.run(main())
