import os
import shutil
import time
import logging
from collections import defaultdict
from moviepy.editor import (
    AudioFileClip,
    ImageClip,
    concatenate_videoclips
)
from app.tts.tts_generator import TTSGenerator
from app.video.slide_generator import SlideRenderer
from app.video.subtitle_engine import SubtitleEngine
from app.video.animation_engine import (
    apply_scene_animation,
    apply_ken_burns,
    apply_fade_in_out,
    resolve_scene_duration,
)
from app.video.vmake_integration import VMakeIntegration
from app.core.config import get_settings

logger = logging.getLogger(__name__)

# Intro/outro card length in seconds
BOOKEND_DURATION = 2.5


class RenderTimer:
    """Accumulates wall-clock time per pipeline stage for the benchmark report."""

    def __init__(self):
        self.totals = defaultdict(float)
        self.counts = defaultdict(int)
        self._t0 = time.perf_counter()

    def record(self, stage: str, seconds: float) -> None:
        self.totals[stage] += seconds
        self.counts[stage] += 1

    def time(self, stage: str):
        timer = self

        class _Scope:
            def __enter__(self_inner):
                self_inner.start = time.perf_counter()
                return self_inner

            def __exit__(self_inner, *exc):
                timer.record(stage, time.perf_counter() - self_inner.start)
                return False

        return _Scope()

    def summary(self) -> dict:
        total = time.perf_counter() - self._t0
        return {
            "total_seconds": round(total, 2),
            "stages": {k: round(v, 2) for k, v in sorted(self.totals.items(), key=lambda kv: -kv[1])},
            "stage_calls": dict(self.counts),
        }


class VideoAssembler:
    def __init__(self, tts: TTSGenerator, slide_renderer: SlideRenderer):
        self.tts = tts
        self.slide_renderer = slide_renderer
        self.subtitle_engine = SubtitleEngine()
        self.settings = get_settings()

        # Configure VMake.ai Integration. It stays inert unless both a key and
        # the VMAKE_ENABLED flag are set (see Settings.vmake_active).
        self.vmake = VMakeIntegration(self.settings.vmake_api_key if self.settings.vmake_active else "")

        # Populated after each assemble_full_video call; consumed by the benchmark script.
        self.last_render_stats = {}

    async def assemble_full_video(self, scenes: list, subject: str, output_path: str) -> str:
        """
        Takes a list of scenes and subject, synthesizes TTS, generates slides,
        overlays subtitles, applies the per-scene animation declared in the scene
        JSON, and concatenates into a final MP4 video.
        """
        temp_dir = self.settings.video_output_dir / "temp"
        temp_dir.mkdir(parents=True, exist_ok=True)

        size = self.settings.video_size
        timer = RenderTimer()
        clips = []
        temp_files = []

        try:
            # 1. Generate Intro Slide (if list is not empty)
            if scenes:
                with timer.time("intro_outro"):
                    intro_scene = {
                        "part": "HOOK",
                        "slide_title": f"NEET Preparation: {subject.title()}",
                        "slide_bullets": [
                            "Targeted Microlearning Module",
                            "Concept-focused review grounded in NCERT",
                        ],
                        "visual_type": "none",
                    }
                    intro_slide_path = str(temp_dir / "intro_slide.png")
                    self.slide_renderer.render_scene_slide(intro_scene, intro_slide_path)
                    temp_files.append(intro_slide_path)

                    intro_clip = ImageClip(intro_slide_path, duration=BOOKEND_DURATION)
                    intro_clip = apply_ken_burns(intro_clip, BOOKEND_DURATION)
                    intro_clip = apply_fade_in_out(intro_clip, fade_in_duration=0.5, fade_out_duration=0.5)
                    clips.append(intro_clip)

            # 2. Generate Scene Clips
            for i, scene in enumerate(scenes):
                logger.info("Processing scene %s/%s: %s", i + 1, len(scenes), scene.get("part"))

                # A. Generate narration audio
                audio_path = str(temp_dir / f"audio_{i}.mp3")
                with timer.time("tts"):
                    audio_result = await self.tts.generate_scene_audio(
                        scene["narration_text"],
                        subject,
                        audio_path,
                    )
                temp_files.append(audio_path)

                audio_clip = AudioFileClip(audio_path)
                audio_duration = audio_clip.duration

                # The segmenter's duration_hint_seconds can hold the slide slightly
                # longer than the narration, but never shorter than the voice track.
                duration = resolve_scene_duration(audio_duration, scene.get("duration_hint_seconds"))

                # B. Render slide
                slide_path = str(temp_dir / f"slide_{i}.png")

                # Determine if we should generate a background video with VMake.ai
                bg_video_url = None
                if self.vmake.is_enabled():
                    with timer.time("vmake_background"):
                        bg_video_url = self.vmake.generate_background(scene["part"], subject)

                # If background video is available, render transparent slide, otherwise solid
                use_bg_video = bg_video_url is not None
                with timer.time("slide_render"):
                    self.slide_renderer.render_scene_slide(scene, slide_path, transparent_bg=use_bg_video)
                temp_files.append(slide_path)

                # C. Build the scene visual (slide over VMake background, or animated slide)
                with timer.time("animation"):
                    if use_bg_video:
                        bg_video_path = str(temp_dir / f"bg_{i}.mp4")
                        try:
                            import urllib.request

                            urllib.request.urlretrieve(bg_video_url, bg_video_path)
                            temp_files.append(bg_video_path)
                            scene_video = self.vmake.composite_slide_over_bg(slide_path, bg_video_path, duration)
                        except Exception as e:
                            logger.error("Failed to use VMake background: %s. Falling back to standard slide.", e)
                            img_clip = ImageClip(slide_path, duration=duration)
                            scene_video = apply_scene_animation(
                                img_clip, scene.get("animation_type"), duration, size=size
                            )
                    else:
                        img_clip = ImageClip(slide_path, duration=duration)
                        # Honour the scene's declared animation_type: fade_in | slide_left | zoom
                        scene_video = apply_scene_animation(
                            img_clip, scene.get("animation_type"), duration, size=size
                        )

                # D. Burn in word-level karaoke subtitles. burn_onto composites
                # directly instead of going through CompositeVideoClip, whose
                # generic float64 blit dominated render time (see
                # scripts/profile_frame_pipeline.py).
                word_boundaries = audio_result.get("word_boundaries", [])
                if word_boundaries:
                    with timer.time("subtitles"):
                        scene_video = self.subtitle_engine.burn_onto(
                            scene_video,
                            word_boundaries,
                            duration,
                            size=size,
                        )

                # E. Combine video and audio
                scene_video = scene_video.set_duration(duration).set_audio(audio_clip)
                scene_video = apply_fade_in_out(scene_video, fade_in_duration=0.3, fade_out_duration=0.3)
                clips.append(scene_video)

            # 3. Generate Outro Slide
            if scenes:
                with timer.time("intro_outro"):
                    outro_scene = {
                        "part": "NEET_ALERT",
                        "slide_title": "Ready for the Challenge?",
                        "slide_bullets": [
                            "Proceed to the Quiz section.",
                            "Test your mastery of this concept now!",
                        ],
                        "visual_type": "none",
                    }
                    outro_slide_path = str(temp_dir / "outro_slide.png")
                    self.slide_renderer.render_scene_slide(outro_scene, outro_slide_path)
                    temp_files.append(outro_slide_path)

                    outro_clip = ImageClip(outro_slide_path, duration=BOOKEND_DURATION)
                    outro_clip = apply_ken_burns(outro_clip, BOOKEND_DURATION)
                    outro_clip = apply_fade_in_out(outro_clip, fade_in_duration=0.5, fade_out_duration=0.5)
                    clips.append(outro_clip)

            # 4. Concatenate and compile final video
            logger.info("Concatenating all video clips...")
            final_video = concatenate_videoclips(clips, method="compose")
            video_duration = final_video.duration

            threads = self.settings.video_threads or os.cpu_count() or 1
            logger.info(
                "Writing final video file to %s (preset=%s, threads=%s)...",
                output_path, self.settings.video_preset, threads,
            )
            with timer.time("encode"):
                final_video.write_videofile(
                    output_path,
                    fps=self.settings.video_fps,
                    codec="libx264",
                    audio_codec="aac",
                    preset=self.settings.video_preset,
                    threads=threads,
                    verbose=False,
                    logger=None,
                )

            # Close all clip resources to release files
            final_video.close()
            for clip in clips:
                clip.close()

            stats = timer.summary()
            stats.update({
                "scenes": len(scenes),
                "video_duration_seconds": round(video_duration or 0.0, 2),
                "output_size_bytes": os.path.getsize(output_path) if os.path.exists(output_path) else 0,
                "vmake_enabled": self.vmake.is_enabled(),
                "fps": self.settings.video_fps,
                "resolution": f"{size[0]}x{size[1]}",
                "x264_preset": self.settings.video_preset,
                "threads": threads,
            })
            if video_duration:
                stats["realtime_factor"] = round(stats["total_seconds"] / video_duration, 2)
            self.last_render_stats = stats

            logger.info("Video assembly completed in %ss: %s", stats["total_seconds"], stats["stages"])
            return output_path

        finally:
            # Cleanup temporary file resources
            logger.info("Cleaning up temporary video assembly files...")
            for f in temp_files:
                try:
                    if os.path.exists(f):
                        os.remove(f)
                except Exception as e:
                    logger.warning("Could not remove temp file %s: %s", f, e)

            try:
                if temp_dir.exists():
                    shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception:
                pass
