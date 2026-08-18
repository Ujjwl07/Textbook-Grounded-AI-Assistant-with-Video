import requests
import logging
from moviepy.editor import VideoFileClip, ImageClip, CompositeVideoClip

logger = logging.getLogger(__name__)

VMAKE_PROMPTS = {
    'HOOK': {
        'physics': 'Deep space background, glowing equations floating in zero gravity, dark blue and orange palette, cinematic lighting, 4K',
        'biology': 'Vibrant nature background, DNA helix strand slowly rotating under light, 3D render, dark blue and green palette, 4K',
        'chemistry': 'Molecular network drifting, microscopic molecules, dark blue and purple palette, 4K'
    },
    'CONCEPT': {
        'physics': 'Abstract vector arrows expanding outwards, force fields glowing, blue and white palette, 4K',
        'biology': 'Abstract cell structure cutaway, bioluminescent colors, microscopic world, teal and green palette, ultra-detailed',
        'chemistry': 'Chemical reaction happening in a flask, atoms orbiting, glowing fluid, 4K'
    },
    'EXAMPLE': {
        'physics': 'Inclined plane vector simulation, block sliding down, glowing coordinates, dark background, 4K',
        'biology': 'Mitosis cell dividing diagram, chromosome movement, organic green and orange palette, 4K',
        'chemistry': 'Laboratory glassware with colorful reactions, molecular bonds forming, atom spheres, orange and white palette'
    },
    'MEMORY': {
        'physics': 'Abstract colorful mnemonic visual, bright geometric shapes, memory palace concept, vivid colors',
        'biology': 'Brain network synapses firing, memory retrieval concept, colorful lines, 4K',
        'chemistry': 'Periodic table element blocks shifting, colorful shapes, memory palace visual'
    },
    'NEET_ALERT': {
        'physics': 'Red warning atmosphere, exam hall concept, urgent energy, deep red and yellow palette, dramatic lighting',
        'biology': 'Bacteria structure with highlighted exceptions, red caution warning glow, 4K',
        'chemistry': 'Hazard symbol rotating, red warning lights pulsing, caution text, 4K'
    }
}

class VMakeIntegration:
    def __init__(self, api_key: str = ""):
        self.api_key = api_key
        self.base_url = 'https://api.vmake.ai/v2'

    def is_enabled(self) -> bool:
        return bool(self.api_key)

    def generate_background(self, scene_type: str, subject: str) -> str:
        """
        Calls VMake.ai Image-to-Video API to generate background clip.
        Returns the video URL or None if api_key is missing or API fails.
        """
        if not self.is_enabled():
            logger.info("VMake.ai integration disabled (no API key configured).")
            return None

        st = scene_type.upper()
        subj = subject.lower()
        if st not in VMAKE_PROMPTS:
            st = 'CONCEPT'
        if subj not in ['physics', 'biology', 'chemistry']:
            subj = 'physics'

        prompt = VMAKE_PROMPTS[st][subj]
        logger.info(f"Submitting background prompt to VMake: {prompt}")
        
        try:
            response = requests.post(
                f'{self.base_url}/image-to-video',
                headers={'Authorization': f'Bearer {self.api_key}'},
                json={
                    'model': 'seedance-2.0',
                    'prompt': prompt,
                    'duration': 8,
                    'resolution': '1280x720'
                },
                timeout=10
            )
            if response.status_code == 200:
                res_data = response.json()
                video_url = res_data.get('video_url')
                logger.info(f"VMake.ai generated video URL: {video_url}")
                return video_url
            else:
                logger.warning(f"VMake API error: {response.status_code} - {response.text}")
        except Exception as e:
            logger.error(f"VMake.ai generate_background failed: {e}")
        
        return None

    def composite_slide_over_bg(self, slide_path: str, bg_video_path: str, audio_duration: float) -> VideoFileClip:
        """
        Composites a transparent PIL slide on top of a background video.
        """
        # Load background video and loop it to match duration of the scene
        bg = VideoFileClip(bg_video_path).loop(duration=audio_duration)
        bg = bg.resize((1280, 720))
        
        # Darken background by 60% so slide text is readable
        bg = bg.fl_image(lambda frame: (frame * 0.4).astype('uint8'))
        
        # Load slide as an ImageClip
        slide = ImageClip(slide_path, duration=audio_duration)
        
        # Composite slide with opacity on top of background
        final = CompositeVideoClip([bg, slide.set_opacity(0.92)])
        return final
