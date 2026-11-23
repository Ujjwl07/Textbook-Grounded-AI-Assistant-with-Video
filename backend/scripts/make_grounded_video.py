"""Render a video whose content comes from the NCERT corpus, not from presets.

This is the end-to-end path the API takes (retrieve -> build scenes -> TTS ->
slides -> MP4), runnable without MongoDB so it can be demoed and tested locally.

    python backend/scripts/make_grounded_video.py "Gravitation" --subject physics --class 11
    python backend/scripts/make_grounded_video.py "Chemical Kinetics" --subject chemistry --class 12
    python backend/scripts/make_grounded_video.py "Gravitation" --slides-only
"""

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import get_settings  # noqa: E402
from app.rag.scene_builder import build_scenes  # noqa: E402
from app.tts.tts_generator import TTSGenerator  # noqa: E402
from app.video.scene_presets import get_fallback_scenes  # noqa: E402
from app.video.slide_generator import SlideRenderer  # noqa: E402
from app.video.video_assembler import VideoAssembler  # noqa: E402

SETTINGS = get_settings()


def slugify(text: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in text.lower()).strip("_")


def describe(scenes: list) -> None:
    for scene in scenes:
        print(f"\n  [{scene['part']}] {scene['slide_title']}   (visual: {scene['visual_type']})")
        if scene.get("definition"):
            print(f"    definition : {scene['definition'][:150]}")
            print(f"    source     : {scene['definition_source']}")
        for bullet in scene.get("slide_bullets", []):
            print(f"    • {bullet[:110]}")


async def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    parser = argparse.ArgumentParser()
    parser.add_argument("topic")
    # Both default to None so the retriever infers them from the corpus, which is
    # what the API does when a client sends only a topic. Defaulting them here
    # silently constrained the search: "Human Reproduction" with the old
    # default of Class 11 resolved to Cell Cycle and Cell Division rather than
    # the Class 12 chapter of that name.
    parser.add_argument("--subject", default=None, choices=["physics", "chemistry", "biology"])
    parser.add_argument("--class", dest="class_level", default=None, choices=["11", "12"])
    parser.add_argument("--slides-only", action="store_true",
                        help="Render the five PNGs and skip TTS/encoding")
    parser.add_argument("--out", default=None, help="Output MP4 path")
    args = parser.parse_args()

    print("=" * 76)
    requested = (f"Class {args.class_level}" if args.class_level else "class: infer") + \
                (f", {args.subject}" if args.subject else ", subject: infer")
    print(f"GROUNDED VIDEO — {args.topic}  [{requested}]")
    print("=" * 76)

    start = time.perf_counter()
    scenes = build_scenes(args.topic, args.subject, args.class_level)
    retrieval_seconds = time.perf_counter() - start

    if scenes:
        resolved = scenes[0]
        print(f"\nResolved to: Class {resolved.get('class_level')} "
              f"{str(resolved.get('subject', '')).title()} / {resolved.get('chapter_name')}")
        print(f"Retrieved and assembled 5 scenes in {retrieval_seconds:.1f}s")
        grounded = True
    else:
        print("\nRetrieval found nothing for this topic — falling back to presets")
        scenes = get_fallback_scenes(args.topic, args.subject, args.class_level)
        grounded = False

    describe(scenes)

    renderer = SlideRenderer()
    slug = slugify(args.topic)

    slide_dir = SETTINGS.slide_output_dir / slug
    slide_dir.mkdir(parents=True, exist_ok=True)
    for index, scene in enumerate(scenes):
        path = slide_dir / f"{index}_{scene['part'].lower()}.png"
        renderer.render_scene_slide(scene, str(path))
    print(f"\nSlides written to {slide_dir}")

    scenes_path = SETTINGS.slide_output_dir / f"{slug}_scenes.json"
    scenes_path.write_text(json.dumps(scenes, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Scene JSON written to {scenes_path}")

    if args.slides_only:
        print("\n--slides-only: skipping TTS and encoding.")
        return

    output_path = args.out or str(SETTINGS.video_output_dir / f"{slug}.mp4")
    SETTINGS.video_output_dir.mkdir(parents=True, exist_ok=True)

    assembler = VideoAssembler(TTSGenerator(), renderer)
    print(f"\nAssembling video -> {output_path}")
    render_start = time.perf_counter()
    voice_subject = (scenes[0].get("subject") if scenes else None) or args.subject
    await assembler.assemble_full_video(scenes, voice_subject, output_path)
    total = time.perf_counter() - render_start

    stats = assembler.last_render_stats
    print(f"\nDone in {total:.1f}s  "
          f"({stats.get('video_duration_seconds')}s of video, "
          f"{stats.get('output_size_bytes', 0) / 1e6:.2f} MB)")
    print(f"  content source : {'NCERT corpus (retrieved)' if grounded else 'presets'}")
    print(f"  retrieval      : {retrieval_seconds:.1f}s")
    for stage, seconds in stats.get("stages", {}).items():
        print(f"  {stage:<14} {seconds:>7.2f}s")


if __name__ == "__main__":
    asyncio.run(main())
