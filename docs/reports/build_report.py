"""Convert the mid-semester report from Markdown to DOCX and PDF.

Pandoc is not available on the development machines, but Microsoft Word is, so
the conversion goes Markdown -> styled HTML -> Word -> DOCX/PDF. Word is driven
through COM automation with its window hidden.

The HTML carries the print styling the institute format expects: Times New Roman
body text, bordered tables, a page break before every chapter, and monospace
blocks for the ASCII architecture diagrams.

    python docs/reports/build_report.py

Outputs, alongside the Markdown source:
    CPG92_MidSemester_Report.html
    CPG92_MidSemester_Report.docx
    CPG92_MidSemester_Report.pdf
"""

import sys
from pathlib import Path

REPORT_DIR = Path(__file__).resolve().parent
SOURCE = REPORT_DIR / "CPG92_MidSemester_Report.md"

CSS = """
@page { size: A4; margin: 2.5cm 2.5cm 2.5cm 3cm; }
body {
    font-family: "Times New Roman", Times, serif;
    font-size: 12pt;
    line-height: 1.5;
    text-align: justify;
    color: #000;
}
h1 {
    font-family: "Times New Roman", Times, serif;
    font-size: 16pt; font-weight: bold;
    text-align: right;
    border-bottom: 3px solid #000;
    padding-bottom: 4pt;
    margin-top: 24pt; margin-bottom: 14pt;
    page-break-before: always;
}
/* The cover is a centred title page, not a chapter heading.
   The page break goes on the last paragraph, not on the wrapper: Word's HTML
   engine propagates page-break-after from a container down to its descendants,
   which turned every <br/> on the cover into a page break. */
.cover { text-align: center; }
.cover p { text-align: center; }
.cover-title {
    font-size: 22pt; font-weight: bold;
    margin-top: 48pt; margin-bottom: 30pt;
    line-height: 1.3;
}
.cover-h1 { font-size: 15pt; font-weight: bold; margin: 14pt 0; }
.cover-h2 { font-size: 13pt; font-weight: bold; margin: 12pt 0; }
.cover-names { font-size: 12.5pt; font-weight: bold; line-height: 1.7; margin: 12pt 0; }
.cover-line { font-size: 12pt; margin: 6pt 0; }
.cover-dept { font-size: 12pt; font-weight: bold; margin-top: 40pt; line-height: 1.6; }
/* An empty paragraph carries the break so no <br/> inherits it. */
.cover-break { page-break-after: always; margin: 0; height: 0; }

/* The first real chapter heading follows the cover, which already broke. */
h1:first-of-type { page-break-before: avoid; }
h2 { font-size: 14pt; font-weight: bold; margin-top: 16pt; margin-bottom: 8pt; text-align: left; }
h3 { font-size: 12.5pt; font-weight: bold; margin-top: 12pt; margin-bottom: 6pt; text-align: left; }
h4 { font-size: 12pt; font-weight: bold; font-style: italic; margin-top: 10pt; text-align: left; }
p  { margin: 6pt 0; }
table {
    border-collapse: collapse;
    width: 100%;
    margin: 10pt 0;
    font-size: 10pt;
    page-break-inside: avoid;
}
th, td { border: 1px solid #000; padding: 4pt 6pt; text-align: left; vertical-align: top; }
th { background-color: #e8e8e8; font-weight: bold; }
pre {
    font-family: Consolas, "Courier New", monospace;
    font-size: 8pt;
    line-height: 1.15;
    border: 1px solid #999;
    padding: 8pt;
    background: #f7f7f7;
    page-break-inside: avoid;
    white-space: pre;
}
code { font-family: Consolas, "Courier New", monospace; font-size: 10pt; }
blockquote {
    border-left: 3px solid #666;
    margin-left: 0; padding-left: 12pt;
    font-size: 11pt;
}
img { max-width: 100%; height: auto; }
hr { border: none; border-top: 1px solid #bbb; margin: 14pt 0; }
strong { font-weight: bold; }
ul, ol { margin: 6pt 0 6pt 18pt; }
"""


def build_html(markdown_text: str) -> str:
    import markdown

    body = markdown.markdown(
        markdown_text,
        extensions=["tables", "fenced_code", "sane_lists", "attr_list"],
    )
    return (
        "<!DOCTYPE html>\n<html><head><meta charset='utf-8'>"
        "<title>CPG-92 Mid Semester Report</title>"
        f"<style>{CSS}</style></head><body>\n{body}\n</body></html>"
    )


def convert_with_word(html_path: Path, docx_path: Path, pdf_path: Path) -> None:
    """Open the HTML in Word and export DOCX and PDF."""
    import win32com.client as win32

    WD_FORMAT_DOCX = 16
    WD_FORMAT_PDF = 17

    word = win32.Dispatch("Word.Application")
    word.Visible = False
    word.DisplayAlerts = False
    try:
        doc = word.Documents.Open(str(html_path), ConfirmConversions=False)
        try:
            # Page numbers in the footer, centred.
            for section in doc.Sections:
                footer = section.Footers(1)          # wdHeaderFooterPrimary
                footer.Range.Fields.Add(footer.Range, 33)  # wdFieldPage
                footer.Range.ParagraphFormat.Alignment = 1  # centred
            doc.SaveAs2(str(docx_path), FileFormat=WD_FORMAT_DOCX)
            doc.SaveAs2(str(pdf_path), FileFormat=WD_FORMAT_PDF)
        finally:
            doc.Close(SaveChanges=False)
    finally:
        word.Quit()


def main() -> int:
    if not SOURCE.exists():
        print(f"Source not found: {SOURCE}")
        return 1

    html_path = SOURCE.with_suffix(".html")
    docx_path = SOURCE.with_suffix(".docx")
    pdf_path = SOURCE.with_suffix(".pdf")

    html = build_html(SOURCE.read_text(encoding="utf-8"))
    html_path.write_text(html, encoding="utf-8")
    print(f"HTML written: {html_path.name} ({len(html):,} bytes)")

    try:
        convert_with_word(html_path, docx_path, pdf_path)
    except ImportError:
        print("pywin32 is not installed; run: pip install pywin32")
        print(f"The HTML at {html_path} can be opened in Word and saved manually.")
        return 1
    except Exception as exc:
        print(f"Word conversion failed: {exc}")
        print(f"The HTML at {html_path} can be opened in Word and saved manually.")
        return 1

    for path in (docx_path, pdf_path):
        if path.exists():
            print(f"Written: {path.name} ({path.stat().st_size / 1024:.0f} KB)")
        else:
            print(f"NOT produced: {path.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
