import os
os.environ.setdefault("PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT", "0")

import argparse
import json
import fitz
import pymupdf4llm
import re
import uuid
from pathlib import Path
from typing import Optional

from sentence_transformers import SentenceTransformer
from langchain_text_splitters import MarkdownHeaderTextSplitter
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct, Filter, FieldCondition, MatchValue
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

QDRANT_URL        = os.getenv("QDRANT_URL")
QDRANT_API_KEY    = os.getenv("QDRANT_API_KEY")
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION")
EMBEDDING_MODEL   = os.getenv("EMBEDDING_MODEL")
EMBEDDING_DIM     = 384
# Retrieval unit size. This was 5,000, which made a chunk embedding an average
# over a whole section: the universal law of gravitation sat at character 2,951
# of its chunk, and a query quoting the law verbatim did not retrieve that chunk
# at all. ~1,200 characters is roughly a paragraph, which is what a definition
# or a worked step actually occupies.
MAX_TEXT_CHUNK_CHARS = 1200

FIGURES_DIR = Path(__file__).resolve().parents[1] / "data" / "figures"

if not QDRANT_URL or not QDRANT_API_KEY:
    raise EnvironmentError("\n.env file is missing or incomplete\n")

SKIP_KEYWORDS = {"answer", "answers", "appendix", "appendices"}

# NEET is a Class 11-12 syllabus. Class 9/10 "Science" books sitting in the same
# dataset root were previously ingested into the shared collection, where they
# outranked the correct book for NEET queries ("Newton's law of gravitation"
# returned Class 9 Science above Class 11 Physics). Ingestion now skips them by
# default; pass --all-classes to include them anyway.
NEET_CLASS_LEVELS = {"11", "12"}

_model: Optional[SentenceTransformer] = None


def get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer(EMBEDDING_MODEL)
    return _model


def get_qdrant_client() -> QdrantClient:
    return QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)


def ensure_collection(client: QdrantClient):
    from qdrant_client.models import PayloadSchemaType
    existing = {c.name for c in client.get_collections().collections}
    if QDRANT_COLLECTION not in existing:
        client.create_collection(
            collection_name=QDRANT_COLLECTION,
            vectors_config=VectorParams(size=EMBEDDING_DIM, distance=Distance.COSINE),
        )
        print(f"[qdrant] Created collection: {QDRANT_COLLECTION}")
    # Index every field the retriever filters on. Without these Qdrant falls
    # back to a full scan for filtered searches. Re-creating is a no-op.
    for field_name in ("pdf_name", "subject", "class_level", "chunk_type", "chapter_name"):
        try:
            client.create_payload_index(
                collection_name=QDRANT_COLLECTION,
                field_name=field_name,
                field_schema=PayloadSchemaType.KEYWORD,
            )
        except Exception as exc:
            print(f"[qdrant] index {field_name}: {exc}")


def parse_metadata_from_path(pdf_path: Path) -> dict:
    parts = pdf_path.parts
    class_level = ""
    subject = ""
    part = ""
    for part_str in parts:
        m = re.match(r"Class\s+(\d+)", part_str, re.IGNORECASE)
        if m:
            class_level = m.group(1)
        subj_m = re.search(r"(?:Class\s+\d+\s+)(.*)", part_str, re.IGNORECASE)
        if subj_m:
            remainder = subj_m.group(1).strip()
            part_match = re.search(r"(part\s*\d+|part\s*[ivxIVX]+)", remainder, re.IGNORECASE)
            if part_match:
                part = part_match.group(1).strip()
                subject = remainder[: part_match.start()].strip()
            else:
                subject = remainder
    stem = pdf_path.stem
    chapter_number = 0
    chapter_name = stem
    num_match = re.match(r"^(\d+)[.\-_\s]+(.*)", stem)
    if num_match:
        chapter_number = int(num_match.group(1))
        chapter_name = num_match.group(2).replace("-", " ").replace("_", " ").strip()
    return {
        "class_level": class_level,
        "subject": subject,
        "part": part,
        "chapter_number": chapter_number,
        "chapter_name": chapter_name,
        "pdf_name": stem,
    }


def extract_figures(pdf_path: Path, meta: dict, out_root: Path, min_side: int = 110) -> list:
    """Save the embedded diagrams of a chapter PDF and label them by caption.

    Chunks carry no page numbers, so a figure cannot be linked to a chunk by
    position. It is linked by label instead: NCERT prose refers to its diagrams
    explicitly ("as shown in Fig. 7.2"), so the caption under each image is read
    and stored, and app.rag.figures resolves a label mentioned in retrieved text
    back to the saved file.

    Returns the manifest entries; writes PNGs plus figures.json under
    ``out_root/<pdf_name>/``.
    """
    out_dir = out_root / meta["pdf_name"]
    out_dir.mkdir(parents=True, exist_ok=True)

    doc = fitz.open(str(pdf_path))
    entries = []
    seen_xrefs = set()

    for page_index in range(len(doc)):
        page = doc[page_index]
        # Text blocks on this page, used to find the caption under an image.
        blocks = [b for b in page.get_text("blocks") if len(b) >= 5 and str(b[4]).strip()]

        for image in page.get_images(full=True):
            xref = image[0]
            if xref in seen_xrefs:
                continue

            try:
                rects = page.get_image_rects(xref)
            except Exception:
                rects = []
            if not rects:
                continue
            rect = rects[0]

            # Skip rules, decorative borders and tiny icons.
            if rect.width < min_side or rect.height < min_side:
                continue

            try:
                pixmap = fitz.Pixmap(doc, xref)
                if pixmap.n - pixmap.alpha >= 4:      # CMYK -> RGB
                    pixmap = fitz.Pixmap(fitz.csRGB, pixmap)
            except Exception as exc:
                print(f"[figures] xref {xref} on page {page_index + 1}: {exc}")
                continue

            caption, label = _caption_for_rect(blocks, rect)
            if not label:
                # Unlabelled images are decoration far more often than content.
                pixmap = None
                continue

            safe_label = re.sub(r"[^0-9a-zA-Z]+", "_", label)
            filename = f"fig_{safe_label}_p{page_index + 1:02d}_x{xref}.png"
            try:
                pixmap.save(str(out_dir / filename))
            except Exception as exc:
                print(f"[figures] could not save {filename}: {exc}")
                continue
            finally:
                pixmap = None

            seen_xrefs.add(xref)
            entries.append({
                "label": label,
                "caption": caption,
                "page": page_index + 1,
                "path": filename,
                "width": int(rect.width),
                "height": int(rect.height),
            })

    doc.close()

    manifest = {
        "meta": {
            "pdf_name": meta["pdf_name"],
            "chapter_name": meta["chapter_name"],
            "chapter_number": meta["chapter_number"],
            "subject": meta["subject"],
            "class_level": meta["class_level"],
        },
        "figures": entries,
    }
    (out_dir / "figures.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"[figures] {len(entries)} labelled figure(s) -> {out_dir}")
    return entries


CAPTION_LABEL = re.compile(r"\bFig(?:ure)?\.?\s*(\d+\.\d+[a-z]?)", re.I)


def _caption_for_rect(blocks, rect, max_gap: float = 90.0):
    """Find the 'Fig. X.Y ...' caption belonging to an image rectangle.

    NCERT captions sit directly below the figure, so the nearest text block that
    starts with a figure label and begins within ``max_gap`` points of the
    image's bottom edge wins.
    """
    best = (None, None, max_gap)
    for block in blocks:
        x0, y0, x1, y1, text = block[0], block[1], block[2], block[3], str(block[4])
        match = CAPTION_LABEL.search(text)
        if not match:
            continue
        gap = y0 - rect.y1
        if gap < -20:            # caption above the image: unusual, allow a little
            continue
        # Require horizontal overlap with the image column.
        if x1 < rect.x0 - 40 or x0 > rect.x1 + 40:
            continue
        if gap < best[2]:
            caption = " ".join(text.split())
            best = (caption, match.group(1), gap)
    return best[0], best[1]


def should_skip(pdf_path: Path) -> bool:
    name_lower = pdf_path.stem.lower()
    return any(kw in name_lower for kw in SKIP_KEYWORDS)


def _markdown_to_text(obj) -> str:
    if isinstance(obj, str):
        return obj
    for attr in ("markdown", "text", "content"):
        if isinstance(obj, dict) and attr in obj:
            return str(obj[attr])
        if hasattr(obj, attr):
            return str(getattr(obj, attr))
    return str(obj)


def extract_text(path: str, pdf_name: str) -> str:
    doc = pymupdf4llm.to_markdown(path)
    print(f"[extract] {pdf_name}.pdf")
    return doc


def extract_text_ocr(path: str, pdf_name: str) -> str:
    from paddleocr import PPStructureV3
    ocr = PPStructureV3(
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
        use_table_recognition=True,
        use_formula_recognition=False,
        use_chart_recognition=False,
        use_seal_recognition=False,
        enable_mkldnn=False,
        device="cpu",
    )
    markdown_list = []
    doc = fitz.open(path)
    for page_no in range(len(doc)):
        page = doc[page_no]
        pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5))
        safe_name = re.sub(r"[^a-zA-Z0-9_\-]", "_", pdf_name)
        temp_img = os.path.join(os.path.dirname(path), f"_ocr_tmp_{safe_name}_{page_no}.png")
        pix.save(temp_img)
        for res in ocr.predict(input=temp_img):
            markdown_list.append(res.markdown)
        try:
            os.remove(temp_img)
        except OSError:
            pass
    doc.close()
    extracted = ocr.concatenate_markdown_pages(markdown_list)
    if isinstance(extracted, tuple):
        extracted = extracted[0]
    print(f"[ocr] {pdf_name}.pdf")
    return _markdown_to_text(extracted)


def header_chunking(text: str):
    splitter = MarkdownHeaderTextSplitter(headers_to_split_on=[("##", "HEADER")])
    return splitter.split_text(text)


def _table_cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _is_separator_row(line: str) -> bool:
    return bool(re.match(r"^\s*\|[\s:\-|]+\|?\s*$", line))


def split_markdown_table_rows(table_lines, section, start_chunk_id):
    rows = [ln for ln in table_lines if ln.strip().startswith("|")]
    if not rows:
        return []
    header = None
    data_start = 0
    if len(rows) >= 2 and _is_separator_row(rows[1]):
        header = _table_cells(rows[0])
        data_start = 2
    elif rows and not _is_separator_row(rows[0]):
        first = _table_cells(rows[0])
        if len(first) > 2:
            header = first
            data_start = 1
    chunks = []
    chunk_id = start_chunk_id
    for line in rows[data_start:]:
        if _is_separator_row(line):
            continue
        cells = _table_cells(line)
        if not any(cells):
            continue
        if header and len(header) == len(cells):
            parts = [f"{h}: {v}" for h, v in zip(header, cells) if v and h]
            content = " | ".join(parts) if parts else " | ".join(c for c in cells if c)
        else:
            content = " | ".join(c for c in cells if c)
        if not content.strip():
            continue
        chunk_id += 1
        chunks.append({
            "chunk_id": chunk_id,
            "section": section,
            "chunk_type": "table_row",
            "content": content,
            "previous_text": "",
        })
    return chunks


def sub_chunking(header_chunks) -> list[dict]:
    data = []
    table = []
    inside_table = False
    temp_lines = ""
    chunk_id = 0
    for document in header_chunks:
        chunk = document.page_content
        metadata = document.metadata
        lines = chunk.splitlines()
        for line in lines:
            cleaned = line.strip()
            if cleaned.startswith("|"):
                if temp_lines:
                    chunk_id += 1
                    data.append({
                        "chunk_id": chunk_id,
                        "section": metadata,
                        "chunk_type": "text",
                        "content": "\n" + temp_lines,
                        "previous_text": "",
                    })
                    temp_lines = ""
                inside_table = True
                table.append(line)
            else:
                if inside_table:
                    chunk_id += 1
                    row_chunks = split_markdown_table_rows(table, metadata, chunk_id - 1)
                    if row_chunks:
                        data.extend(row_chunks)
                        chunk_id = row_chunks[-1]["chunk_id"]
                    else:
                        data.append({
                            "chunk_id": chunk_id,
                            "section": metadata,
                            "chunk_type": "table",
                            "content": "\n".join(table),
                            "previous_text": "",
                        })
                    table = []
                    inside_table = False
                if not cleaned:
                    continue
                temp_lines += (cleaned + " ") if cleaned[-1] in ".!?:;," else (cleaned + ". ")
                if len(temp_lines) >= MAX_TEXT_CHUNK_CHARS:
                    chunk_id += 1
                    data.append({
                        "chunk_id": chunk_id,
                        "section": metadata,
                        "chunk_type": "text",
                        "content": "\n" + temp_lines,
                        "previous_text": "",
                    })
                    temp_lines = ""
        if temp_lines:
            chunk_id += 1
            data.append({
                "chunk_id": chunk_id,
                "section": metadata,
                "chunk_type": "text",
                "content": "\n" + temp_lines,
                "previous_text": "",
            })
            temp_lines = ""
        if inside_table and table:
            chunk_id += 1
            row_chunks = split_markdown_table_rows(table, metadata, chunk_id - 1)
            if row_chunks:
                data.extend(row_chunks)
                chunk_id = row_chunks[-1]["chunk_id"]
            else:
                data.append({
                    "chunk_id": chunk_id,
                    "section": metadata,
                    "chunk_type": "table",
                    "content": "\n".join(table),
                    "previous_text": "",
                })
            table = []
            inside_table = False
    return data


def fill_previous_text(data: list[dict]) -> list[dict]:
    for i, chunk in enumerate(data):
        chunk["previous_text"] = "" if i == 0 else data[i - 1]["content"][-500:]
    return data


def embed_chunks(chunks: list[dict]) -> list[dict]:
    model = get_model()
    total = len(chunks)
    texts = [
        f"Section: {c['section'].get('HEADER', '')}\n\nContent: {c['content']}"
        for c in chunks
    ]
    embeddings = model.encode(texts, batch_size=64, show_progress_bar=False, normalize_embeddings=True)
    for i, chunk in enumerate(chunks):
        chunk["embedding"] = embeddings[i].tolist()
        if (i + 1) % 50 == 0 or (i + 1) == total:
            print(f"[embed] {i + 1}/{total}")
    return chunks


def upsert_to_qdrant(chunks: list[dict], meta: dict, client: QdrantClient):
    points = []
    for chunk in chunks:
        if not chunk.get("embedding"):
            continue
        payload = {
            **meta,
            "chunk_id": chunk["chunk_id"],
            "section": chunk["section"].get("HEADER", ""),
            "chunk_type": chunk["chunk_type"],
            "content": chunk["content"],
            "previous_text": chunk["previous_text"],
        }
        points.append(PointStruct(id=str(uuid.uuid4()), vector=chunk["embedding"], payload=payload))
    for i in range(0, len(points), 100):
        client.upsert(collection_name=QDRANT_COLLECTION, points=points[i:i + 100])
        print(f"[qdrant] {min(i + 100, len(points))}/{len(points)} upserted")


def is_already_ingested(pdf_name: str, client: QdrantClient) -> bool:
    results = client.scroll(
        collection_name=QDRANT_COLLECTION,
        scroll_filter=Filter(must=[FieldCondition(key="pdf_name", match=MatchValue(value=pdf_name))]),
        limit=1,
        with_payload=False,
        with_vectors=False,
    )
    return len(results[0]) > 0


def process_pdf(pdf_path: Path, client: QdrantClient, force: bool = False,
                all_classes: bool = False, with_figures: bool = True):
    if should_skip(pdf_path):
        print(f"[skip] {pdf_path.name} (answer/appendix)")
        return
    meta = parse_metadata_from_path(pdf_path)
    if not all_classes and meta["class_level"] not in NEET_CLASS_LEVELS:
        print(f"[skip] {pdf_path.name} (Class {meta['class_level'] or '?'} is outside the NEET syllabus; use --all-classes to include)")
        return
    if not force and is_already_ingested(meta["pdf_name"], client):
        print(f"[skip] Already in Qdrant: {pdf_path.name}")
        return
    print(f"\n[process] Class {meta['class_level']} | {meta['subject']} {meta['part']} | Ch.{meta['chapter_number']} {meta['chapter_name']}")

    if with_figures:
        try:
            extract_figures(pdf_path, meta, FIGURES_DIR)
        except Exception as exc:
            print(f"[figures] extraction failed for {pdf_path.name}: {exc}")

    text = extract_text(str(pdf_path), meta["pdf_name"])
    if len(text) < 5000:
        print("[extract] Low yield — falling back to OCR")
        text = extract_text_ocr(str(pdf_path), meta["pdf_name"])
    chunks = sub_chunking(header_chunking(text))
    chunks = fill_previous_text(chunks)
    chunks = embed_chunks(chunks)
    upsert_to_qdrant(chunks, meta, client)
    print(f"[done] {len(chunks)} chunks stored\n")


def main():
    parser = argparse.ArgumentParser(description="Ingest NCERT chapter PDFs into Qdrant.")
    parser.add_argument("input_path", help="Dataset root directory or single PDF file")
    parser.add_argument("--force", action="store_true", help="Re-ingest even if already present")
    parser.add_argument("--no-figures", action="store_true",
                        help="Skip extracting diagrams from the PDFs")
    parser.add_argument("--all-classes", action="store_true",
                        help="Also ingest Class 9/10 books (off-syllabus for NEET; excluded by default)")
    args = parser.parse_args()
    client = get_qdrant_client()
    ensure_collection(client)
    input_path = Path(args.input_path)
    if input_path.is_file() and input_path.suffix.lower() == ".pdf":
        process_pdf(input_path, client, args.force, args.all_classes, not args.no_figures)
    elif input_path.is_dir():
        pdf_files = sorted(input_path.rglob("*.pdf"))
        print(f"Found {len(pdf_files)} PDF(s) in {input_path}")
        for pdf in pdf_files:
            process_pdf(pdf, client, args.force, args.all_classes, not args.no_figures)
    else:
        print("Error: provide a valid PDF path or directory.")


if __name__ == "__main__":
    main()
