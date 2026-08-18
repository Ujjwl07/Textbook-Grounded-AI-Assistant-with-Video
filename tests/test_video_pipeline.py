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
    print("Initializing components for video pipeline test...")
    settings = get_settings()
    
    # Ensure output directory exists
    settings.video_output_dir.mkdir(parents=True, exist_ok=True)
    
    tts = TTSGenerator()
    renderer = SlideRenderer()
    assembler = VideoAssembler(tts, renderer)
    
    # Define a simple 2-scene list to run quickly
    test_scenes = [
        {
            "part": "HOOK",
            "slide_title": "Understanding Newton's Third Law",
            "slide_bullets": [
                "To every action, there is an equal and opposite reaction.",
                "Forces always occur in matched pairs.",
                "Crucial concept for mechanics questions."
            ],
            "narration_text": "Did you know that you cannot push on a wall without it pushing back on you? This is the core of Newton's third law of motion. To every action, there is always an equal and opposite reaction.",
            "visual_type": "alert"
        },
        {
            "part": "CONCEPT",
            "slide_title": "Mathematical Expression",
            "slide_bullets": [
                "Action and reaction forces act on different bodies.",
                "F_AB equals negative F_BA.",
                "Vectors are equal in magnitude, opposite in direction."
            ],
            "narration_text": "Mathematically, we write this as F A B equals negative F B A. Remember, these forces act on two completely different bodies, so they never cancel each other out.",
            "visual_type": "formula",
            "formula_latex": r"\vec{F}_{AB} = -\vec{F}_{BA}"
        }
    ]
    
    output_video_path = str(settings.video_output_dir / "test_verification.mp4")
    if os.path.exists(output_video_path):
        os.remove(output_video_path)
        
    print(f"Assembling video and compiling to: {output_video_path} ...")
    await assembler.assemble_full_video(test_scenes, "physics", output_video_path)
    
    # Check if file exists and has size
    if os.path.exists(output_video_path) and os.path.getsize(output_video_path) > 0:
        print(f"SUCCESS: Video file successfully generated! Size: {os.path.getsize(output_video_path)} bytes.")
    else:
        print("FAILURE: Video file was not generated or is empty.")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
