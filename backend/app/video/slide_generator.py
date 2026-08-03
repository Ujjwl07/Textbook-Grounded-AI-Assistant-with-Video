import os
import textwrap
from PIL import Image, ImageDraw, ImageFont
from app.video.formula_renderer import render_latex_to_image

SLIDE_W, SLIDE_H = 1280, 720  # HD 16:9

SCENE_THEMES = {
    'HOOK': {
        'bg': (26, 35, 126),       # Deep Navy Blue
        'accent': (255, 111, 0),    # Vibrant Orange
        'text': (255, 255, 255),
        'subtext': (200, 230, 255)
    },
    'CONCEPT': {
        'bg': (21, 101, 192),      # Royal Blue
        'accent': (255, 255, 255),  # Crisp White
        'text': (255, 255, 255),
        'subtext': (220, 240, 255)
    },
    'EXAMPLE': {
        'bg': (27, 94, 32),        # Forest Green
        'accent': (255, 235, 59),   # Sunshine Yellow
        'text': (255, 255, 255),
        'subtext': (220, 255, 220)
    },
    'MEMORY': {
        'bg': (74, 20, 140),       # Royal Purple
        'accent': (255, 167, 38),   # Warm Amber
        'text': (255, 255, 255),
        'subtext': (240, 220, 255)
    },
    'NEET_ALERT': {
        'bg': (183, 28, 28),       # Dark Crimson Red
        'accent': (255, 245, 157),  # Soft Light Yellow
        'text': (255, 255, 255),
        'subtext': (255, 220, 220)
    },
}

class SlideRenderer:
    def __init__(self):
        # Cache fonts
        self.fonts = {}
        self._load_fonts()

    def _load_fonts(self):
        # Attempt to load premium fonts on Windows, with fallback to default
        system_fonts = [
            ("title", "arial.ttf", 46),
            ("body", "arial.ttf", 26),
            ("badge", "arial.ttf", 20),
            ("caption", "arial.ttf", 18),
        ]
        
        windows_font_dir = "C:\\Windows\\Fonts"
        for role, name, size in system_fonts:
            font_path = os.path.join(windows_font_dir, name)
            try:
                if os.path.exists(font_path):
                    self.fonts[f"{role}_{size}"] = ImageFont.truetype(font_path, size)
                else:
                    self.fonts[f"{role}_{size}"] = ImageFont.truetype(name, size)
            except Exception:
                # Fallback to default
                self.fonts[f"{role}_{size}"] = ImageFont.load_default()

    def get_font(self, role: str, size: int):
        key = f"{role}_{size}"
        if key in self.fonts:
            return self.fonts[key]
        
        # Try dynamic loading
        windows_font_dir = "C:\\Windows\\Fonts"
        font_path = os.path.join(windows_font_dir, "arial.ttf")
        try:
            if os.path.exists(font_path):
                self.fonts[key] = ImageFont.truetype(font_path, size)
            else:
                self.fonts[key] = ImageFont.truetype("arial.ttf", size)
            return self.fonts[key]
        except Exception:
            return ImageFont.load_default()

    def render_scene_slide(self, scene: dict, output_path: str, transparent_bg: bool = False) -> str:
        """
        Renders a full slide image based on the scene parameters and saves to output_path.
        Returns the output file path.
        """
        part_name = scene.get('part', 'CONCEPT').upper()
        theme = SCENE_THEMES.get(part_name, SCENE_THEMES['CONCEPT'])
        
        # Create base image (RGBA to support transparency when compositing with background videos)
        bg_alpha = 0 if transparent_bg else 255
        img = Image.new('RGBA', (SLIDE_W, SLIDE_H), (theme['bg'][0], theme['bg'][1], theme['bg'][2], bg_alpha))
        draw = ImageDraw.Draw(img)
        
        # Draw background decoration if not transparent
        if not transparent_bg:
            draw.polygon([(800, 0), (SLIDE_W, 0), (SLIDE_W, SLIDE_H), (1050, SLIDE_H)], fill=tuple(int(c * 0.9) for c in theme['bg']))
        
        # 1. Accent bar on left
        # Accent bar should be fully opaque (255 alpha)
        accent_color = (theme['accent'][0], theme['accent'][1], theme['accent'][2], 255)
        draw.rectangle([0, 0, 10, SLIDE_H], fill=accent_color)
        
        # 2. Part label (top-left badge)
        badge_text = part_name.replace('_', ' ')
        badge_font = self.get_font("badge", 20)
        # Determine text size dynamically
        try:
            bbox = draw.textbbox((0, 0), badge_text, font=badge_font)
            text_w = bbox[2] - bbox[0]
            text_h = bbox[3] - bbox[1]
        except AttributeError:
            text_w, text_h = 100, 20  # estimate
            
        badge_x1, badge_y1 = 40, 40
        badge_x2, badge_y2 = badge_x1 + text_w + 30, badge_y1 + 45
        draw.rounded_rectangle([badge_x1, badge_y1, badge_x2, badge_y2], radius=10, fill=accent_color)
        
        # Draw badge text (color contrasts with badge background)
        badge_text_color = (0, 0, 0, 255) if part_name in ['EXAMPLE', 'NEET_ALERT'] else (theme['bg'][0], theme['bg'][1], theme['bg'][2], 255)
        draw.text((badge_x1 + 15, badge_y1 + 10), badge_text, font=badge_font, fill=badge_text_color)
        
        # 3. Main title (top left below badge)
        title_text = scene.get('slide_title', 'NCERT Concepts')
        title_font = self.get_font("title", 46)
        
        # Wrap title if too long
        title_wrapper = textwrap.TextWrapper(width=30)
        title_lines = title_wrapper.wrap(title_text)
        
        title_y = 110
        for line in title_lines:
            draw.text((40, title_y), line, font=title_font, fill=theme['text'])
            title_y += 55
            
        # 4. Bullet points (left side)
        bullets = scene.get('slide_bullets', [])
        body_font = self.get_font("body", 26)
        bullet_y = max(title_y + 30, 230)
        
        for bullet in bullets[:3]:  # max 3 bullet points
            # Wrap bullet point
            bullet_wrapper = textwrap.TextWrapper(width=45)
            bullet_lines = bullet_wrapper.wrap(bullet)
            
            # Draw bullet symbol
            draw.text((40, bullet_y), "•", font=body_font, fill=theme['accent'])
            
            for line_idx, line in enumerate(bullet_lines):
                draw.text((70, bullet_y + (line_idx * 32)), line, font=body_font, fill=theme['text'])
            
            bullet_y += len(bullet_lines) * 32 + 25
            
        # 5. Visual section on the right side (x = 750 to 1200)
        visual_type = scene.get('visual_type', 'none').lower()
        formula_latex = scene.get('formula_latex')
        
        if visual_type == 'formula' and formula_latex:
            # Render and paste LaTeX image
            try:
                formula_img = render_latex_to_image(formula_latex, font_size=28, color='white')
                # Center formula in the right area
                fx = 750 + (450 - formula_img.width) // 2
                fy = 200 + (400 - formula_img.height) // 2
                img.paste(formula_img, (max(700, fx), max(150, fy)), formula_img)
            except Exception as e:
                # Fallback to plain text formula
                draw.text((750, 300), formula_latex, font=body_font, fill=theme['accent'])
                
        elif visual_type == 'diagram':
            # Draw a beautiful mock diagram (e.g. cells or atoms)
            self._draw_mock_diagram(draw, theme)
            
        elif visual_type == 'process':
            # Draw a process flowchart
            self._draw_process_flowchart(draw, theme)
            
        elif visual_type == 'comparison':
            # Draw a comparison double box
            self._draw_comparison(draw, theme)
            
        elif visual_type == 'alert':
            # Draw a prominent alert shield
            self._draw_alert_graphic(draw, theme)
            
        # Save image
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        img.save(output_path, "PNG")
        return output_path

    def _draw_mock_diagram(self, draw: ImageDraw.Draw, theme: dict):
        """Draws a stylized biological cell/atomic diagram."""
        center_x, center_y = 980, 360
        # Draw outer circle (cell membrane)
        draw.ellipse([center_x - 140, center_y - 140, center_x + 140, center_y + 140], 
                     outline=theme['accent'], width=4)
        # Draw inner circle (nucleus)
        draw.ellipse([center_x - 50, center_y - 50, center_x + 50, center_y + 50], 
                     fill=theme['accent'], outline=(255, 255, 255), width=2)
        # Draw some smaller cytoplasm dots
        draw.ellipse([center_x - 80, center_y - 70, center_x - 72, center_y - 62], fill=(255, 255, 255))
        draw.ellipse([center_x + 70, center_y - 80, center_x + 78, center_y - 72], fill=(255, 255, 255))
        draw.ellipse([center_x - 60, center_y + 80, center_x - 52, center_y + 88], fill=(255, 255, 255))
        
        caption_font = self.get_font("caption", 18)
        draw.text((center_x - 60, center_y + 160), "Diagram Representation", font=caption_font, fill=theme['subtext'])

    def _draw_process_flowchart(self, draw: ImageDraw.Draw, theme: dict):
        """Draws three sequential horizontal boxes connected by arrows."""
        y_center = 360
        box_w, box_h = 110, 80
        x_coords = [760, 930, 1100]
        caption_font = self.get_font("caption", 18)
        
        for idx, x in enumerate(x_coords):
            # Draw box
            draw.rounded_rectangle([x, y_center - box_h//2, x + box_w, y_center + box_h//2], radius=6, 
                                   fill=None, outline=theme['accent'], width=3)
            # Label
            draw.text((x + 25, y_center - 10), f"Step {idx+1}", font=caption_font, fill=theme['text'])
            
            # Arrow to next
            if idx < 2:
                arrow_x = x + box_w + 10
                draw.line([(arrow_x, y_center), (arrow_x + 40, y_center)], fill=theme['accent'], width=3)
                draw.polygon([(arrow_x + 40, y_center), (arrow_x + 30, y_center - 8), (arrow_x + 30, y_center + 8)], fill=theme['accent'])

    def _draw_comparison(self, draw: ImageDraw.Draw, theme: dict):
        """Draws a side-by-side comparison block."""
        y_center = 360
        box_w, box_h = 180, 220
        caption_font = self.get_font("caption", 18)
        
        # Left block
        draw.rounded_rectangle([750, y_center - box_h//2, 930, y_center + box_h//2], radius=8, 
                               fill=None, outline=theme['accent'], width=3)
        draw.text((790, y_center - 90), "Condition A", font=caption_font, fill=theme['accent'])
        draw.line([(770, y_center - 40), (910, y_center - 40)], fill=theme['subtext'], width=1)
        
        # Right block
        draw.rounded_rectangle([970, y_center - box_h//2, 1150, y_center + box_h//2], radius=8, 
                               fill=None, outline=(255, 255, 255), width=3)
        draw.text((1010, y_center - 90), "Condition B", font=caption_font, fill=(255, 255, 255))
        draw.line([(990, y_center - 40), (1130, y_center - 40)], fill=theme['subtext'], width=1)

    def _draw_alert_graphic(self, draw: ImageDraw.Draw, theme: dict):
        """Draws a warning triangle icon on the right side."""
        cx, cy = 960, 360
        # Draw dynamic glowing hazard warning triangle
        draw.polygon([(cx, cy - 100), (cx - 110, cy + 90), (cx + 110, cy + 90)], 
                     fill=None, outline=theme['accent'], width=5)
        # Exclamation point inside
        draw.rectangle([cx - 5, cy - 50, cx + 5, cy + 30], fill=theme['accent'])
        draw.ellipse([cx - 6, cy + 50, cx + 6, cy + 62], fill=theme['accent'])
        
        caption_font = self.get_font("caption", 18)
        draw.text((cx - 75, cy + 120), "CRITICAL NEET TRAP", font=caption_font, fill=theme['accent'])
