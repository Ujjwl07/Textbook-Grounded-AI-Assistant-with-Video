"""Programmatically drawn concept diagrams for NEET topics.

These are the project's own illustrations, drawn with matplotlib to match the
scene theme. They are deliberately **not** presented as textbook figures: no
"Fig. 7.2" label, no NCERT caption. When real extracted figures are available
(see app.rag.figures) those take priority and these are the fallback.

Each drawing function receives a matplotlib axis and a palette, and renders one
scientifically meaningful diagram — force pairs with labelled separation, a
reaction energy profile with activation energy marked, a labelled cell, and so
on. ``diagram_for_topic`` picks one from the topic and chapter name.

Adding a diagram: write a ``draw_*`` function, then add its keywords to
DIAGRAM_KEYWORDS.
"""

import io
import logging
import re

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Arc, Circle, Ellipse, FancyArrowPatch, Polygon  # noqa: E402
from PIL import Image  # noqa: E402

logger = logging.getLogger(__name__)


def _hex(rgb) -> str:
    return "#{:02x}{:02x}{:02x}".format(*[int(c) for c in rgb[:3]])


class Palette:
    """Theme colours as matplotlib-friendly hex strings."""

    def __init__(self, theme: dict):
        self.accent = _hex(theme.get("accent", (255, 255, 255)))
        self.text = _hex(theme.get("text", (255, 255, 255)))
        self.subtext = _hex(theme.get("subtext", (220, 220, 220)))
        self.line = self.text


# ---------------------------------------------------------------------------
# Physics
# ---------------------------------------------------------------------------


def draw_force_pair(ax, p: Palette, labels=None):
    """Two masses attracting each other, with the separation marked.

    Covers gravitation, Coulomb's law and Newton's third law.
    """
    left, right = labels[:2] if labels and len(labels) >= 2 else ("m₁", "m₂")
    ax.add_patch(Circle((1.2, 2.0), 0.42, color=p.accent, zorder=3))
    ax.add_patch(Circle((5.0, 2.0), 0.62, color=p.text, alpha=0.9, zorder=3))
    ax.text(1.2, 2.0, left, ha="center", va="center", fontsize=13,
            color="black", zorder=4, fontweight="bold")
    ax.text(5.0, 2.0, right, ha="center", va="center", fontsize=13,
            color="black", zorder=4, fontweight="bold")

    # Attractive forces: arrows point toward each other.
    ax.add_patch(FancyArrowPatch((1.85, 2.0), (2.9, 2.0), arrowstyle="-|>",
                                 mutation_scale=18, color=p.accent, lw=2.4))
    ax.add_patch(FancyArrowPatch((4.3, 2.0), (3.3, 2.0), arrowstyle="-|>",
                                 mutation_scale=18, color=p.accent, lw=2.4))
    ax.text(2.35, 2.28, "F", color=p.text, fontsize=12, ha="center", style="italic")
    ax.text(3.85, 2.28, "F", color=p.text, fontsize=12, ha="center", style="italic")

    # Separation
    ax.annotate("", xy=(1.2, 1.05), xytext=(5.0, 1.05),
                arrowprops=dict(arrowstyle="<->", color=p.subtext, lw=1.4))
    ax.text(3.1, 0.72, "r", color=p.subtext, fontsize=13, ha="center", style="italic")
    ax.plot([1.2, 1.2], [1.0, 1.6], color=p.subtext, lw=1, ls=":")
    ax.plot([5.0, 5.0], [1.0, 1.4], color=p.subtext, lw=1, ls=":")

    ax.set_xlim(0, 6.2)
    ax.set_ylim(0.3, 3.4)


def draw_orbit(ax, p: Palette, labels=None):
    """Elliptical orbit with the Sun at a focus and a swept area."""
    ax.add_patch(Ellipse((3.1, 2.0), 4.6, 3.0, fill=False,
                         edgecolor=p.text, lw=2.2))
    sun = (1.85, 2.0)
    ax.add_patch(Circle(sun, 0.3, color=p.accent, zorder=3))
    ax.text(sun[0], sun[1] - 0.62, "Sun", color=p.subtext, fontsize=10, ha="center")

    planet = (5.15, 2.55)
    ax.add_patch(Circle(planet, 0.17, color=p.text, zorder=3))
    ax.text(planet[0] + 0.1, planet[1] + 0.32, "P", color=p.text, fontsize=11)

    # Swept sector, the visual point of the law of areas.
    wedge = Polygon([sun, (5.30, 2.05), (5.15, 2.55)], closed=True,
                    facecolor=p.accent, alpha=0.35, edgecolor=p.accent, lw=1.2)
    ax.add_patch(wedge)
    ax.text(4.2, 1.62, "equal areas\nin equal times", color=p.subtext,
            fontsize=9, ha="center")

    ax.set_xlim(0.2, 6.2)
    ax.set_ylim(0.1, 3.9)


def draw_wave(ax, p: Palette, labels=None):
    """Sine wave with wavelength and amplitude marked."""
    import numpy as np

    x = np.linspace(0, 6, 400)
    y = 2.0 + 0.85 * np.sin(2 * np.pi * x / 3.0)
    ax.plot(x, y, color=p.accent, lw=2.6)
    ax.axhline(2.0, color=p.subtext, lw=1, ls=":")

    ax.annotate("", xy=(0.75, 3.05), xytext=(3.75, 3.05),
                arrowprops=dict(arrowstyle="<->", color=p.text, lw=1.4))
    ax.text(2.25, 3.18, "λ", color=p.text, fontsize=14, ha="center")

    ax.annotate("", xy=(0.75, 2.0), xytext=(0.75, 2.85),
                arrowprops=dict(arrowstyle="<->", color=p.text, lw=1.4))
    ax.text(0.95, 2.4, "A", color=p.text, fontsize=12, va="center")

    ax.set_xlim(-0.1, 6.1)
    ax.set_ylim(0.6, 3.5)


def draw_ray_lens(ax, p: Palette, labels=None):
    """Convex lens converging parallel rays to a focus."""
    ax.add_patch(Ellipse((3.0, 2.0), 0.7, 2.6, fill=False, edgecolor=p.text, lw=2.4))
    ax.axhline(2.0, color=p.subtext, lw=1, ls=":")

    for offset in (0.75, 0.0, -0.75):
        ax.add_patch(FancyArrowPatch((0.4, 2.0 + offset), (2.85, 2.0 + offset),
                                     arrowstyle="-|>", mutation_scale=13,
                                     color=p.accent, lw=1.8))
        ax.plot([3.15, 5.1], [2.0 + offset, 2.0], color=p.accent, lw=1.8)

    ax.add_patch(Circle((5.1, 2.0), 0.09, color=p.text, zorder=3))
    ax.text(5.1, 1.62, "F", color=p.text, fontsize=12, ha="center")
    ax.text(3.0, 0.5, "convex lens", color=p.subtext, fontsize=10, ha="center")

    ax.set_xlim(0.1, 6.0)
    ax.set_ylim(0.3, 3.7)


def draw_graph(ax, p: Palette, labels=None):
    """Generic labelled straight-line graph (v-t, rate-concentration...)."""
    x_label, y_label = (labels + ["x", "y"])[:2] if labels else ("time", "value")
    ax.plot([0.6, 5.4], [0.8, 3.1], color=p.accent, lw=2.8)
    ax.annotate("", xy=(0.6, 3.5), xytext=(0.6, 0.5),
                arrowprops=dict(arrowstyle="-|>", color=p.text, lw=1.6))
    ax.annotate("", xy=(5.8, 0.5), xytext=(0.6, 0.5),
                arrowprops=dict(arrowstyle="-|>", color=p.text, lw=1.6))
    ax.text(3.2, 0.15, x_label, color=p.subtext, fontsize=11, ha="center")
    ax.text(0.2, 2.0, y_label, color=p.subtext, fontsize=11, va="center", rotation=90)
    ax.text(4.4, 2.35, "slope", color=p.subtext, fontsize=10, rotation=25)
    ax.set_xlim(0, 6.2)
    ax.set_ylim(0, 3.9)


# ---------------------------------------------------------------------------
# Chemistry
# ---------------------------------------------------------------------------


def draw_energy_profile(ax, p: Palette, labels=None):
    """Reaction coordinate with activation energy and enthalpy change."""
    import numpy as np

    x = np.linspace(0, 6, 400)
    barrier = 1.9 * np.exp(-((x - 3.0) ** 2) / 0.7)
    y = 2.0 + barrier - 0.16 * x
    ax.plot(x, y, color=p.accent, lw=2.8)

    peak = float(y.max())
    ax.plot([0.35, 3.0], [y[20], y[20]], color=p.subtext, lw=1, ls=":")
    ax.plot([3.0, 5.9], [y[-1], y[-1]], color=p.subtext, lw=1, ls=":")

    ax.annotate("", xy=(1.55, peak), xytext=(1.55, y[20]),
                arrowprops=dict(arrowstyle="<->", color=p.text, lw=1.5))
    ax.text(1.72, (peak + y[20]) / 2, "Eₐ", color=p.text, fontsize=13, va="center")

    ax.annotate("", xy=(5.3, y[20]), xytext=(5.3, y[-1]),
                arrowprops=dict(arrowstyle="<->", color=p.text, lw=1.5))
    ax.text(5.45, (y[20] + y[-1]) / 2, "ΔH", color=p.text, fontsize=12, va="center")

    ax.text(0.55, y[20] + 0.22, "reactants", color=p.subtext, fontsize=10)
    ax.text(4.3, y[-1] - 0.34, "products", color=p.subtext, fontsize=10)
    ax.text(3.0, 0.35, "reaction coordinate", color=p.subtext, fontsize=10, ha="center")

    ax.set_xlim(0, 6.4)
    ax.set_ylim(0.1, peak + 0.7)


def draw_atom(ax, p: Palette, labels=None):
    """Nucleus with electron shells."""
    centre = (3.0, 2.0)
    ax.add_patch(Circle(centre, 0.34, color=p.accent, zorder=4))
    ax.text(centre[0], centre[1], "+", ha="center", va="center",
            fontsize=15, color="black", zorder=5, fontweight="bold")

    for radius, count in ((0.95, 2), (1.55, 8)):
        ax.add_patch(Circle(centre, radius, fill=False, edgecolor=p.text,
                            lw=1.5, alpha=0.85))
        import numpy as np

        for angle in np.linspace(0, 2 * np.pi, count, endpoint=False):
            ex = centre[0] + radius * np.cos(angle)
            ey = centre[1] + radius * np.sin(angle)
            ax.add_patch(Circle((ex, ey), 0.11, color=p.subtext, zorder=4))

    ax.text(centre[0], 0.32, "nucleus and electron shells",
            color=p.subtext, fontsize=10, ha="center")
    ax.set_xlim(0.6, 5.4)
    ax.set_ylim(0.1, 3.9)


# ---------------------------------------------------------------------------
# Biology
# ---------------------------------------------------------------------------


def draw_cell(ax, p: Palette, labels=None):
    """Labelled cell with nucleus, mitochondrion and membrane."""
    ax.add_patch(Ellipse((2.9, 2.0), 4.4, 3.1, facecolor=p.accent, alpha=0.16,
                         edgecolor=p.text, lw=2.4))
    ax.add_patch(Circle((2.5, 2.15), 0.62, facecolor=p.accent, edgecolor=p.text, lw=1.6))
    ax.add_patch(Circle((2.5, 2.15), 0.18, facecolor=p.text))
    ax.add_patch(Ellipse((4.0, 1.3), 0.95, 0.45, angle=-20,
                         facecolor=p.text, alpha=0.85, edgecolor=p.text))

    annotations = [
        ("nucleus", (2.5, 2.15), (0.35, 3.35)),
        ("mitochondrion", (4.0, 1.3), (4.3, 0.55)),
        ("cell membrane", (4.95, 2.55), (3.6, 3.55)),
    ]
    given = labels or []
    for index, (default, point, text_xy) in enumerate(annotations):
        label = given[index] if index < len(given) else default
        ax.annotate(label, xy=point, xytext=text_xy, color=p.text, fontsize=10,
                    arrowprops=dict(arrowstyle="-", color=p.subtext, lw=1.1))

    ax.set_xlim(0.1, 6.3)
    ax.set_ylim(0.2, 3.9)


def draw_cycle(ax, p: Palette, labels=None):
    """Circular process with named stages (Calvin, Krebs, cell cycle)."""
    import numpy as np

    stages = [str(s) for s in (labels or [])][:4] or ["Stage 1", "Stage 2", "Stage 3", "Stage 4"]
    centre = (3.0, 2.0)
    radius = 1.25

    for index, stage in enumerate(stages):
        angle = np.pi / 2 - index * 2 * np.pi / len(stages)
        x = centre[0] + radius * np.cos(angle)
        y = centre[1] + radius * np.sin(angle)
        ax.add_patch(Circle((x, y), 0.42, facecolor=p.accent, alpha=0.9, zorder=3))
        ax.text(x, y, str(index + 1), ha="center", va="center", fontsize=12,
                color="black", zorder=4, fontweight="bold")
        label_r = radius + 0.95
        lx = centre[0] + label_r * np.cos(angle)
        ly = centre[1] + label_r * np.sin(angle)
        ax.text(lx, ly, stage[:22], ha="center", va="center",
                color=p.text, fontsize=9.5, zorder=4)

    ax.add_patch(Arc(centre, 2 * radius, 2 * radius, theta1=0, theta2=330,
                     edgecolor=p.text, lw=2.0))
    ax.add_patch(FancyArrowPatch((centre[0] + radius, centre[1] - 0.02),
                                 (centre[0] + radius, centre[1] + 0.02),
                                 arrowstyle="-|>", mutation_scale=18, color=p.text))

    ax.set_xlim(0.2, 5.8)
    ax.set_ylim(0.05, 3.95)


def draw_dna(ax, p: Palette, labels=None):
    """Double helix with base-pair rungs."""
    import numpy as np

    t = np.linspace(0, 4 * np.pi, 300)
    x1 = 3.0 + 0.85 * np.sin(t)
    x2 = 3.0 - 0.85 * np.sin(t)
    y = np.linspace(0.4, 3.6, len(t))

    ax.plot(x1, y, color=p.accent, lw=2.6)
    ax.plot(x2, y, color=p.text, lw=2.6)
    for index in range(0, len(t), 18):
        ax.plot([x1[index], x2[index]], [y[index], y[index]],
                color=p.subtext, lw=1.2, alpha=0.8)

    ax.text(3.0, 0.05, "complementary strands", color=p.subtext,
            fontsize=10, ha="center")
    ax.set_xlim(1.2, 4.8)
    ax.set_ylim(-0.1, 3.9)


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------

# Shape-based diagrams must not be stretched: a circle drawn on unequal axes
# renders as an ellipse, which reads as a different object entirely (a "mass"
# becomes an oval, an electron shell becomes an orbit).
for _fn in (draw_force_pair, draw_orbit, draw_ray_lens, draw_atom, draw_cell,
            draw_cycle, draw_dna):
    _fn.equal_aspect = True

# Ordered: the first entry whose keyword appears in the topic or chapter wins.
DIAGRAM_KEYWORDS = [
    (draw_orbit, ("kepler", "orbit", "planet", "satellite", "solar")),
    (draw_force_pair, ("gravitation", "gravity", "coulomb", "electric charge",
                       "electrostatic", "law of motion", "force")),
    (draw_ray_lens, ("ray optics", "lens", "mirror", "refraction", "optical")),
    (draw_wave, ("wave", "oscillation", "sound", "shm", "periodic", "alternating")),
    (draw_energy_profile, ("kinetics", "activation", "rate of", "thermodynamic",
                           "enthalpy", "equilibrium")),
    (draw_atom, ("atom", "electron", "orbital", "nuclei", "nuclear",
                 "d and f", "periodic", "structure of the atom")),
    (draw_dna, ("dna", "inheritance", "molecular basis", "genetic", "nucleic")),
    (draw_cell, ("cell", "tissue", "organelle", "membrane", "microbe", "biotechnolog")),
    (draw_cycle, ("photosynthesis", "respiration", "krebs", "calvin", "cycle",
                  "reproduction", "ecosystem", "nitrogen")),
    (draw_graph, ("current electricity", "resistance", "motion", "velocity",
                  "concentration", "solution")),
]


def diagram_for_topic(topic: str, chapter: str = "", subject: str = ""):
    """Pick a drawing function for a topic, or None when nothing fits.

    Returning None matters: an unrelated diagram is worse than no diagram, so
    the slide falls back to its text panel rather than showing, say, a cell for
    a thermodynamics scene.
    """
    haystack = f"{topic} {chapter}".lower()
    for function, keywords in DIAGRAM_KEYWORDS:
        if any(keyword in haystack for keyword in keywords):
            return function
    return None


def render_diagram(function, theme: dict, size=(470, 390), labels=None):
    """Render a drawing function to a transparent PIL image."""
    palette = Palette(theme)
    dpi = 100
    fig = plt.figure(figsize=(size[0] / dpi, size[1] / dpi), dpi=dpi)
    fig.patch.set_alpha(0.0)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_facecolor("none")
    ax.axis("off")

    if getattr(function, "equal_aspect", False):
        # "box" shrinks the axes to satisfy the aspect and keeps the x/y limits
        # the drawing set. "datalim" does the opposite — it widens the data
        # range, padding the diagram with empty space that then dominates the
        # panel after the tight bounding box is applied.
        ax.set_aspect("equal", adjustable="box")

    try:
        function(ax, palette, labels)
    except Exception as exc:
        logger.warning("Diagram %s failed: %s", getattr(function, "__name__", "?"), exc)
        plt.close(fig)
        return None

    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", transparent=True, dpi=dpi,
                bbox_inches="tight", pad_inches=0.05)
    plt.close(fig)
    buffer.seek(0)
    return Image.open(buffer).convert("RGBA")


def render_for_topic(topic: str, theme: dict, chapter: str = "", subject: str = "",
                     size=(470, 390), labels=None):
    """Convenience: select and render in one call. Returns None if no match."""
    function = diagram_for_topic(topic, chapter, subject)
    if function is None:
        return None
    return render_diagram(function, theme, size=size, labels=labels)
