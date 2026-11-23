"""Lookup for NCERT figures extracted from the textbook PDFs.

Chunks in Qdrant carry no page numbers, so a figure cannot be tied to a chunk by
position. It can be tied by *label*: NCERT prose refers to its own diagrams
explicitly ("as shown in Fig. 7.2"), and those labels survive text extraction.

So the ingestion pass writes, per book, a manifest of every extracted image with
the caption label it was found under, and this module resolves a label mentioned
in retrieved text back to the image file.

    backend/data/figures/
        keph107/                     <- one directory per source PDF
            figures.json             <- manifest
            fig_7_2_p03_x412.png

The store is empty until the PDFs are ingested; every call degrades to "no
figure found" rather than failing.
"""

import json
import logging
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional

from app.core.config import BACKEND_DIR

logger = logging.getLogger(__name__)

FIGURES_DIR = BACKEND_DIR / "data" / "figures"
MANIFEST_NAME = "figures.json"

# "Fig. 7.2", "Fig 7.2", "Figure 7.2" — the label forms NCERT uses.
FIGURE_REFERENCE = re.compile(r"\bFig(?:ure)?\.?\s*(\d+\.\d+[a-z]?)", re.I)


def normalise_label(label: str) -> str:
    """'Fig. 7.2 (b)' -> '7.2b', so references and captions compare equal."""
    match = FIGURE_REFERENCE.search(str(label))
    raw = match.group(1) if match else str(label)
    return re.sub(r"[^0-9a-z.]", "", raw.lower())


def find_figure_references(text: str) -> list:
    """Every figure label mentioned in a passage, in order of appearance."""
    seen, labels = set(), []
    for match in FIGURE_REFERENCE.finditer(str(text or "")):
        label = normalise_label(match.group(1))
        if label and label not in seen:
            seen.add(label)
            labels.append(label)
    return labels


@dataclass
class Figure:
    label: str
    path: str
    caption: str = ""
    page: int = 0
    chapter_name: str = ""
    subject: str = ""
    class_level: str = ""
    pdf_name: str = ""

    @property
    def exists(self) -> bool:
        return bool(self.path) and Path(self.path).exists()


class FigureStore:
    """Reads the per-book manifests written by the ingestion pass."""

    def __init__(self, root: Optional[Path] = None):
        self.root = Path(root or FIGURES_DIR)

    def _load_all(self) -> dict:
        """Map of (pdf_name, label) and (chapter_name, label) -> Figure."""
        index = {}
        if not self.root.exists():
            return index

        for manifest_path in self.root.glob(f"*/{MANIFEST_NAME}"):
            try:
                data = json.loads(manifest_path.read_text(encoding="utf-8"))
            except Exception as exc:
                logger.warning("Unreadable figure manifest %s: %s", manifest_path, exc)
                continue

            meta = data.get("meta", {})
            for entry in data.get("figures", []):
                path = entry.get("path", "")
                if not Path(path).is_absolute():
                    path = str((manifest_path.parent / path).resolve())
                figure = Figure(
                    label=normalise_label(entry.get("label", "")),
                    path=path,
                    caption=entry.get("caption", ""),
                    page=int(entry.get("page", 0) or 0),
                    chapter_name=meta.get("chapter_name", ""),
                    subject=meta.get("subject", ""),
                    class_level=str(meta.get("class_level", "")),
                    pdf_name=meta.get("pdf_name", manifest_path.parent.name),
                )
                if not figure.label:
                    continue
                index[(figure.pdf_name.lower(), figure.label)] = figure
                if figure.chapter_name:
                    index.setdefault((figure.chapter_name.lower(), figure.label), figure)
        return index

    @property
    def index(self) -> dict:
        if not hasattr(self, "_index"):
            self._index = self._load_all()
            logger.info("Figure store loaded %s figures from %s", len(self._index), self.root)
        return self._index

    def get(self, label: str, chapter_name: str = "", pdf_name: str = "") -> Optional[Figure]:
        """Resolve one figure label within a chapter or source book."""
        key = normalise_label(label)
        if not key:
            return None
        for scope in (pdf_name, chapter_name):
            if scope:
                figure = self.index.get((str(scope).lower(), key))
                if figure and figure.exists:
                    return figure
        return None

    def first_in_text(self, text: str, chapter_name: str = "", pdf_name: str = "") -> Optional[Figure]:
        """The first figure a passage refers to that we actually have on disk."""
        for label in find_figure_references(text):
            figure = self.get(label, chapter_name=chapter_name, pdf_name=pdf_name)
            if figure:
                return figure
        return None

    def count(self) -> int:
        return len(self.index)


@lru_cache(maxsize=1)
def get_figure_store() -> FigureStore:
    return FigureStore()
