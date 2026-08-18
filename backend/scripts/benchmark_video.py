"""Benchmark + visual-evidence generator for the video module (Purnika).

Produces the numbers and screenshots the capstone report needs:

  1. One PNG per scene theme in outputs/slides/  (5 themed templates evidence)
  2. Per-stage wall-clock timings for a full 5-scene assembly
  3. A machine-readable JSON summary in outputs/benchmarks/

Run from the repo root:  python backend/scripts/benchmark_video.py
"""

import asyncio
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import get_settings  # noqa: E402
from app.video.scene_presets import get_fallback_scenes  # noqa: E402
from app.tts.tts_generator import TTSGenerator  # noqa: E402
from app.video.fonts import resolve_font_path, font_is_scalable  # noqa: E402
from app.video.slide_generator import SCENE_THEMES, SlideRenderer  # noqa: E402
from app.video.video_assembler import VideoAssembler  # noqa: E402

SETTINGS = get_settings()


def benchmark_slides(renderer: SlideRenderer) -> dict:
    """Render one slide per theme, timing each, and keep the PNGs as evidence."""
    out_dir = SETTINGS.slide_output_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    visual_by_part = {
        "HOOK": ("alert", None),
        "CONCEPT": ("process", None),
        "EXAMPLE": ("formula", r"F = G \frac{m_1 m_2}{r^2}"),
        "MEMORY": ("comparison", None),
        "NEET_ALERT": ("alert", None),
    }

    results = {}
    for part in SCENE_THEMES:
        visual_type, formula = visual_by_part.get(part, ("none", None))
        scene = {
            "part": part,
            "slide_title": f"{part.replace('_', ' ').title()} Scene Template",
            "slide_bullets": [
                "First supporting point rendered by PIL.",
                "Second point, wrapped automatically at 45 characters.",
                "Third point closes the slide.",
            ],
            "visual_type": visual_type,
        }
        if formula:
            scene["formula_latex"] = formula

        path = out_dir / f"theme_{part.lower()}.png"
        start = time.perf_counter()
        renderer.render_scene_slide(scene, str(path))
        elapsed = time.perf_counter() - start

        results[part] = {
            "seconds": round(elapsed, 3),
            "path": str(path),
            "size_bytes": path.stat().st_size if path.exists() else 0,
            "visual_type": visual_type,
        }
        print(f"  [slide] {part:<11} {elapsed:6.3f}s  -> {path.name}")

    return results


async def benchmark_assembly() -> dict:
    """Time a full 5-scene assembly and return the assembler's stage breakdown."""
    tts = TTSGenerator()
    renderer = SlideRenderer()
    assembler = VideoAssembler(tts, renderer)

    scenes = get_fallback_scenes("Gravitation", "physics", "11")
    SETTINGS.video_output_dir.mkdir(parents=True, exist_ok=True)
    output_path = str(SETTINGS.video_output_dir / "benchmark_full.mp4")
    if os.path.exists(output_path):
        os.remove(output_path)

    print(f"  [assembly] rendering {len(scenes)} scenes -> {Path(output_path).name}")
    start = time.perf_counter()
    await assembler.assemble_full_video(scenes, "physics", output_path)
    total = time.perf_counter() - start

    stats = dict(assembler.last_render_stats)
    stats["measured_total_seconds"] = round(total, 2)
    stats["output_path"] = output_path
    stats["animation_types_used"] = sorted({s.get("animation_type", "fade_in") for s in scenes})
    return stats


async def main() -> None:
    print("=" * 68)
    print("VIDEO MODULE BENCHMARK — CPG-92 (Purnika)")
    print("=" * 68)
    print(f"Font face      : {resolve_font_path() or 'PIL default (bitmap)'}")
    print(f"Scalable fonts : {font_is_scalable()}")
    print(f"Resolution/FPS : {SETTINGS.video_width}x{SETTINGS.video_height} @ {SETTINGS.video_fps}fps")
    print(f"VMake active   : {SETTINGS.vmake_active}")
    print()

    print("1) Slide rendering per theme")
    slide_stats = benchmark_slides(SlideRenderer())
    slide_total = sum(v["seconds"] for v in slide_stats.values())
    print(f"  -> {len(slide_stats)} themes in {slide_total:.3f}s "
          f"(mean {slide_total / max(1, len(slide_stats)):.3f}s)")
    print()

    print("2) Full video assembly")
    assembly_stats = await benchmark_assembly()
    print(f"  -> total {assembly_stats['measured_total_seconds']}s for "
          f"{assembly_stats.get('video_duration_seconds')}s of video "
          f"(realtime factor {assembly_stats.get('realtime_factor')}x)")
    for stage, seconds in assembly_stats.get("stages", {}).items():
        share = 100.0 * seconds / max(assembly_stats["total_seconds"], 1e-6)
        print(f"     {stage:<18} {seconds:7.2f}s  {share:5.1f}%")
    print()

    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "environment": {
            "python": sys.version.split()[0],
            "platform": sys.platform,
            "font_face": resolve_font_path() or "PIL default",
            "scalable_fonts": font_is_scalable(),
        },
        "video_specs": {
            "resolution": f"{SETTINGS.video_width}x{SETTINGS.video_height}",
            "fps": SETTINGS.video_fps,
            "video_codec": "libx264",
            "audio_codec": "aac",
            "container": "mp4",
        },
        "slide_rendering": slide_stats,
        "slide_rendering_total_seconds": round(slide_total, 3),
        "assembly": assembly_stats,
    }

    bench_dir = BACKEND_DIR / "outputs" / "benchmarks"
    bench_dir.mkdir(parents=True, exist_ok=True)
    report_path = bench_dir / "video_benchmark.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"JSON summary written to {report_path}")


if __name__ == "__main__":
    asyncio.run(main())
