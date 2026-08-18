"""Karaoke-style word-level subtitles (Purnika, Section 11.4 #4).

Word timings come from Edge-TTS WordBoundary events (see app.tts.tts_generator),
so the highlight tracks the actual speech rather than an estimate.

Two rendering paths exist:

``generate_subtitles_clip``
    Returns a transparent overlay clip for use inside a MoviePy
    ``CompositeVideoClip``. Kept for compatibility and for callers that need a
    standalone overlay.

``burn_onto`` (preferred)
    Composites the subtitle band onto a base clip directly. Profiling showed
    MoviePy's generic ``blit()`` — which copies the whole frame and does the
    alpha blend in float64 via ``np.dstack`` — cost ~37 ms per frame and
    accounted for the overwhelming majority of render time. This path does the
    blend itself in float32 with a broadcast alpha channel, touching only the
    subtitle band, and center-crops the zoomed base frame in the same pass.
"""

from bisect import bisect_right

import numpy as np
from PIL import Image, ImageDraw
from moviepy.editor import VideoClip

from app.video.fonts import load_font, resolve_font_path

WHITE = (255, 255, 255)
DEFAULT_HIGHLIGHT = (255, 235, 59)


class SubtitleLayout:
    """Pre-computed, time-invariant subtitle geometry and pixel data.

    Everything here is built once per scene: the line wrapping, the alpha mask
    and one rendered band image per highlighted word. At render time only an
    array lookup and one blend remain.
    """

    def __init__(self, engine, word_boundaries, size, highlight_color):
        self.width, self.height = size
        self.word_boundaries = word_boundaries
        self.starts = [w["start"] for w in word_boundaries]

        font = engine.font
        try:
            self.space_width = font.getbbox(" ")[2] - font.getbbox(" ")[0]
        except Exception:
            self.space_width = 8

        # Group words into lines that fit within max_width.
        self.lines = []
        current_line, current_width = [], 0
        for idx, info in enumerate(word_boundaries):
            try:
                word_width = font.getbbox(info["word"])[2] - font.getbbox(info["word"])[0]
            except Exception:
                word_width = len(info["word"]) * 12

            if current_width + word_width > engine.max_width and current_line:
                self.lines.append(current_line)
                current_line, current_width = [], 0

            current_line.append((idx, info, word_width))
            current_width += word_width + self.space_width
        if current_line:
            self.lines.append(current_line)

        self.line_height = engine.font_size + 8
        self.band_h = max(
            engine.band_height,
            len(self.lines) * self.line_height + 2 * engine.band_padding,
        )
        self.band_y = max(0, self.height - self.band_h - engine.band_margin_bottom)
        self.start_y = (self.band_h - len(self.lines) * self.line_height) // 2

        self.font = font
        self.max_width = engine.max_width
        self.highlight_color = highlight_color

        # Alpha mask, shaped (band_h, width, 1) so it broadcasts over RGB
        # without the per-frame np.dstack that MoviePy performs.
        mask_img = Image.new("L", (self.width, self.band_h), 0)
        mask_draw = ImageDraw.Draw(mask_img)
        mask_draw.rectangle(
            [self.width // 2 - self.max_width // 2 - 20, 0,
             self.width // 2 + self.max_width // 2 + 20, self.band_h],
            fill=160,  # ~63% opaque backing bar
        )
        self._draw_words(mask_draw, lambda i: 255)
        self.alpha = (np.array(mask_img, dtype=np.float32) / 255.0)[:, :, None]
        self.inv_alpha = 1.0 - self.alpha

        # One band image per highlighted word index (-1 = nothing highlighted).
        # Stored pre-multiplied by alpha so the per-frame blend is one multiply
        # and one add.
        self._band_cache = {}

    def _draw_words(self, draw, colour_for) -> None:
        y = self.start_y
        for line in self.lines:
            line_w = sum(w[2] for w in line) + (len(line) - 1) * self.space_width
            x = self.width // 2 - line_w // 2
            for idx, info, word_width in line:
                draw.text((x, y), info["word"], font=self.font, fill=colour_for(idx))
                x += word_width + self.space_width
            y += self.line_height

    def active_index(self, t: float) -> int:
        """Index of the word being spoken at ``t``, or -1 between words."""
        pos = bisect_right(self.starts, t) - 1
        if pos < 0:
            return -1
        return pos if t <= self.word_boundaries[pos]["end"] else -1

    def band_rgb(self, index: int) -> np.ndarray:
        """Rendered band (uint8 RGB) with word ``index`` highlighted."""
        cached = self._band_cache.get(index)
        if cached is None:
            img = Image.new("RGB", (self.width, self.band_h), (0, 0, 0))
            self._draw_words(
                ImageDraw.Draw(img),
                lambda i, active=index: self.highlight_color if i == active else WHITE,
            )
            cached = np.array(img)
            self._band_cache[index] = cached
        return cached

    def band_premultiplied(self, index: int) -> np.ndarray:
        """Band pre-multiplied by alpha, cached as float32."""
        key = ("pm", index)
        cached = self._band_cache.get(key)
        if cached is None:
            cached = self.band_rgb(index).astype(np.float32) * self.alpha
            self._band_cache[key] = cached
        return cached


class SubtitleEngine:
    # Bottom-band geometry. Keeping the overlay to a band instead of a
    # full-frame layer is the single biggest render-speed lever in the pipeline.
    DEFAULT_BAND_HEIGHT = 100
    BAND_MARGIN_BOTTOM = 20
    BAND_PADDING = 12

    def __init__(self, font_size: int = 28, max_width: int = 900, band_height: int = None):
        self.font_size = font_size
        self.max_width = max_width
        self.band_height = band_height or self.DEFAULT_BAND_HEIGHT
        self.band_margin_bottom = self.BAND_MARGIN_BOTTOM
        self.band_padding = self.BAND_PADDING
        self.font_path = resolve_font_path(bold=True)
        self.font = load_font(self.font_size, bold=True)

    def build_layout(self, word_boundaries, size=(1280, 720), highlight_color=DEFAULT_HIGHLIGHT):
        return SubtitleLayout(self, word_boundaries, size, highlight_color)

    # -- Path 1: overlay clip for MoviePy compositing -----------------------

    def generate_subtitles_clip(self, word_boundaries: list, duration: float,
                                size: tuple = (1280, 720),
                                highlight_color: tuple = DEFAULT_HIGHLIGHT) -> VideoClip:
        """Transparent karaoke overlay, positioned as a band at the bottom."""
        layout = self.build_layout(word_boundaries, size, highlight_color)
        mask_2d = layout.alpha[:, :, 0]

        def make_frame(t):
            return layout.band_rgb(layout.active_index(t))

        def make_mask_frame(t):
            return mask_2d

        clip = VideoClip(make_frame, duration=duration)
        mask = VideoClip(make_mask_frame, ismask=True, duration=duration)
        return clip.set_mask(mask).set_position((0, layout.band_y))

    # -- Path 2: direct compositing (fast) ---------------------------------

    def burn_onto(self, base_clip, word_boundaries: list, duration: float,
                  size: tuple = (1280, 720),
                  highlight_color: tuple = DEFAULT_HIGHLIGHT) -> VideoClip:
        """Composite subtitles onto ``base_clip`` without MoviePy's generic blit.

        Also center-crops the base frame to ``size``. Ken Burns produces frames
        larger than the canvas, and MoviePy would otherwise anchor them at the
        top-left, so the zoom appeared to drift into a corner instead of pushing
        into the centre.
        """
        if not word_boundaries:
            return base_clip

        layout = self.build_layout(word_boundaries, size, highlight_color)
        width, height = size
        y0, y1 = layout.band_y, layout.band_y + layout.band_h

        def make_frame(t):
            frame = base_clip.get_frame(t)
            frame = _fit_center(frame, width, height)

            premultiplied = layout.band_premultiplied(layout.active_index(t))
            region = frame[y0:y1, 0:width].astype(np.float32)
            blended = premultiplied + region * layout.inv_alpha

            out = frame.copy()
            out[y0:y1, 0:width] = blended.astype(np.uint8)
            return out

        return VideoClip(make_frame, duration=duration)


def _fit_center(frame: np.ndarray, width: int, height: int) -> np.ndarray:
    """Centre-crop (or pad) ``frame`` to exactly ``height`` x ``width``."""
    frame_h, frame_w = frame.shape[:2]
    if (frame_h, frame_w) == (height, width):
        return frame

    if frame_h >= height and frame_w >= width:
        top = (frame_h - height) // 2
        left = (frame_w - width) // 2
        return frame[top:top + height, left:left + width]

    # Smaller than the canvas in at least one axis: pad onto a black canvas.
    canvas = np.zeros((height, width, frame.shape[2]), dtype=frame.dtype)
    copy_h, copy_w = min(frame_h, height), min(frame_w, width)
    top = (height - copy_h) // 2
    left = (width - copy_w) // 2
    canvas[top:top + copy_h, left:left + copy_w] = frame[:copy_h, :copy_w]
    return canvas
