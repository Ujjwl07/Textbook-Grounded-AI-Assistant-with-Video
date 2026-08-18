import asyncio
import os
import sys

# Ensure backend directory is in path
backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend"))
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

from app.tts.tts_generator import TTSGenerator
from app.video.slide_generator import SlideRenderer
from app.video.video_assembler import VideoAssembler
from app.core.config import get_settings

async def main():
    print("STEP 1: Initializing components...")
    settings = get_settings()
    settings.video_output_dir.mkdir(parents=True, exist_ok=True)
    
    tts = TTSGenerator()
    renderer = SlideRenderer()
    
    # Let's inspect parts of the assembler
    temp_dir = settings.video_output_dir / "debug_temp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    
    scene = {
        "part": "HOOK",
        "slide_title": "Debug Test",
        "slide_bullets": ["Bullet 1", "Bullet 2"],
        "narration_text": "This is a quick debug text to test where the pipeline hangs.",
        "visual_type": "alert"
    }
    
    # Test A: TTS
    print("STEP 2: Testing TTS audio generation...")
    audio_path = str(temp_dir / "debug_audio.mp3")
    audio_result = await tts.generate_scene_audio(scene["narration_text"], "physics", audio_path)
    print(f"TTS complete: {audio_result.get('audio_path')} exists={os.path.exists(audio_path)}")
    
    # Test B: Slide
    print("STEP 3: Testing slide rendering...")
    slide_path = str(temp_dir / "debug_slide.png")
    renderer.render_scene_slide(scene, slide_path)
    print(f"Slide complete: {slide_path} exists={os.path.exists(slide_path)}")
    
    # Test C: Loading clips and animating
    print("STEP 4: Loading clips in MoviePy...")
    from moviepy.editor import AudioFileClip, ImageClip, CompositeVideoClip
    from app.video.animation_engine import apply_ken_burns, apply_fade_in_out
    
    audio_clip = AudioFileClip(audio_path)
    duration = audio_clip.duration
    print(f"Audio loaded. Duration: {duration}")
    
    img_clip = ImageClip(slide_path, duration=duration)
    print("Image clip loaded.")
    
    scene_video = apply_ken_burns(img_clip, duration)
    print("Ken Burns applied.")
    
    # Test D: Subtitles
    print("STEP 5: Testing subtitles generation...")
    from app.video.subtitle_engine import SubtitleEngine
    sub_engine = SubtitleEngine()
    word_boundaries = audio_result.get("word_boundaries", [])
    print(f"Word boundaries count: {len(word_boundaries)}")
    
    sub_clip = sub_engine.generate_subtitles_clip(word_boundaries, duration)
    print("Subtitle clip created.")
    
    # Test E: Composite
    print("STEP 6: Compositing clips...")
    scene_video = CompositeVideoClip([scene_video, sub_clip])
    scene_video = scene_video.set_audio(audio_clip)
    print("Composite complete.")
    
    # Test F: Write output
    print("STEP 7: Writing output debug file...")
    output_video_path = str(settings.video_output_dir / "debug_output.mp4")
    if os.path.exists(output_video_path):
        os.remove(output_video_path)
        
    scene_video.write_videofile(
        output_video_path,
        fps=24,
        codec="libx264",
        audio_codec="aac",
        verbose=True,
        logger='bar'
    )
    print("STEP 8: Cleanup and verification...")
    scene_video.close()
    audio_clip.close()
    sub_clip.close()
    print(f"Done! File exists={os.path.exists(output_video_path)} size={os.path.getsize(output_video_path) if os.path.exists(output_video_path) else 0}")

if __name__ == "__main__":
    asyncio.run(main())
