"""Pixel-accurate text layout helpers for the slide renderer.

The renderer previously wrapped text with ``textwrap.TextWrapper(width=45)``,
which counts characters. Character counts do not correspond to rendered width in
a proportional font — "Illinois" and "Wowmawm" are both 8 characters but differ
by roughly 2x in pixels — so lines either overflowed the column or wasted half
of it. Everything here measures the actual glyphs instead.
"""

from PIL import ImageDraw

# A scratch canvas for measuring text outside of any particular drawing context.
_MEASURE = ImageDraw.Draw
_measure_draw = None


def _get_measurer():
    global _measure_draw
    if _measure_draw is None:
        from PIL import Image

        _measure_draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    return _measure_draw


def text_size(text: str, font) -> tuple:
    """Return the (width, height) of ``text`` rendered in ``font``."""
    if not text:
        return (0, 0)
    draw = _get_measurer()
    try:
        box = draw.textbbox((0, 0), text, font=font)
        return (box[2] - box[0], box[3] - box[1])
    except Exception:
        return (len(text) * 10, 20)


def text_width(text: str, font) -> int:
    return text_size(text, font)[0]


def wrap_by_width(text: str, font, max_width: int) -> list:
    """Wrap ``text`` so every line fits within ``max_width`` pixels."""
    if not text:
        return []

    lines, current = [], ""
    for word in str(text).split():
        candidate = f"{current} {word}".strip()
        if text_width(candidate, font) <= max_width or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def fit_text(text: str, font_for_size, max_width: int, max_height: int,
             sizes, line_spacing: float = 1.25) -> tuple:
    """Pick the largest size from ``sizes`` whose wrapped text fits the box.

    ``font_for_size`` is a callable size -> font. Returns ``(font, lines,
    line_height)``. The smallest size is used as the fallback, truncating with
    an ellipsis if even that overflows, so a long string degrades gracefully
    instead of running off the slide.
    """
    for size in sorted(sizes, reverse=True):
        font = font_for_size(size)
        line_height = int(size * line_spacing)
        lines = wrap_by_width(text, font, max_width)
        if len(lines) * line_height <= max_height:
            return font, lines, line_height

    size = min(sizes)
    font = font_for_size(size)
    line_height = int(size * line_spacing)
    lines = wrap_by_width(text, font, max_width)
    max_lines = max(1, max_height // line_height)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip() + "…"
    return font, lines, line_height


def draw_lines(draw, xy: tuple, lines, font, fill, line_height: int) -> int:
    """Draw ``lines`` top-down from ``xy``; returns the y below the last line."""
    x, y = xy
    for line in lines:
        draw.text((x, y), line, font=font, fill=fill)
        y += line_height
    return y


def blend(color, other, amount: float) -> tuple:
    """Mix ``color`` toward ``other`` by ``amount`` (0..1)."""
    amount = max(0.0, min(1.0, amount))
    return tuple(int(c + (o - c) * amount) for c, o in zip(color[:3], other[:3]))


def lighten(color, amount: float = 0.12) -> tuple:
    return blend(color, (255, 255, 255), amount)


def darken(color, amount: float = 0.12) -> tuple:
    return blend(color, (0, 0, 0), amount)


def readable_on(background) -> tuple:
    """Black or white, whichever has more contrast against ``background``.

    Uses the ITU-R BT.601 luma approximation; the 140 threshold is the usual
    cut-off for switching label colour on a coloured chip.
    """
    r, g, b = background[:3]
    luma = 0.299 * r + 0.587 * g + 0.114 * b
    return (0, 0, 0) if luma > 140 else (255, 255, 255)
