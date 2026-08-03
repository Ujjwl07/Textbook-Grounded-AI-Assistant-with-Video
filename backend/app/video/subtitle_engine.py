import os
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from moviepy.editor import VideoClip

class SubtitleEngine:
    def __init__(self, font_size: int = 28, max_width: int = 900):
        self.font_size = font_size
        self.max_width = max_width
        self.font_path = "C:\\Windows\\Fonts\\arial.ttf" if os.path.exists("C:\\Windows\\Fonts\\arial.ttf") else "arial.ttf"
        try:
            self.font = ImageFont.truetype(self.font_path, self.font_size)
        except Exception:
            self.font = ImageFont.load_default()

    def generate_subtitles_clip(self, word_boundaries: list, duration: float, size: tuple = (1280, 720), highlight_color: tuple = (255, 235, 59)) -> VideoClip:
        """
        Creates a transparent overlay VideoClip containing Karaoke-style subtitles.
        Highlights the active word being spoken.
        """
        W, H = size
        
        # Determine space width
        space_width = 8
        try:
            space_width = self.font.getbbox(" ")[2] - self.font.getbbox(" ")[0]
        except Exception:
            pass
            
        # Group words into lines that fit the max_width
        lines = []
        current_line = []
        current_width = 0
        
        for idx, w_info in enumerate(word_boundaries):
            word = w_info["word"]
            try:
                word_width = self.font.getbbox(word)[2] - self.font.getbbox(word)[0]
            except Exception:
                word_width = len(word) * 12
                
            if current_width + word_width > self.max_width and current_line:
                lines.append(current_line)
                current_line = []
                current_width = 0
                
            current_line.append((idx, w_info, word_width))
            current_width += word_width + space_width
            
        if current_line:
            lines.append(current_line)
            
        line_height = self.font_size + 8
        
        # Subtitle positioning at the bottom center of the slide
        box_y1 = H - 120
        box_y2 = H - 20
        box_center_y = (box_y1 + box_y2) // 2
        
        def make_frame(t):
            # Base frame image (MoviePy expects RGB)
            img = Image.new("RGB", (W, H), (0, 0, 0))
            draw = ImageDraw.Draw(img)
            
            # Find which word index is currently active at time t
            active_idx = -1
            for idx, w_info in enumerate(word_boundaries):
                if w_info["start"] <= t <= w_info["end"]:
                    active_idx = idx
                    break
                    
            start_y = box_center_y - (len(lines) * line_height) // 2
            y = start_y
            
            for line in lines:
                line_w = sum(w[2] for w in line) + (len(line) - 1) * space_width
                x = W // 2 - line_w // 2
                
                for idx, w_info, w_width in line:
                    color = highlight_color if idx == active_idx else (255, 255, 255)
                    draw.text((x, y), w_info["word"], font=self.font, fill=color)
                    x += w_width + space_width
                y += line_height
                
            return np.array(img)

        def make_mask_frame(t):
            # Alpha mask (1-channel float array between 0.0 and 1.0)
            mask_img = Image.new("L", (W, H), 0)
            draw = ImageDraw.Draw(mask_img)
            
            # Draw semi-transparent background bar behind subtitles (160 out of 255 is ~63% opacity)
            draw.rectangle([W//2 - self.max_width//2 - 20, box_y1, W//2 + self.max_width//2 + 20, box_y2], fill=160)
            
            # Draw text characters in full opacity (255 is 100% opacity)
            start_y = box_center_y - (len(lines) * line_height) // 2
            y = start_y
            
            for line in lines:
                line_w = sum(w[2] for w in line) + (len(line) - 1) * space_width
                x = W // 2 - line_w // 2
                
                for idx, w_info, w_width in line:
                    draw.text((x, y), w_info["word"], font=self.font, fill=255)
                    x += w_width + space_width
                y += line_height
                
            return np.array(mask_img) / 255.0

        # Build video and transparency mask clips
        clip = VideoClip(make_frame, duration=duration)
        mask = VideoClip(make_mask_frame, ismask=True, duration=duration)
        return clip.set_mask(mask)
