"""PIL slide renderer for the five NEET scene themes (Purnika, Section 11.4 #1).

Slides are composed, not templated: the layout adapts to what the scene supplies.
A scene with a definition gets a quoted definition card as the hero element; a
scene with a figure gets a photo panel; a scene with process steps gets a real
flowchart with the step names on it.

Layout (1280x720, title-safe margins so zoom cannot clip anything):

    +--------------------------------------------------------------+
    | [BADGE]                             o--o--o--o--o  flow strip |
    | Title                                                          |
    | +----------------------------+   +--------------------------+ |
    | | " Definition card          |   |                          | |
    | +----------------------------+   |   visual panel           | |
    | * bullet                         |   (figure / flow /       | |
    | * bullet                         |    comparison / formula) | |
    | * bullet                         |                          | |
    |                                  +--------------------------+ |
    |            (subtitle band is burned in later by the assembler) |
    +--------------------------------------------------------------+
"""

import os

from PIL import Image, ImageDraw

from app.video.fonts import load_font
from app.video.formula_renderer import render_latex_to_image
from app.video.layout import (
    darken,
    draw_lines,
    fit_text,
    lighten,
    readable_on,
    text_size,
    text_width,
    wrap_by_width,
)
from app.video import visuals


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

# The assembler burns the subtitle band over the bottom ~120 px, so slide
# content stops above it.
CONTENT_BOTTOM = 580

# Left text column and right visual panel.
TEXT_X = SAFE_MARGIN_X
TEXT_W = 600
VISUAL_X0 = 730
VISUAL_X1 = SLIDE_W - SAFE_MARGIN_X   # 1200
VISUAL_Y0 = 190
VISUAL_Y1 = CONTENT_BOTTOM

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
    ROLE_WEIGHTS = {'title': True, 'badge': True, 'body': False,
                    'caption': False, 'definition': False, 'source': False}

    def __init__(self):
        # Warm the font cache for the sizes used on every slide.
        for role, size in (("title", 44), ("body", 24), ("badge", 20), ("caption", 16)):
            self.get_font(role, size)

    def get_font(self, role: str, size: int):
        """Resolve a font for a text role at ``size`` (cached inside app.video.fonts)."""
        return load_font(size, bold=self.ROLE_WEIGHTS.get(role, False))

    def _body_font(self, size: int):
        """Callable of size -> font, for the auto-fitting helpers."""
        return load_font(size, bold=False)

    def _bold_font(self, size: int):
        return load_font(size, bold=True)

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

    # -- individual elements ----------------------------------------------

    def _draw_background(self, img, draw, theme, transparent_bg: bool):
        if transparent_bg:
            return
        # Diagonal tint panel behind the visual column.
        draw.polygon([(820, 0), (SLIDE_W, 0), (SLIDE_W, SLIDE_H), (1040, SLIDE_H)],
                     fill=darken(theme['bg'], 0.10))

    def _draw_badge(self, draw, theme, part_name: str) -> None:
        badge_text = part_name.replace('_', ' ')
        font = self.get_font("badge", 20)
        width, height = text_size(badge_text, font)
        x1, y1 = SAFE_MARGIN_X, SAFE_MARGIN_Y
        x2, y2 = x1 + width + 30, y1 + 40
        accent = tuple(theme['accent'][:3]) + (255,)
        draw.rounded_rectangle([x1, y1, x2, y2], radius=10, fill=accent)
        draw.text((x1 + 15, y1 + (40 - height) // 2 - 2), badge_text,
                  font=font, fill=readable_on(theme['accent']))

    def _draw_title(self, draw, theme, title: str) -> int:
        """Draw the title, auto-shrinking to fit two lines. Returns the y below it."""
        font, lines, line_height = fit_text(
            title, self._bold_font, TEXT_W, 120, sizes=[44, 38, 34, 30]
        )
        y = SAFE_MARGIN_Y + 58
        return draw_lines(draw, (TEXT_X, y), lines, font, theme['text'], line_height)

    def _draw_definition(self, draw, theme, definition: str, source: str, y: int) -> int:
        """Quoted definition card — the element the slides were missing.

        A NEET student needs the exact NCERT wording on screen, not a paraphrase
        in the narration only. The card is visually distinct from the bullets so
        it reads as "this is the definition to memorise".
        """
        if not definition:
            return y

        font, lines, line_height = fit_text(
            definition, self._body_font, TEXT_W - 56, 190, sizes=[24, 22, 20, 18]
        )
        source_font = self.get_font("source", 15)
        body_h = len(lines) * line_height
        card_h = body_h + 34 + (22 if source else 0)

        draw.rounded_rectangle([TEXT_X, y, TEXT_X + TEXT_W, y + card_h],
                               radius=12, fill=lighten(theme['bg'], 0.14))
        # Accent spine
        draw.rounded_rectangle([TEXT_X, y, TEXT_X + 6, y + card_h], radius=3,
                               fill=theme['accent'])
        # Opening quote mark
        quote_font = self._bold_font(46)
        draw.text((TEXT_X + 18, y - 4), "“", font=quote_font, fill=theme['accent'])

        text_y = y + 16
        text_y = draw_lines(draw, (TEXT_X + 44, text_y), lines, font,
                            theme['text'], line_height)

        if source:
            draw.text((TEXT_X + 44, text_y + 4), f"— {source}",
                      font=source_font, fill=theme['subtext'])

        return y + card_h + 20

    def _draw_bullets(self, draw, theme, bullets, y: int) -> int:
        if not bullets:
            return y
        font = self.get_font("body", 24)
        for bullet in list(bullets)[:3]:
            if y > CONTENT_BOTTOM - 30:
                break
            lines = wrap_by_width(str(bullet), font, TEXT_W - 34)[:3]
            draw.ellipse([TEXT_X + 3, y + 9, TEXT_X + 11, y + 17], fill=theme['accent'])
            for line in lines:
                draw.text((TEXT_X + 28, y), line, font=font, fill=theme['text'])
                y += font.size + 8
            y += 14
        return y

    def _draw_formula(self, img, theme, formula_latex: str, box) -> None:
        x0, y0, x1, y1 = box
        try:
            formula_img = render_latex_to_image(formula_latex, font_size=28, color='white')
        except Exception:
            draw = ImageDraw.Draw(img)
            draw.text((x0, (y0 + y1) // 2), formula_latex,
                      font=self.get_font("body", 24), fill=theme['accent'])
            return
        # Matplotlib sizes the output from the expression, so a long formula
        # easily exceeds the panel and used to bleed off-slide.
        formula_img = self._fit_within(formula_img, x1 - x0, y1 - y0)
        fx = x0 + (x1 - x0 - formula_img.width) // 2
        fy = y0 + (y1 - y0 - formula_img.height) // 2
        img.paste(formula_img, (fx, fy), formula_img)

    def _draw_concept_diagram(self, img, theme, scene: dict, box) -> bool:
        """Draw a topic-matched concept diagram into the visual panel.

        Returns False when no diagram fits the topic, so the caller falls back
        to the text panels — an unrelated diagram is worse than none.
        """
        from app.video import diagrams

        x0, y0, x1, y1 = box
        caption = str(scene.get('diagram_caption', '')).strip()
        caption_h = 34 if caption else 0

        drawing = diagrams.render_for_topic(
            scene['diagram_topic'],
            theme,
            chapter=scene.get('diagram_chapter', ''),
            subject=scene.get('diagram_subject', ''),
            size=(x1 - x0, (y1 - y0) - caption_h),
            labels=scene.get('diagram_labels'),
        )
        if drawing is None:
            return False

        # Scale to fill the panel. matplotlib's tight bounding box crops the
        # figure smaller than requested, and _fit_within only shrinks, so the
        # diagram used to sit small in the middle of an empty panel.
        drawing = self._fit_to_box(drawing, x1 - x0, (y1 - y0) - caption_h)
        dx = x0 + (x1 - x0 - drawing.width) // 2
        dy = y0 + ((y1 - y0 - caption_h) - drawing.height) // 2
        img.paste(drawing, (dx, dy), drawing)

        if caption:
            visuals.draw_caption(ImageDraw.Draw(img), (x0, y1 - caption_h, x1, y1),
                                 theme, caption, self.get_font("caption", 16))
        return True

    # -- main entry point --------------------------------------------------

    def render_scene_slide(self, scene: dict, output_path: str, transparent_bg: bool = False) -> str:
        """Render one scene to a PNG and return the path."""
        part_name = scene.get('part', 'CONCEPT').upper()
        theme = self.resolve_theme(scene)

        bg_alpha = 0 if transparent_bg else 255
        img = Image.new('RGBA', (SLIDE_W, SLIDE_H),
                        tuple(theme['bg'][:3]) + (bg_alpha,))
        draw = ImageDraw.Draw(img)

        self._draw_background(img, draw, theme, transparent_bg)

        # Accent bar, inside the safe area so zoom cannot crop it away.
        draw.rectangle([SAFE_MARGIN_X - 36, 0, SAFE_MARGIN_X - 20, SLIDE_H],
                       fill=tuple(theme['accent'][:3]) + (255,))

        self._draw_badge(draw, theme, part_name)

        # Flow strip: where this scene sits in the five-part lesson.
        if scene.get('show_flow', True) and part_name in visuals.FLOW_PARTS:
            visuals.draw_flow_strip(
                draw, (VISUAL_X0, SAFE_MARGIN_Y, VISUAL_X1, SAFE_MARGIN_Y + 40),
                theme, part_name, self._body_font,
            )

        y = self._draw_title(draw, theme, scene.get('slide_title', 'NCERT Concepts'))
        y += 14
        y = self._draw_definition(draw, theme, str(scene.get('definition', '')).strip(),
                                  str(scene.get('definition_source', '')).strip(), y)
        self._draw_bullets(draw, theme, scene.get('slide_bullets', []), y)

        # -- right-hand visual panel
        visual_box = (VISUAL_X0, VISUAL_Y0, VISUAL_X1, VISUAL_Y1)
        visual_type = str(scene.get('visual_type', 'none')).lower()
        visual_data = scene.get('visual_data') or {}

        # A supplied image always wins: a real NCERT figure beats a drawing.
        rendered_image = visuals.paste_image_panel(
            img, visual_box, theme,
            scene.get('image_path'), scene.get('image_caption'), self._body_font,
        )

        # A drawn concept diagram, selected from the topic. Used when no real
        # figure is available; never captioned as a textbook figure.
        if not rendered_image and scene.get('diagram_topic'):
            rendered_image = self._draw_concept_diagram(img, theme, scene, visual_box)

        if not rendered_image:
            if visual_type == 'formula' and scene.get('formula_latex'):
                self._draw_formula(img, theme, scene['formula_latex'], visual_box)
            elif visual_type == 'process':
                visuals.draw_process_flow(draw, visual_box, theme, visual_data, self._body_font)
            elif visual_type == 'comparison':
                visuals.draw_comparison(draw, visual_box, theme, visual_data, self._body_font)
            elif visual_type == 'diagram':
                visuals.draw_labelled_diagram(draw, visual_box, theme, visual_data, self._body_font)
            elif visual_type == 'alert':
                visuals.draw_alert(draw, visual_box, theme, visual_data, self._body_font)

        os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
        img.save(output_path, "PNG")
        return output_path

    @staticmethod
    def _fit_to_box(image: Image.Image, max_w: int, max_h: int) -> Image.Image:
        """Scale ``image`` up or down to fill the box, keeping aspect ratio."""
        if image.width <= 0 or image.height <= 0:
            return image
        scale = min(max_w / image.width, max_h / image.height)
        new_size = (max(1, int(image.width * scale)), max(1, int(image.height * scale)))
        return image.resize(new_size, Image.LANCZOS)

    @staticmethod
    def _fit_within(image: Image.Image, max_w: int, max_h: int) -> Image.Image:
        """Downscale ``image`` to fit inside ``max_w`` x ``max_h``, keeping aspect."""
        if image.width <= max_w and image.height <= max_h:
            return image
        scale = min(max_w / image.width, max_h / image.height)
        new_size = (max(1, int(image.width * scale)), max(1, int(image.height * scale)))
        return image.resize(new_size, Image.LANCZOS)
