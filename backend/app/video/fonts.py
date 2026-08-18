"""Cross-platform font resolution for the slide and subtitle renderers.

The renderers originally hardcoded ``C:/Windows/Fonts/arial.ttf``, which silently
degraded to PIL's tiny bitmap default font on Linux/macOS deployment targets.
This module resolves a usable TrueType face on any platform and caches the result.
"""

import os
from functools import lru_cache
from PIL import ImageFont

# Candidate faces in preference order, per weight. First existing path wins.
_REGULAR_CANDIDATES = [
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/segoeui.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
    "/Library/Fonts/Arial.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
]

_BOLD_CANDIDATES = [
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/segoeuib.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
]


@lru_cache(maxsize=2)
def resolve_font_path(bold: bool = False) -> str:
    """Return the path of the first installed TrueType face, or '' if none found."""
    candidates = _BOLD_CANDIDATES if bold else _REGULAR_CANDIDATES
    for path in candidates:
        if os.path.exists(path):
            return path

    # Last resort: let PIL/fontconfig resolve a bare family name.
    for name in (("arialbd.ttf", "DejaVuSans-Bold.ttf") if bold else ("arial.ttf", "DejaVuSans.ttf")):
        try:
            ImageFont.truetype(name, 12)
            return name
        except Exception:
            continue
    return ""


@lru_cache(maxsize=64)
def load_font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    """Load a TrueType font at ``size``, falling back to PIL's default face."""
    path = resolve_font_path(bold=bold)
    if path:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            pass
    # Non-bold retry before giving up entirely.
    if bold:
        return load_font(size, bold=False)
    return ImageFont.load_default()


def font_is_scalable() -> bool:
    """True when a real TrueType face was found (i.e. font sizes are honoured)."""
    return bool(resolve_font_path())
