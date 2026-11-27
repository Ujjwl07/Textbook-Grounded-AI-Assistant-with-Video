"""Cross-platform font resolution for the slide and subtitle renderers.

Two problems are solved here.

1. Portability. The renderers originally hardcoded ``C:/Windows/Fonts/arial.ttf``,
   which silently degraded to PIL's bitmap default font on Linux/macOS — slides
   still rendered, but the requested point sizes were ignored and no error was
   raised.

2. Glyph coverage. Science slides contain subscripts, superscripts and Greek
   ("m₁", "N m² kg⁻²", "Δ", "→"). Arial has no U+2081/U+2082/U+207B, so those
   characters render as .notdef boxes — the slides literally showed "m□ and m□".
   Faces are therefore checked against a required glyph set before being chosen,
   and DejaVuSans (shipped inside matplotlib, already a project dependency) is a
   guaranteed-complete fallback on every platform.
"""

import os
from functools import lru_cache

from PIL import ImageFont

# Characters a NEET slide is expected to contain. A face must cover all of them
# to be preferred; otherwise the next candidate is tried.
REQUIRED_GLYPHS = "₀₁₂₃₄⁻⁰¹²³×÷→←↔≈≤≥±°ΔΩθλμπσ½"


def _matplotlib_font(name: str) -> str:
    """Path to a font bundled inside matplotlib, or '' when unavailable."""
    try:
        import matplotlib

        path = os.path.join(matplotlib.get_data_path(), "fonts", "ttf", name)
        return path if os.path.exists(path) else ""
    except Exception:
        return ""


# Candidate faces in preference order, per weight. The matplotlib DejaVu build is
# listed last as the always-present fallback, but wins whenever the system faces
# lack the scientific glyphs above.
_REGULAR_CANDIDATES = [
    "C:/Windows/Fonts/segoeui.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
    "/Library/Fonts/Arial.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
]

_BOLD_CANDIDATES = [
    "C:/Windows/Fonts/segoeuib.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
]


@lru_cache(maxsize=32)
def _covered_glyphs(path: str) -> frozenset:
    """Code points a font file can render, read from its cmap tables."""
    try:
        from fontTools.ttLib import TTFont

        codepoints = set()
        with TTFont(path, fontNumber=0, lazy=True) as font:
            for table in font["cmap"].tables:
                codepoints |= set(table.cmap.keys())
        return frozenset(codepoints)
    except Exception:
        # fontTools is a matplotlib dependency, but never fail hard over fonts.
        return frozenset()


def _covers_required(path: str) -> bool:
    covered = _covered_glyphs(path)
    if not covered:
        return False
    return all(ord(ch) in covered for ch in REQUIRED_GLYPHS)


@lru_cache(maxsize=2)
def resolve_font_path(bold: bool = False) -> str:
    """Path of the best available TrueType face, or '' if none is found.

    Preference order: an installed face that covers REQUIRED_GLYPHS, then
    matplotlib's DejaVu build, then any installed face at all.
    """
    candidates = _BOLD_CANDIDATES if bold else _REGULAR_CANDIDATES
    fallback = _matplotlib_font("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf")

    existing = [path for path in candidates if os.path.exists(path)]

    for path in existing:
        if _covers_required(path):
            return path

    if fallback and _covers_required(fallback):
        return fallback

    if existing:
        return existing[0]
    if fallback:
        return fallback

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
    if bold:
        return load_font(size, bold=False)
    return ImageFont.load_default()


def font_is_scalable() -> bool:
    """True when a real TrueType face was found (i.e. font sizes are honoured)."""
    return bool(resolve_font_path())


# Caption faces for Indian-language lessons. A face is used only when it has
# the script's letters; PIL shapes the conjuncts and vowel signs through raqm.
_SCRIPT_FONTS = {
    "hi-IN": ("\u0915\u093e\u0930\u094d", [  # क ा र ्
        "/System/Library/Fonts/Supplemental/Devanagari Sangam MN.ttc",
        "/System/Library/Fonts/Kohinoor.ttc",
        "/System/Library/Fonts/Supplemental/DevanagariMT.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansDevanagari-Bold.ttf",
        "/usr/share/fonts/truetype/noto/NotoSansDevanagari-Regular.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansDevanagari-Bold.ttf",
        "/usr/share/fonts/truetype/lohit-devanagari/Lohit-Devanagari.ttf",
        "C:/Windows/Fonts/NirmalaB.ttf",
        "C:/Windows/Fonts/Nirmala.ttf",
        "C:/Windows/Fonts/mangalb.ttf",
    ]),
    "pa-IN": ("\u0a15\u0a3e\u0a30", [  # ਕ ਾ ਰ
        "/System/Library/Fonts/Supplemental/Gurmukhi Sangam MN.ttc",
        "/System/Library/Fonts/Supplemental/Gurmukhi MN.ttc",
        "/System/Library/Fonts/Supplemental/Gurmukhi.ttf",
        "/usr/share/fonts/truetype/noto/NotoSansGurmukhi-Bold.ttf",
        "/usr/share/fonts/truetype/noto/NotoSansGurmukhi-Regular.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansGurmukhi-Bold.ttf",
        "/usr/share/fonts/truetype/lohit-punjabi/Lohit-Gurmukhi.ttf",
        "C:/Windows/Fonts/NirmalaB.ttf",
        "C:/Windows/Fonts/Nirmala.ttf",
        "C:/Windows/Fonts/raavib.ttf",
    ]),
}


@lru_cache(maxsize=8)
def resolve_script_font_path(language: str) -> str:
    """A face with the letters of ``language`` (hi-IN, pa-IN), or ''."""
    entry = _SCRIPT_FONTS.get(language or "")
    if not entry:
        return ""
    sample, candidates = entry
    for path in candidates:
        if os.path.exists(path):
            covered = _covered_glyphs(path)
            if not covered or all(ord(ch) in covered for ch in sample):
                return path
    return ""


@lru_cache(maxsize=32)
def load_caption_font(size: int, language: str = "en-IN") -> ImageFont.ImageFont:
    """Bold caption font for ``language``; the English face for English or when
    no face for the script is installed."""
    path = resolve_script_font_path(language)
    if path:
        try:
            # .ttc collections: index 1 is the bold face in the macOS Sangam fonts.
            if path.endswith(".ttc"):
                try:
                    return ImageFont.truetype(path, size, index=1)
                except Exception:
                    pass
            return ImageFont.truetype(path, size)
        except Exception:
            pass
    return load_font(size, bold=True)
