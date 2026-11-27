import asyncio
from typing import Optional
from proglog import ProgressBarLogger
from pathlib import Path
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


class _EncodeProgress(ProgressBarLogger):
    """Turns MoviePy's frame counter into encode progress (whole percents only)."""

    def __init__(self, report):
        super().__init__()
        self.report = report
        self.last = -1

    def bars_callback(self, bar, attr, value, old_value=None):
        if bar != "t" or attr != "index":
            return
        total = self.bars[bar].get("total") or 0
        if not total:
            return
        pct = int(100 * value / total)
        if pct >= self.last + 3 or pct >= 100:
            self.last = pct
            self.report("encode", pct, 100, f"Encoding the MP4 ({pct}% of frames)")


class VideoAssembler:
    def __init__(self, tts: TTSGenerator, slide_renderer: SlideRenderer):
        self.tts = tts
        self.slide_renderer = slide_renderer
        self.subtitle_engine = SubtitleEngine()
        # Reels are narrow: shorter lines, a third line allowed, and the band
        # raised clear of the buttons/caption overlay Shorts and Reels draw.
        self.subtitle_engine_portrait = SubtitleEngine(font_size=30, max_width=600, band_height=150, max_lines=3)
        self.subtitle_engine_portrait.band_margin_bottom = 70
        self.settings = get_settings()

        # Configure VMake.ai Integration. It stays inert unless both a key and
        # the VMAKE_ENABLED flag are set (see Settings.vmake_active).
        self.vmake = VMakeIntegration(self.settings.vmake_api_key if self.settings.vmake_active else "")

        # Populated after each assemble_full_video call; consumed by the benchmark script.
        self.last_render_stats = {}

    def _subtitle_engine(self, portrait: bool, language: str) -> SubtitleEngine:
        if not language or language == "en-IN":
            return self.subtitle_engine_portrait if portrait else self.subtitle_engine
        if portrait:
            engine = SubtitleEngine(font_size=30, max_width=600, band_height=150, max_lines=3, language=language)
            engine.band_margin_bottom = 70
            return engine
        return SubtitleEngine(language=language)

    async def _translate_scenes(self, scenes, voice_language, caption_language, report):
        """Narration text per scene in the voice and caption languages."""
        from app.tts import sarvam

        source = [str(sc.get("narration_text", "")) for sc in scenes]
        wanted = [lang for lang in dict.fromkeys([voice_language, caption_language]) if lang != "en-IN"]
        texts = {"en-IN": source}
        for lang in wanted:
            name = sarvam.LANGUAGES.get(lang, lang)
            report("narrate", 0, len(scenes), f"Translating the script into {name} (Sarvam-Translate)")
            texts[lang] = await asyncio.gather(*[sarvam.translate(t, lang) for t in source])
        return texts[voice_language], texts[caption_language]

    @staticmethod
    def _caption_words(audio_result: dict, caption_text: str, audio_seconds: float, same: bool) -> list:
        """Word timings for the burned-in captions. Same language as the voice:
        the voice's own timings. Bilingual: the caption sentence spread over the
        stretch where the voice speaks."""
        voice_words = audio_result.get("word_boundaries", []) or []
        if same:
            return voice_words
        from app.tts.sarvam import estimate_word_times

        if voice_words:
            start = float(voice_words[0].get("start", 0.0))
            end = float(voice_words[-1].get("end", audio_seconds) or audio_seconds)
        else:
            start, end = 0.0, float(audio_seconds or 0.0)
        return estimate_word_times(caption_text, start, max(end, start + 0.5))

    @staticmethod
    def _timeline_entry(scene, start, duration, audio_result, voice_text, caption_text) -> dict:
        return {
            "part": str(scene.get("part", "")),
            "title": str(scene.get("slide_title", "")),
            "start": round(start, 2),
            "duration": round(duration, 2),
            # What the watch page shows: the caption-language text and timings.
            "text": str(caption_text or ""),
            "words": [
                [str(w.get("word", "")), round(start + float(w.get("start", 0.0)), 2)]
                for w in audio_result.get("caption_words", audio_result.get("word_boundaries", [])) or []
            ],
            "voice_text": str(voice_text or ""),
            # The English script, for flashcards and doubts grounded in NCERT.
            "source_text": str(scene.get("narration_text", "")),
        }

    async def assemble_full_video(self, scenes: list, subject: str, output_path: str,
                                  orientation: str = "landscape", short: bool = False,
                                  on_progress=None, timeline: Optional[list] = None,
                                  voice_language: str = "en-IN", caption_language: Optional[str] = None,
                                  pace: float = 1.0) -> str:
        """
        Takes a list of scenes and subject, synthesizes TTS, generates slides,
        overlays subtitles, applies the per-scene animation declared in the scene
        JSON, and concatenates into a final MP4 video.

        ``orientation``: "landscape" (16:9, settings.video_size) or "portrait"
        (9:16 reel, 720x1280). ``short``: trim the intro/outro for 30-second videos.
        ``on_progress(step, done, total, message)`` is called as work advances,
        with step "narrate", "render" or "encode"; it must be thread-safe, because
        encoding runs on a worker thread.
        ``timeline``: if given, filled with one entry per scene (part, title,
        start and duration in seconds of the final video, narration text and
        word timings) so the watch page can show scenes, transcript and captions.
        ``voice_language`` / ``caption_language``: en-IN, hi-IN or pa-IN. The
        script is written in English; other languages are translated with
        Sarvam-Translate and voiced with Bulbul v3. Captions default to the
        voice language; a different one gives a bilingual lesson. ``pace``
        is the speaking speed (0.8, 1 or 1.25).
        """
        def report(step, done, total, message):
            if on_progress:
                try:
                    on_progress(step, done, total, message)
                except Exception:  # progress reporting must never break a render
                    logger.debug("progress callback failed", exc_info=True)

        # A folder per render: two videos built at the same time used to share
        # outputs/videos/temp and delete each other's files on cleanup.
        temp_dir = self.settings.video_output_dir / "temp" / Path(output_path).stem
        temp_dir.mkdir(parents=True, exist_ok=True)

        portrait = orientation == "portrait"
        size = (720, 1280) if portrait else self.settings.video_size
        voice_language = voice_language or "en-IN"
        caption_language = caption_language or voice_language
        subtitles = self._subtitle_engine(portrait, caption_language)
        voice_texts, caption_texts = await self._translate_scenes(scenes, voice_language, caption_language, report)
        bookend = 1.2 if short else BOOKEND_DURATION
        timer = RenderTimer()
        clips = []
        temp_files = []

        if scenes and not self.vmake.is_enabled() and os.environ.get("VIDEO_PARALLEL", "1") != "0":
            return await self._assemble_parallel(scenes, subject, output_path, temp_dir, size, timer,
                                                 orientation=orientation, bookend=bookend,
                                                 report=report, timeline=timeline,
                                                 voice_texts=voice_texts, caption_texts=caption_texts,
                                                 voice_language=voice_language,
                                                 caption_language=caption_language, pace=pace)

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
                    self.slide_renderer.render_scene_slide(intro_scene, intro_slide_path, orientation=orientation)
                    temp_files.append(intro_slide_path)

                    intro_clip = ImageClip(intro_slide_path, duration=bookend)
                    intro_clip = apply_ken_burns(intro_clip, bookend)
                    intro_clip = apply_fade_in_out(intro_clip, fade_in_duration=0.5, fade_out_duration=0.5)
                    clips.append(intro_clip)

            # 2a. Narration pass: every scene's voice track first, so the
            # progress page can show "Narrate" and "Render" as separate steps.
            narrated = []
            for i, scene in enumerate(scenes):
                report("narrate", i, len(scenes), f"Narrating scene {i + 1} of {len(scenes)}: {scene.get('slide_title', '')}")
                audio_path = str(temp_dir / f"audio_{i}.mp3")
                with timer.time("tts"):
                    audio_result = await self.tts.generate_scene_audio(
                        voice_texts[i],
                        subject,
                        audio_path,
                        language=voice_language,
                        pace=pace,
                    )
                temp_files.append(audio_path)
                audio_clip = AudioFileClip(audio_path)
                # The segmenter's duration_hint_seconds can hold the slide slightly
                # longer than the narration, but never shorter than the voice track.
                duration = resolve_scene_duration(audio_clip.duration, scene.get("duration_hint_seconds"))
                audio_result["caption_words"] = self._caption_words(
                    audio_result, caption_texts[i], audio_clip.duration,
                    same=caption_language == voice_language)
                narrated.append((audio_result, audio_clip, duration))
            report("narrate", len(scenes), len(scenes), "Narration ready")

            if timeline is not None:
                timeline.clear()
                start = bookend if scenes else 0.0
                for i, (scene, (audio_result, _clip, duration)) in enumerate(zip(scenes, narrated)):
                    timeline.append(self._timeline_entry(scene, start, duration, audio_result,
                                                         voice_texts[i], caption_texts[i]))
                    start += duration

            # 2b. Visual pass: slides, animation and burned-in subtitles.
            for i, scene in enumerate(scenes):
                logger.info("Processing scene %s/%s: %s", i + 1, len(scenes), scene.get("part"))
                report("render", i, len(scenes), f"Drawing scene {i + 1} of {len(scenes)}: {scene.get('slide_title', '')}")
                audio_result, audio_clip, duration = narrated[i]

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
                    self.slide_renderer.render_scene_slide(scene, slide_path, transparent_bg=use_bg_video,
                                                           orientation=orientation)
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
                word_boundaries = audio_result.get("caption_words", [])
                if word_boundaries:
                    with timer.time("subtitles"):
                        scene_video = subtitles.burn_onto(
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
                    self.slide_renderer.render_scene_slide(outro_scene, outro_slide_path, orientation=orientation)
                    temp_files.append(outro_slide_path)

                    outro_clip = ImageClip(outro_slide_path, duration=bookend)
                    outro_clip = apply_ken_burns(outro_clip, bookend)
                    outro_clip = apply_fade_in_out(outro_clip, fade_in_duration=0.5, fade_out_duration=0.5)
                    clips.append(outro_clip)

            report("render", len(scenes), len(scenes), "Slides and subtitles ready")

            # 4. Concatenate and compile final video
            logger.info("Concatenating all video clips...")
            final_video = concatenate_videoclips(clips, method="chain")
            video_duration = final_video.duration

            threads = self.settings.video_threads or os.cpu_count() or 1
            logger.info(
                "Writing final video file to %s (preset=%s, threads=%s)...",
                output_path, self.settings.video_preset, threads,
            )
            report("encode", 0, 100, "Encoding the MP4")
            with timer.time("encode"):
                # Encoding is CPU-bound and takes about a minute. On a worker
                # thread it no longer freezes the server: progress updates keep
                # flowing and other students' requests are still answered.
                await asyncio.to_thread(
                    final_video.write_videofile,
                    output_path,
                    fps=self.settings.video_fps,
                    codec="libx264",
                    audio_codec="aac",
                    preset=self.settings.video_preset,
                    threads=threads,
                    verbose=False,
                    logger=_EncodeProgress(report) if on_progress else None,
                )
            report("encode", 100, 100, "Encoding finished")

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
                "orientation": orientation,
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

    async def _assemble_parallel(self, scenes, subject, output_path, temp_dir, size, timer,
                                 orientation="landscape", bookend=BOOKEND_DURATION,
                                 report=lambda *a: None, timeline=None, voice_texts=None,
                                 caption_texts=None, voice_language="en-IN",
                                 caption_language="en-IN", pace=1.0) -> str:
        """Render slides + audio here, then encode every segment in its own process
        and join them with FFmpeg's concat demuxer (no re-encode)."""
        from app.video.segment_encoder import concat_without_reencode, encode_segments_parallel

        try:
            audio_paths = [str(temp_dir / f"audio_{i}.mp3") for i in range(len(scenes))]
            report("narrate", 0, len(scenes), f"Narrating {len(scenes)} scenes")
            with timer.time("tts"):
                audio_results = await asyncio.gather(*[
                    self.tts.generate_scene_audio(voice_texts[i], subject, audio_paths[i],
                                                  language=voice_language, pace=pace)
                    for i, sc in enumerate(scenes)
                ])
            report("narrate", len(scenes), len(scenes), "Narration ready")

            durations = []
            for i, scene in enumerate(scenes):
                a = AudioFileClip(audio_paths[i])
                durations.append(resolve_scene_duration(a.duration, scene.get("duration_hint_seconds")))
                audio_results[i]["caption_words"] = self._caption_words(
                    audio_results[i], caption_texts[i], a.duration,
                    same=caption_language == voice_language)
                a.close()

            if timeline is not None:
                timeline.clear()
                start = bookend
                for i, (scene, audio_result, duration) in enumerate(zip(scenes, audio_results, durations)):
                    timeline.append(self._timeline_entry(scene, start, duration, audio_result,
                                                         voice_texts[i], caption_texts[i]))
                    start += duration

            n_segments = len(scenes) + 2
            workers = max(1, min(n_segments, (os.cpu_count() or 2) - 1))
            threads = max(1, (os.cpu_count() or 1) // workers)
            common = {"size": list(size), "fps": self.settings.video_fps,
                      "preset": self.settings.video_preset, "threads": threads,
                      "portrait": orientation == "portrait", "caption_language": caption_language}

            jobs = []
            with timer.time("slide_render"):
                bookends = {
                    "intro": {"part": "HOOK", "slide_title": f"NEET Preparation: {subject.title()}",
                              "slide_bullets": ["Targeted Microlearning Module",
                                                "Concept-focused review grounded in NCERT"],
                              "visual_type": "none"},
                    "outro": {"part": "NEET_ALERT", "slide_title": "Ready for the Challenge?",
                              "slide_bullets": ["Proceed to the Quiz section.",
                                                "Test your mastery of this concept now!"],
                              "visual_type": "none"},
                }
                for name in ("intro", "outro"):
                    path = str(temp_dir / f"{name}_slide.png")
                    self.slide_renderer.render_scene_slide(bookends[name], path, orientation=orientation)
                    bookends[name] = path

                jobs.append({**common, "kind": "bookend", "slide_path": bookends["intro"],
                             "duration": bookend, "out_path": str(temp_dir / "seg_000.mp4")})
                for i, scene in enumerate(scenes):
                    duration = durations[i]
                    report("render", i, len(scenes), f"Drawing scene {i + 1} of {len(scenes)}: {scene.get('slide_title', '')}")
                    slide_path = str(temp_dir / f"slide_{i}.png")
                    self.slide_renderer.render_scene_slide(scene, slide_path, orientation=orientation)
                    jobs.append({**common, "kind": "scene", "slide_path": slide_path,
                                 "audio_path": audio_paths[i], "duration": duration,
                                 "animation_type": scene.get("animation_type"),
                                 "word_boundaries": audio_results[i].get("caption_words", []),
                                 "out_path": str(temp_dir / f"seg_{i + 1:03d}.mp4")})
                jobs.append({**common, "kind": "bookend", "slide_path": bookends["outro"],
                             "duration": bookend,
                             "out_path": str(temp_dir / f"seg_{len(scenes) + 1:03d}.mp4")})

            logger.info("Encoding %s segments in %s processes (%s x264 threads each)",
                        len(jobs), workers, threads)
            report("render", len(scenes), len(scenes), "Slides ready")
            report("encode", 0, 100, f"Encoding {len(jobs)} segments in parallel")
            loop = asyncio.get_running_loop()
            with timer.time("encode"):
                seg_paths = await loop.run_in_executor(None, encode_segments_parallel, jobs, workers)
                concat_without_reencode(seg_paths, output_path)
            report("encode", 100, 100, "Encoding finished")

            final = AudioFileClip(output_path)
            video_duration = final.duration
            final.close()

            stats = timer.summary()
            stats.update({
                "scenes": len(scenes),
                "video_duration_seconds": round(video_duration or 0.0, 2),
                "output_size_bytes": os.path.getsize(output_path),
                "vmake_enabled": False,
                "fps": self.settings.video_fps,
                "resolution": f"{size[0]}x{size[1]}",
                "orientation": orientation,
                "x264_preset": self.settings.video_preset,
                "threads": threads,
                "parallel_workers": workers,
            })
            if video_duration:
                stats["realtime_factor"] = round(stats["total_seconds"] / video_duration, 2)
            self.last_render_stats = stats
            logger.info("Parallel assembly completed in %ss: %s", stats["total_seconds"], stats["stages"])
            return output_path
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
