import os
import shutil
import logging
from pathlib import Path
from moviepy.editor import (
    AudioFileClip,
    ImageClip,
    CompositeVideoClip,
    concatenate_videoclips
)
from app.tts.tts_generator import TTSGenerator
from app.video.slide_generator import SlideRenderer
from app.video.subtitle_engine import SubtitleEngine
from app.video.animation_engine import apply_ken_burns, apply_fade_in_out
from app.video.vmake_integration import VMakeIntegration
from app.core.config import get_settings

logger = logging.getLogger(__name__)

class VideoAssembler:
    def __init__(self, tts: TTSGenerator, slide_renderer: SlideRenderer):
        self.tts = tts
        self.slide_renderer = slide_renderer
        self.subtitle_engine = SubtitleEngine()
        self.settings = get_settings()
        
        # Configure VMake.ai Integration
        vmake_api_key = getattr(self.settings, 'vmake_api_key', '')
        self.vmake = VMakeIntegration(vmake_api_key)

    async def assemble_full_video(self, scenes: list, subject: str, output_path: str) -> str:
        """
        Takes a list of scenes and subject, synthesizes TTS, generates slides,
        overlays subtitles, applies transitions/animations, and concatenates
        into a final MP4 video.
        """
        temp_dir = self.settings.video_output_dir / "temp"
        temp_dir.mkdir(parents=True, exist_ok=True)
        
        clips = []
        temp_files = []
        
        try:
            # 1. Generate Intro Slide (if list is not empty)
            if scenes:
                intro_scene = {
                    "part": "HOOK",
                    "slide_title": f"NEET Preparation: {subject.title()}",
                    "slide_bullets": [
                        f"Targeted Microlearning Module",
                        f"Concept-focused review grounded in NCERT"
                    ],
                    "visual_type": "none"
                }
                intro_slide_path = str(temp_dir / "intro_slide.png")
                self.slide_renderer.render_scene_slide(intro_scene, intro_slide_path)
                temp_files.append(intro_slide_path)
                
                # Intro clip lasts 2.5 seconds
                intro_clip = ImageClip(intro_slide_path, duration=2.5)
                intro_clip = apply_fade_in_out(intro_clip, fade_in_duration=0.5, fade_out_duration=0.5)
                clips.append(intro_clip)

            # 2. Generate Scene Clips
            for i, scene in enumerate(scenes):
                logger.info(f"Processing scene {i+1}/{len(scenes)}: {scene.get('part')}")
                
                # A. Generate narration audio
                audio_path = str(temp_dir / f"audio_{i}.mp3")
                audio_result = await self.tts.generate_scene_audio(
                    scene['narration_text'], 
                    subject, 
                    audio_path
                )
                temp_files.append(audio_path)
                
                # Load audio clip
                audio_clip = AudioFileClip(audio_path)
                duration = audio_clip.duration
                
                # B. Render slide
                slide_path = str(temp_dir / f"slide_{i}.png")
                
                # Determine if we should generate a background video with VMake.ai
                bg_video_url = None
                if self.vmake.is_enabled():
                    bg_video_url = self.vmake.generate_background(scene['part'], subject)
                
                # If background video is available, render transparent slide, otherwise solid
                use_bg_video = bg_video_url is not None
                self.slide_renderer.render_scene_slide(scene, slide_path, transparent_bg=use_bg_video)
                temp_files.append(slide_path)
                
                # C. Build slide background visual (Static zoom slide OR transparent slide over looped video)
                if use_bg_video:
                    # Download the background video
                    bg_video_path = str(temp_dir / f"bg_{i}.mp4")
                    try:
                        import urllib.request
                        urllib.request.urlretrieve(bg_video_url, bg_video_path)
                        temp_files.append(bg_video_path)
                        
                        # Composite slide transparent overlay on top of looped video
                        scene_video = self.vmake.composite_slide_over_bg(slide_path, bg_video_path, duration)
                    except Exception as e:
                        logger.error(f"Failed to use VMake background: {e}. Falling back to standard slide.")
                        img_clip = ImageClip(slide_path, duration=duration)
                        scene_video = apply_ken_burns(img_clip, duration)
                else:
                    img_clip = ImageClip(slide_path, duration=duration)
                    scene_video = apply_ken_burns(img_clip, duration)
                
                # D. Generate word-level Karaoke subtitles
                word_boundaries = audio_result.get("word_boundaries", [])
                if word_boundaries:
                    sub_clip = self.subtitle_engine.generate_subtitles_clip(
                        word_boundaries, 
                        duration, 
                        size=(1280, 720)
                    )
                    # Overlay subtitles on top of slide video
                    scene_video = CompositeVideoClip([scene_video, sub_clip])
                
                # E. Combine video and audio
                scene_video = scene_video.set_audio(audio_clip)
                scene_video = apply_fade_in_out(scene_video, fade_in_duration=0.3, fade_out_duration=0.3)
                clips.append(scene_video)
                
            # 3. Generate Outro Slide
            if scenes:
                outro_scene = {
                    "part": "NEET_ALERT",
                    "slide_title": "Ready for the Challenge?",
                    "slide_bullets": [
                        "Proceed to the Quiz section.",
                        "Test your mastery of this concept now!"
                    ],
                    "visual_type": "none"
                }
                outro_slide_path = str(temp_dir / "outro_slide.png")
                self.slide_renderer.render_scene_slide(outro_scene, outro_slide_path)
                temp_files.append(outro_slide_path)
                
                outro_clip = ImageClip(outro_slide_path, duration=2.5)
                outro_clip = apply_fade_in_out(outro_clip, fade_in_duration=0.5, fade_out_duration=0.5)
                clips.append(outro_clip)

            # 4. Concatenate and compile final video
            logger.info("Concatenating all video clips...")
            final_video = concatenate_videoclips(clips, method="compose")
            
            # Write final file to target output path
            logger.info(f"Writing final video file to {output_path}...")
            final_video.write_videofile(
                output_path, 
                fps=24, 
                codec="libx264", 
                audio_codec="aac",
                verbose=False,
                logger=None
            )
            
            # Close all clip resources to release files
            final_video.close()
            for clip in clips:
                clip.close()
                
            logger.info("Video assembly completed successfully.")
            return output_path
            
        finally:
            # Cleanup temporary file resources
            logger.info("Cleaning up temporary video assembly files...")
            for f in temp_files:
                try:
                    if os.path.exists(f):
                        os.remove(f)
                except Exception as e:
                    logger.warning(f"Could not remove temp file {f}: {e}")
                    
            try:
                if temp_dir.exists():
                    shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception:
                pass
