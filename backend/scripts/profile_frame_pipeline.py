"""Isolate what makes MoviePy frame generation slow (Purnika, optimisation study).

The full-assembly benchmark showed ~95% of wall time inside write_videofile, and
changing the x264 preset barely moved it — so the cost is Python-side frame
generation, not the encoder. This script encodes the same 10-second slide six
ways and reports frames per second for each:

    static              — no zoom, no subtitles         (floor: encoder only)
    ken_burns           — per-frame PIL resize
    subs_composite      — subtitles via MoviePy CompositeVideoClip (original)
    subs_burn           — subtitles via SubtitleEngine.burn_onto (optimised)
    kenburns+composite  — original production pipeline
    kenburns+burn       — current production pipeline

Run from the repo root:  python backend/scripts/profile_frame_pipeline.py
"""

import json
import sys
import time
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from moviepy.editor import CompositeVideoClip, ImageClip  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.video.animation_engine import apply_ken_burns  # noqa: E402
from app.video.slide_generator import SlideRenderer  # noqa: E402
from app.video.subtitle_engine import SubtitleEngine  # noqa: E402

SETTINGS = get_settings()
CLIP_SECONDS = 10.0


def fake_word_boundaries(duration: float, words_per_second: float = 2.5) -> list:
    """Synthetic word timings so the profile does not depend on a network TTS call."""
    sample = ("Newton's third law tells us that forces always occur in pairs acting on "
              "two different bodies which is why they never cancel out").split()
    step = 1.0 / words_per_second
    boundaries = []
    t = 0.0
    index = 0
    while t < duration:
        boundaries.append({
            "word": sample[index % len(sample)],
            "start": t,
            "end": min(t + step * 0.9, duration),
            "duration": step * 0.9,
        })
        t += step
        index += 1
    return boundaries


def encode(clip, path: str) -> float:
    start = time.perf_counter()
    clip.write_videofile(
        path,
        fps=SETTINGS.video_fps,
        codec="libx264",
        preset=SETTINGS.video_preset,
        threads=SETTINGS.video_threads or None,
        audio=False,
        verbose=False,
        logger=None,
    )
    return time.perf_counter() - start


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    tmp_dir = SETTINGS.video_output_dir / "profile"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    slide_path = str(tmp_dir / "profile_slide.png")
    SlideRenderer().render_scene_slide(
        {
            "part": "CONCEPT",
            "slide_title": "Frame Pipeline Profile",
            "slide_bullets": ["Measuring per-frame cost", "Ken Burns vs subtitles"],
            "visual_type": "process",
        },
        slide_path,
    )

    size = SETTINGS.video_size
    boundaries = fake_word_boundaries(CLIP_SECONDS)
    subtitle_engine = SubtitleEngine()
    total_frames = int(CLIP_SECONDS * SETTINGS.video_fps)

    def build(with_zoom: bool, subs_mode):
        clip = ImageClip(slide_path, duration=CLIP_SECONDS)
        if with_zoom:
            clip = apply_ken_burns(clip, CLIP_SECONDS)
        if subs_mode == "composite":
            # Original path: MoviePy CompositeVideoClip + masked blit.
            overlay = subtitle_engine.generate_subtitles_clip(boundaries, CLIP_SECONDS, size=size)
            clip = CompositeVideoClip([clip, overlay])
        elif subs_mode == "burn":
            # Optimised path: direct float32 band blend.
            clip = subtitle_engine.burn_onto(clip, boundaries, CLIP_SECONDS, size=size)
        return clip.set_duration(CLIP_SECONDS)

    variants = [
        ("static", False, None),
        ("ken_burns", True, None),
        ("subs_composite", False, "composite"),
        ("subs_burn", False, "burn"),
        ("kenburns+composite", True, "composite"),
        ("kenburns+burn", True, "burn"),
    ]

    print("=" * 68)
    print(f"FRAME PIPELINE PROFILE — {CLIP_SECONDS:.0f}s clip, {total_frames} frames "
          f"@ {size[0]}x{size[1]}, preset={SETTINGS.video_preset}")
    print("=" * 68)

    results = {}
    for name, zoom, subs in variants:
        clip = build(zoom, subs)
        seconds = encode(clip, str(tmp_dir / f"{name}.mp4"))
        clip.close()
        fps = total_frames / seconds
        results[name] = {
            "seconds": round(seconds, 2),
            "fps": round(fps, 1),
            "realtime_factor": round(seconds / CLIP_SECONDS, 2),
        }
        print(f"  {name:<16} {seconds:7.2f}s   {fps:6.1f} fps   "
              f"{results[name]['realtime_factor']:5.2f}x realtime")

    base = results["static"]["seconds"]
    print()
    print("Overhead attributable to each stage (vs static baseline):")
    for name in ("ken_burns", "subs_composite", "subs_burn",
                 "kenburns+composite", "kenburns+burn"):
        delta = results[name]["seconds"] - base
        print(f"  {name:<16} +{delta:6.2f}s   ({delta / base * 100:5.0f}% over baseline)")

    out_path = BACKEND_DIR / "outputs" / "benchmarks" / "frame_pipeline_profile.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({
        "clip_seconds": CLIP_SECONDS,
        "frames": total_frames,
        "resolution": f"{size[0]}x{size[1]}",
        "fps_target": SETTINGS.video_fps,
        "x264_preset": SETTINGS.video_preset,
        "results": results,
    }, indent=2), encoding="utf-8")
    print(f"\nJSON written to {out_path}")


if __name__ == "__main__":
    main()
