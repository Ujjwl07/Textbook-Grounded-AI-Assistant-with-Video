"""Visual panels drawn on the right-hand side of a slide.

Every panel here reads its content from the scene's ``visual_data``. The earlier
versions drew fixed placeholders — a comparison panel that always said
"Condition A" / "Condition B" with empty bodies, a flowchart that always said
"Step 1, Step 2, Step 3" — so the graphic carried no information about the topic
being taught. A panel with no content is worse than no panel: it occupies the
half of the slide where the explanation should be.

Scene contract:

    "visual_type": "process",
    "visual_data": {"steps": ["Prophase", "Metaphase", "Anaphase"]}

    "visual_type": "comparison",
    "visual_data": {"left":  {"title": "SN1", "points": ["Two steps", "Racemic"]},
                    "right": {"title": "SN2", "points": ["One step", "Inversion"]}}

    "visual_type": "diagram",
    "visual_data": {"title": "Animal cell", "labels": ["Nucleus", "Mitochondrion"]}

    "visual_type": "image",
    "image_path": "...", "image_caption": "Fig 7.2 Kepler's second law"
"""

import os

from PIL import Image, ImageDraw

from app.video.layout import (
    draw_lines,
    fit_text,
    lighten,
    darken,
    readable_on,
    text_size,
    text_width,
    wrap_by_width,
)


def _panel_center(box):
    x0, y0, x1, y1 = box
    return ((x0 + x1) // 2, (y0 + y1) // 2)


def draw_caption(draw, box, theme, text, font):
    """Centred caption along the bottom edge of the panel."""
    if not text:
        return
    x0, y0, x1, y1 = box
    lines = wrap_by_width(text, font, x1 - x0)[:2]
    y = y1 - len(lines) * (font.size + 6)
    for line in lines:
        width = text_width(line, font)
        draw.text(((x0 + x1 - width) // 2, y), line, font=font, fill=theme["subtext"])
        y += font.size + 6


# ---------------------------------------------------------------------------
# Process flow
# ---------------------------------------------------------------------------


def draw_process_flow(draw, box, theme, data, font_for_size):
    """Vertical chain of named steps joined by arrows.

    Steps are stacked vertically rather than laid out horizontally: real process
    names ("Photophosphorylation") do not fit in a 110 px wide horizontal box,
    which is why the old flowchart could only ever say "Step 1".
    """
    steps = [str(s) for s in (data or {}).get("steps", []) if str(s).strip()]
    if not steps:
        return

    x0, y0, x1, y1 = box
    steps = steps[:5]
    gap = 18
    box_h = min(74, max(46, (y1 - y0 - gap * (len(steps) - 1)) // len(steps)))
    total_h = len(steps) * box_h + (len(steps) - 1) * gap
    y = y0 + ((y1 - y0) - total_h) // 2

    width = x1 - x0
    label_font = font_for_size(20)

    for index, step in enumerate(steps):
        fill = lighten(theme["bg"], 0.16)
        draw.rounded_rectangle([x0, y, x1, y + box_h], radius=10,
                               fill=fill, outline=theme["accent"], width=2)

        # Step number chip
        chip_r = 13
        cx, cy = x0 + 22, y + box_h // 2
        draw.ellipse([cx - chip_r, cy - chip_r, cx + chip_r, cy + chip_r], fill=theme["accent"])
        num = str(index + 1)
        nw, nh = text_size(num, font_for_size(16))
        draw.text((cx - nw // 2, cy - nh // 2 - 2), num,
                  font=font_for_size(16), fill=readable_on(theme["accent"]))

        text_x = x0 + 44
        font, lines, line_height = fit_text(
            step, font_for_size, width - 58, box_h - 10, sizes=[20, 18, 16, 14]
        )
        text_y = y + (box_h - len(lines) * line_height) // 2
        draw_lines(draw, (text_x, text_y), lines, font, theme["text"], line_height)

        if index < len(steps) - 1:
            ax = (x0 + x1) // 2
            ay = y + box_h
            draw.line([(ax, ay + 2), (ax, ay + gap - 4)], fill=theme["accent"], width=3)
            draw.polygon(
                [(ax, ay + gap), (ax - 6, ay + gap - 7), (ax + 6, ay + gap - 7)],
                fill=theme["accent"],
            )
        y += box_h + gap


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------


def draw_comparison(draw, box, theme, data, font_for_size):
    """Two labelled columns with real bullet points inside each."""
    data = data or {}
    left = data.get("left") or {}
    right = data.get("right") or {}
    if not left.get("title") and not right.get("title"):
        return

    x0, y0, x1, y1 = box
    gap = 16
    col_w = (x1 - x0 - gap) // 2

    title_font = font_for_size(21)
    point_font = font_for_size(15)

    # Size the columns to their content instead of stretching to the panel:
    # three short points in a 370 px tall box left two-thirds of it empty.
    def column_height(column) -> int:
        points = [str(p) for p in (column.get("points") or []) if str(p).strip()][:4]
        height = 58
        for point in points:
            lines = wrap_by_width(point, point_font, col_w - 34)[:3]
            height += len(lines) * (point_font.size + 5) + 8
        return height + 14

    box_h = max(column_height(left), column_height(right), 120)
    box_h = min(box_h, y1 - y0)
    top = y0 + ((y1 - y0) - box_h) // 2
    y1 = top + box_h
    y0 = top

    columns = [
        (left, x0, theme["accent"]),
        (right, x0 + col_w + gap, (255, 255, 255)),
    ]

    for column, cx, colour in columns:
        title = str(column.get("title", "")).strip()
        points = [str(p) for p in column.get("points", []) if str(p).strip()][:4]
        if not title and not points:
            continue

        draw.rounded_rectangle([cx, y0, cx + col_w, y1], radius=12,
                               fill=lighten(theme["bg"], 0.13), outline=colour, width=3)

        # Header band
        draw.rounded_rectangle([cx, y0, cx + col_w, y0 + 42], radius=12, fill=colour)
        draw.rectangle([cx, y0 + 30, cx + col_w, y0 + 42], fill=colour)
        tw = text_width(title, title_font)
        draw.text((cx + (col_w - tw) // 2, y0 + 10), title,
                  font=title_font, fill=readable_on(colour))

        y = y0 + 58
        for point in points:
            lines = wrap_by_width(point, point_font, col_w - 34)[:3]
            draw.ellipse([cx + 14, y + 7, cx + 20, y + 13], fill=colour)
            for line in lines:
                draw.text((cx + 28, y), line, font=point_font, fill=theme["text"])
                y += point_font.size + 5
            y += 8
            if y > y1 - 20:
                break


# ---------------------------------------------------------------------------
# Labelled diagram
# ---------------------------------------------------------------------------


def draw_labelled_diagram(draw, box, theme, data, font_for_size):
    """Concentric structure with leader lines to the supplied labels."""
    data = data or {}
    labels = [str(l) for l in data.get("labels", []) if str(l).strip()][:4]
    title = str(data.get("title", "")).strip()

    x0, y0, x1, y1 = box
    cx, cy = _panel_center((x0, y0, x1 - 120, y1 - 30))
    radius = min((x1 - x0) // 4, (y1 - y0) // 3)

    draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius],
                 fill=lighten(theme["bg"], 0.10), outline=theme["accent"], width=4)
    inner = max(16, radius // 3)
    draw.ellipse([cx - inner, cy - inner, cx + inner, cy + inner],
                 fill=theme["accent"], outline=(255, 255, 255), width=2)

    label_font = font_for_size(15)
    # Anchor points around the structure, paired with a side to write on.
    anchors = [
        (cx, cy, "right"),                       # centre -> inner body
        (cx + int(radius * 0.72), cy - int(radius * 0.55), "right"),
        (cx - int(radius * 0.70), cy + int(radius * 0.60), "left"),
        (cx + int(radius * 0.30), cy + int(radius * 0.85), "right"),
    ]

    for label, (ax, ay, side) in zip(labels, anchors):
        draw.ellipse([ax - 4, ay - 4, ax + 4, ay + 4], fill=(255, 255, 255))
        if side == "right":
            lx = x1 - 108
            draw.line([(ax, ay), (lx - 6, ay)], fill=(255, 255, 255), width=1)
            text_x = lx
        else:
            lx = x0 + 4
            draw.line([(lx + 60, ay), (ax, ay)], fill=(255, 255, 255), width=1)
            text_x = lx

        lines = wrap_by_width(label, label_font, 104)[:2]
        ty = ay - (len(lines) * (label_font.size + 3)) // 2
        for line in lines:
            draw.text((text_x, ty), line, font=label_font, fill=theme["text"])
            ty += label_font.size + 3

    if title:
        draw_caption(draw, box, theme, title, font_for_size(16))


# ---------------------------------------------------------------------------
# Alert
# ---------------------------------------------------------------------------


def draw_alert(draw, box, theme, data, font_for_size):
    """Hazard triangle with the trap named underneath, when one is supplied."""
    data = data or {}
    caption = str(data.get("caption", "CRITICAL NEET TRAP")).strip()

    x0, y0, x1, y1 = box
    cx, cy = _panel_center(box)
    cy -= 20
    size = min((x1 - x0) // 3, (y1 - y0) // 3)

    draw.polygon([(cx, cy - size), (cx - size, cy + size * 0.8), (cx + size, cy + size * 0.8)],
                 outline=theme["accent"], width=6)
    bar_h = size * 0.75
    draw.rounded_rectangle([cx - 6, cy - bar_h * 0.55, cx + 6, cy + bar_h * 0.28],
                           radius=4, fill=theme["accent"])
    draw.ellipse([cx - 7, cy + bar_h * 0.44, cx + 7, cy + bar_h * 0.44 + 14], fill=theme["accent"])

    draw_caption(draw, box, theme, caption, font_for_size(17))


# ---------------------------------------------------------------------------
# Photo panel
# ---------------------------------------------------------------------------


def paste_image_panel(base, box, theme, image_path, caption, font_for_size):
    """Paste a photo/figure into the panel, scaled to fit, with a caption.

    This is the slot real NCERT figures land in once they are extracted from the
    textbook PDFs; nothing else about the slide needs to change.
    """
    if not image_path or not os.path.exists(image_path):
        return False

    try:
        photo = Image.open(image_path).convert("RGBA")
    except Exception:
        return False

    x0, y0, x1, y1 = box
    caption_font = font_for_size(16)
    caption_h = 46 if caption else 0
    avail_w, avail_h = x1 - x0, (y1 - y0) - caption_h

    scale = min(avail_w / photo.width, avail_h / photo.height)
    if scale < 1:
        photo = photo.resize((max(1, int(photo.width * scale)),
                              max(1, int(photo.height * scale))), Image.LANCZOS)

    px = x0 + (avail_w - photo.width) // 2
    py = y0 + (avail_h - photo.height) // 2

    # White card behind the figure: NCERT figures have white backgrounds and
    # would otherwise float on the themed colour with a hard edge.
    pad = 10
    card = [px - pad, py - pad, px + photo.width + pad, py + photo.height + pad]
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    ImageDraw.Draw(overlay).rounded_rectangle(card, radius=10, fill=(255, 255, 255, 245))
    base.alpha_composite(overlay)
    base.paste(photo, (px, py), photo)

    if caption:
        draw = ImageDraw.Draw(base)
        draw_caption(draw, (x0, y1 - caption_h, x1, y1), theme, caption, caption_font)
    return True


# ---------------------------------------------------------------------------
# Flow strip
# ---------------------------------------------------------------------------

FLOW_PARTS = ["HOOK", "CONCEPT", "EXAMPLE", "MEMORY", "NEET_ALERT"]
FLOW_LABELS = {"HOOK": "Hook", "CONCEPT": "Concept", "EXAMPLE": "Example",
               "MEMORY": "Memory", "NEET_ALERT": "Alert"}


def draw_flow_strip(draw, box, theme, current_part, font_for_size):
    """Five-step progress strip showing where the viewer is in the lesson.

    This is the 'flow' the video was missing: without it each scene reads as a
    standalone card, with no sense of a five-part structure being worked through.
    """
    x0, y0, x1, y1 = box
    parts = FLOW_PARTS
    current = (current_part or "").upper()
    try:
        current_index = parts.index(current)
    except ValueError:
        current_index = -1

    font = font_for_size(13)
    gap = 8
    dot_r = 5
    # Width is divided evenly; each cell holds a dot and its label.
    cell_w = (x1 - x0 - gap * (len(parts) - 1)) // len(parts)
    y_dot = y0 + dot_r + 2

    for index, part in enumerate(parts):
        cx = x0 + index * (cell_w + gap) + cell_w // 2
        done = index <= current_index if current_index >= 0 else False
        active = index == current_index

        if index < len(parts) - 1:
            nx = x0 + (index + 1) * (cell_w + gap) + cell_w // 2
            line_colour = theme["accent"] if index < current_index else darken(theme["bg"], 0.25)
            draw.line([(cx + dot_r + 3, y_dot), (nx - dot_r - 3, y_dot)],
                      fill=line_colour, width=2)

        if active:
            draw.ellipse([cx - dot_r - 4, y_dot - dot_r - 4, cx + dot_r + 4, y_dot + dot_r + 4],
                         outline=theme["accent"], width=2)
        fill = theme["accent"] if done else darken(theme["bg"], 0.3)
        draw.ellipse([cx - dot_r, y_dot - dot_r, cx + dot_r, y_dot + dot_r], fill=fill)

        label = FLOW_LABELS.get(part, part.title())
        lw = text_width(label, font)
        colour = theme["text"] if active else theme["subtext"]
        draw.text((cx - lw // 2, y_dot + dot_r + 6), label, font=font, fill=colour)
