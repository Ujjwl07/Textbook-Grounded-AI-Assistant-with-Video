import os
import textwrap
from PIL import Image, ImageDraw
from app.video.formula_renderer import render_latex_to_image
from app.video.fonts import load_font


def hex_to_rgb(value: str):
    """Convert a '#RRGGBB' string to an (r, g, b) tuple. Returns None if unparseable."""
    if not value or not isinstance(value, str):
        return None
    value = value.strip().lstrip('#')
    if len(value) == 3:
        value = ''.join(ch * 2 for ch in value)
    if len(value) != 6:
        return None
    try:
        return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return None

SLIDE_W, SLIDE_H = 1280, 720  # HD 16:9

# Title-safe area. Ken Burns / zoom animations centre-crop the frame, so any
# element drawn outside this margin is clipped once the zoom reaches its peak.
# Must stay larger than the crop implied by animation_engine.MAX_ZOOM
# (1.06 removes ~36 px horizontally and ~20 px vertically).
SAFE_MARGIN_X = 80
SAFE_MARGIN_Y = 50

# Right-hand visual panel, expressed inside the safe area.
VISUAL_X0 = 730
VISUAL_X1 = SLIDE_W - SAFE_MARGIN_X   # 1200
VISUAL_Y0 = 170
VISUAL_Y1 = 560

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
    # Weight per text role — titles and badges render bold where a bold face exists.
    ROLE_WEIGHTS = {'title': True, 'badge': True, 'body': False, 'caption': False}

    def __init__(self):
        # Warm the font cache for the sizes used on every slide.
        for role, size in (("title", 46), ("body", 26), ("badge", 20), ("caption", 18)):
            self.get_font(role, size)

    def get_font(self, role: str, size: int):
        """Resolve a font for a text role at ``size`` (cached inside app.video.fonts)."""
        return load_font(size, bold=self.ROLE_WEIGHTS.get(role, False))

    def resolve_theme(self, scene: dict) -> dict:
        """Theme for this scene, honouring a per-scene ``background_color`` override.

        The scene segmentation prompt emits a ``background_color`` hex per part.
        When present it wins over the built-in palette so a director can retint a
        scene without a code change; accent/text colours are kept from the part
        theme so contrast rules still hold.
        """
        part_name = scene.get('part', 'CONCEPT').upper()
        theme = dict(SCENE_THEMES.get(part_name, SCENE_THEMES['CONCEPT']))
        override = hex_to_rgb(scene.get('background_color'))
        if override:
            theme['bg'] = override
        return theme

    def render_scene_slide(self, scene: dict, output_path: str, transparent_bg: bool = False) -> str:
        """
        Renders a full slide image based on the scene parameters and saves to output_path.
        Returns the output file path.
        """
        part_name = scene.get('part', 'CONCEPT').upper()
        theme = self.resolve_theme(scene)

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
        draw.rectangle([SAFE_MARGIN_X - 36, 0, SAFE_MARGIN_X - 20, SLIDE_H], fill=accent_color)
        
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
            
        badge_x1, badge_y1 = SAFE_MARGIN_X, SAFE_MARGIN_Y
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
        
        title_y = SAFE_MARGIN_Y + 70
        for line in title_lines:
            draw.text((SAFE_MARGIN_X, title_y), line, font=title_font, fill=theme['text'])
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
            draw.text((SAFE_MARGIN_X, bullet_y), "•", font=body_font, fill=theme['accent'])
            
            for line_idx, line in enumerate(bullet_lines):
                draw.text((SAFE_MARGIN_X + 30, bullet_y + (line_idx * 32)), line, font=body_font, fill=theme['text'])
            
            bullet_y += len(bullet_lines) * 32 + 25
            
        # 5. Visual section on the right side, clamped to the safe area
        visual_type = scene.get('visual_type', 'none').lower()
        formula_latex = scene.get('formula_latex')
        
        if visual_type == 'formula' and formula_latex:
            # Render and paste LaTeX image
            try:
                formula_img = render_latex_to_image(formula_latex, font_size=28, color='white')
                # Matplotlib sizes the output from the expression, so a long
                # formula easily exceeds the panel and used to bleed off-slide.
                # Scale it down to fit, preserving aspect ratio.
                formula_img = self._fit_within(
                    formula_img, VISUAL_X1 - VISUAL_X0, VISUAL_Y1 - VISUAL_Y0
                )
                # Centre the formula inside the visual panel.
                fx = VISUAL_X0 + (VISUAL_X1 - VISUAL_X0 - formula_img.width) // 2
                fy = VISUAL_Y0 + (VISUAL_Y1 - VISUAL_Y0 - formula_img.height) // 2
                img.paste(formula_img, (fx, fy), formula_img)
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

    @staticmethod
    def _fit_within(image: Image.Image, max_w: int, max_h: int) -> Image.Image:
        """Downscale ``image`` to fit inside ``max_w`` x ``max_h``, keeping aspect."""
        if image.width <= max_w and image.height <= max_h:
            return image
        scale = min(max_w / image.width, max_h / image.height)
        new_size = (max(1, int(image.width * scale)), max(1, int(image.height * scale)))
        return image.resize(new_size, Image.LANCZOS)

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
