"""Test figure extraction and label lookup without needing the NCERT PDFs.

Builds a small PDF that mimics NCERT page layout — a diagram with a
"Fig. 7.2 ..." caption underneath, a second labelled diagram, and an unlabelled
decorative image — then checks that extraction keeps the labelled figures, skips
the decoration, and that FigureStore resolves a label mentioned in prose.

    python tests/test_figure_extraction.py
"""

import json
import shutil
import sys
import tempfile
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import fitz  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402


def make_diagram(path: Path, label: str, size=(320, 240)) -> None:
    """A stand-in for a textbook diagram."""
    image = Image.new("RGB", size, (255, 255, 255))
    draw = ImageDraw.Draw(image)
    draw.ellipse([40, 40, 200, 200], outline=(20, 60, 160), width=5)
    draw.line([(20, 120), (300, 120)], fill=(200, 60, 20), width=3)
    draw.text((60, 210), label, fill=(0, 0, 0))
    image.save(path)


def build_sample_pdf(pdf_path: Path, work_dir: Path) -> None:
    """Two pages: two captioned figures and one unlabelled decoration."""
    diagram_a = work_dir / "a.png"
    diagram_b = work_dir / "b.png"
    decoration = work_dir / "c.png"
    make_diagram(diagram_a, "orbit")
    make_diagram(diagram_b, "field")
    make_diagram(decoration, "border")

    doc = fitz.open()

    page = doc.new_page(width=595, height=842)      # A4
    page.insert_text((60, 80), "7.3 KEPLER'S LAWS", fontsize=14)
    page.insert_text((60, 110), "The planet moves in an elliptical orbit around the sun.", fontsize=11)
    page.insert_image(fitz.Rect(60, 140, 380, 380), filename=str(diagram_a))
    page.insert_text((60, 400), "Fig. 7.2 The planet P moves in an elliptical orbit.", fontsize=10)

    page2 = doc.new_page(width=595, height=842)
    page2.insert_image(fitz.Rect(60, 100, 380, 340), filename=str(decoration))  # no caption
    page2.insert_text((60, 380), "Some ordinary paragraph text with no figure label.", fontsize=11)
    page2.insert_image(fitz.Rect(60, 420, 380, 660), filename=str(diagram_b))
    page2.insert_text((60, 680), "Figure 7.3 Gravitational field of a spherical shell.", fontsize=10)

    doc.save(str(pdf_path))
    doc.close()


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    work_dir = Path(tempfile.mkdtemp(prefix="figtest_"))
    failures = []
    try:
        pdf_path = work_dir / "7. GRAVITATION.pdf"
        build_sample_pdf(pdf_path, work_dir)
        print(f"Built sample PDF: {pdf_path.name}")

        # Import after the PDF exists; extract.py needs QDRANT_* only at import.
        from scripts.extract import extract_figures, parse_metadata_from_path

        meta = parse_metadata_from_path(pdf_path)
        out_root = work_dir / "figures"
        entries = extract_figures(pdf_path, meta, out_root)

        labels = sorted(e["label"] for e in entries)
        print(f"Extracted labels: {labels}")

        if labels != ["7.2", "7.3"]:
            failures.append(f"expected labels ['7.2', '7.3'], got {labels}")

        for entry in entries:
            saved = out_root / meta["pdf_name"] / entry["path"]
            if not saved.exists():
                failures.append(f"missing image file {saved}")
            if not entry["caption"].lower().startswith(("fig", "figure")):
                failures.append(f"caption not captured for {entry['label']}: {entry['caption']!r}")

        manifest_path = out_root / meta["pdf_name"] / "figures.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest["meta"]["chapter_name"].upper() != "GRAVITATION":
            failures.append(f"chapter metadata wrong: {manifest['meta']}")

        # Lookup: prose mentioning a label should resolve to the saved file.
        from app.rag.figures import FigureStore, find_figure_references

        refs = find_figure_references(
            "As shown in Fig. 7.2, the planet sweeps equal areas in equal times."
        )
        if refs != ["7.2"]:
            failures.append(f"reference parsing returned {refs}")

        store = FigureStore(root=out_root)
        figure = store.first_in_text(
            "The orbit is described in Fig. 7.2 and the shell result in Figure 7.3.",
            chapter_name="GRAVITATION",
        )
        if figure is None:
            failures.append("FigureStore did not resolve Fig. 7.2")
        else:
            print(f"Resolved Fig 7.2 -> {Path(figure.path).name}")
            if not figure.exists:
                failures.append("resolved figure path does not exist")

        missing = store.get("9.9", chapter_name="GRAVITATION")
        if missing is not None:
            failures.append("unknown label should resolve to None")

        print(f"Store holds {store.count()} figure entries")

    finally:
        shutil.rmtree(work_dir, ignore_errors=True)

    if failures:
        print("\nFAILURES:")
        for failure in failures:
            print(f"  - {failure}")
        return 1

    print("\nAll figure-extraction checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
