import os
os.environ.setdefault("PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT", "0")

import argparse
import fitz
import pymupdf4llm
import re
import uuid
from pathlib import Path
from typing import Optional

from sentence_transformers import SentenceTransformer
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance, VectorParams, PointStruct, Filter, FieldCondition, MatchValue, FilterSelector,
)
from dotenv import load_dotenv

from ncert_chapters import lookup_chapter

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

QDRANT_URL        = os.getenv("QDRANT_URL")
QDRANT_API_KEY    = os.getenv("QDRANT_API_KEY")
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION") or "textbook_chunks"
EMBEDDING_MODEL   = os.getenv("EMBEDDING_MODEL") or "all-MiniLM-L6-v2"
EMBEDDING_DIM     = 384

# all-MiniLM-L6-v2 reads at most 256 word-pieces (~1000 chars of English, less for
# formula-heavy text); anything longer is silently truncated before embedding.
# Chunks are packed to TARGET and never exceed MAX so the whole chunk is embedded.
TARGET_CHUNK_CHARS = 750
MAX_CHUNK_CHARS    = 1000
MIN_CHUNK_CHARS    = 200   # smaller trailing pieces are merged into the previous chunk
OVERLAP_CHARS      = 150   # last sentence(s) of a chunk repeated at the start of the next
PREVIOUS_TEXT_CHARS = 500

# Stable namespace so re-ingesting a PDF overwrites the same point IDs.
POINT_NAMESPACE = uuid.UUID("6f1c2a9e-3b0d-4c55-9a43-1d2e7f8b0c11")

SKIP_KEYWORDS = {"answer", "answers", "appendix", "appendices"}
_model: Optional[SentenceTransformer] = None


def get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer(EMBEDDING_MODEL)
    return _model


def get_qdrant_client() -> QdrantClient:
    if not QDRANT_URL or not QDRANT_API_KEY:
        raise EnvironmentError("\nQDRANT_URL / QDRANT_API_KEY missing in backend/.env\n")
    return QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY, timeout=60)


def ensure_collection(client: QdrantClient):
    from qdrant_client.models import PayloadSchemaType
    existing = {c.name for c in client.get_collections().collections}
    if QDRANT_COLLECTION not in existing:
        client.create_collection(
            collection_name=QDRANT_COLLECTION,
            vectors_config=VectorParams(size=EMBEDDING_DIM, distance=Distance.COSINE),
        )
        print(f"[qdrant] Created collection: {QDRANT_COLLECTION}")
    # Indexes for every field the retrievers filter on (Qdrant Cloud refuses to
    # filter on an unindexed field: "Index required but not found").
    for field, schema in [
        ("pdf_name", PayloadSchemaType.KEYWORD),
        ("subject", PayloadSchemaType.KEYWORD),
        ("class_level", PayloadSchemaType.KEYWORD),
        ("chapter_number", PayloadSchemaType.INTEGER),
        ("chapter_name", PayloadSchemaType.KEYWORD),
        ("chunk_type", PayloadSchemaType.KEYWORD),
    ]:
        client.create_payload_index(
            collection_name=QDRANT_COLLECTION, field_name=field, field_schema=schema,
        )


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
    # Layout "Class 11/Physics/<file>.pdf": the subject is the folder right after "Class N".
    if not subject:
        for i, part_str in enumerate(parts[:-2]):
            if re.fullmatch(r"Class\s*\d+", part_str, re.IGNORECASE):
                subject = parts[i + 1].strip()
    stem = pdf_path.stem
    chapter_number = 0
    chapter_name = stem
    num_match = re.match(r"^(\d+)[.\-_\s]+(.*)", stem)
    ch_match = re.search(r"Ch(?:apter)?[\s_\-]*(\d+)$", stem, re.IGNORECASE)
    if num_match:
        chapter_number = int(num_match.group(1))
        chapter_name = num_match.group(2).replace("-", " ").replace("_", " ").strip()
    elif ch_match:
        # Filenames like "Class11_Physics_Ch4" carry only the number; look the title up.
        chapter_number = int(ch_match.group(1))
        known_name, known_part = lookup_chapter(class_level, subject, chapter_number)
        if known_name:
            chapter_name = known_name
        if not part:
            part = known_part
    return {
        "class_level": class_level,
        "subject": subject,
        "part": part,
        "chapter_number": chapter_number,
        "chapter_name": chapter_name,
        "pdf_name": stem,
    }


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
    doc = pymupdf4llm.to_markdown(path, show_progress=False)
    print(f"[extract] {pdf_name}.pdf")
    return doc


def extract_text_ocr(path: str, pdf_name: str) -> Optional[str]:
    try:
        from paddleocr import PPStructureV3
    except ImportError:
        print("[ocr] paddleocr not installed — keeping pymupdf4llm output")
        return None
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


# ─── Cleaning ────────────────────────────────────────────────────────────────

_SUBJECT_WORDS = {"physics", "chemistry", "biology", "science", "mathematics"}
# "4.1 INTRODUCTION", "5.1.1 Structure of ...", "2.2 atomic models" → numbered textbook section
_SECTION_RE = re.compile(r"^(\d{1,2}(?:\.\d{1,2}){1,3})\.?\s+(\S.{1,120})$")
_BACK_MATTER_RE = re.compile(r"^(summary|exercises|points to ponder|additional exercises)\b", re.I)


def _strip_inline_markup(line: str) -> str:
    line = re.sub(r"<!--.*?-->", "", line)
    line = re.sub(r"<sup>(.*?)</sup>", r"^\1", line)
    line = re.sub(r"<sub>(.*?)</sub>", r"\1", line)
    line = re.sub(r"<br\s*/?>", " ", line)
    line = re.sub(r"</?[a-zA-Z][^>]*>", "", line)              # <u>, <i>, ...
    line = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", line)           # images
    line = line.replace("**", "").replace("__", "")
    line = re.sub(r"(?<!\w)_(.+?)_(?!\w)", r"\1", line)          # _italic_
    return re.sub(r"[ \t]+", " ", line).strip()


def _plain(line: str) -> str:
    """Line text without heading marks / bullets / markup, for comparisons."""
    s = re.sub(r"^#+\s*", "", line.strip())
    s = re.sub(r"^[-*•]\s+", "", s)
    return _strip_inline_markup(s)


def _is_noise_line(plain: str, chapter_name: str) -> bool:
    low = plain.lower().strip(" .")
    if not low:
        return False
    if re.fullmatch(r"\d{1,4}", low):                                   # page number
        return True
    if re.fullmatch(r"(reprint\s*)?20\d\d\s*[-–]\s*\d\d", low):          # "2024-25" stamp
        return True
    if low in _SUBJECT_WORDS:                                           # running header
        return True
    if chapter_name and low == chapter_name.lower():                    # running header
        return True
    if re.fullmatch(r"[⊳►▶•·\-–—]+", low):
        return True
    return False


def _title(text: str) -> str:
    """'4.9.1  FRICTION' / 'atomic moDels' → '4.9.1 Friction' / 'Atomic Models'."""
    text = re.sub(r"\s+", " ", text).strip(" .:")
    # NCERT headings come out ALL CAPS or with small-caps artefacts ("sUb-atomic");
    # normalise those, but leave ordinary mixed case ("Newton's Laws", "DNA") alone.
    weird = any(w[1:] != w[1:].lower() and w[1:] != w[1:].upper() for w in text.split())
    if text.isupper() or weird:
        small = {"a", "an", "and", "as", "at", "by", "for", "in", "of", "on", "or", "the", "to", "with"}
        words = text.lower().split(" ")
        text = " ".join(
            w.upper() if w.strip("(),:;").upper() in _ACRONYMS
            else w if i and w in small
            else w[:1].upper() + w[1:]
            for i, w in enumerate(words)
        )
    return text[:1].upper() + text[1:]


_ACRONYMS = {"DNA", "RNA", "MRNA", "TRNA", "RRNA", "ATP", "ADP", "NADP", "NADPH", "PCR", "HIV",
             "AIDS", "STD", "STDS", "IUD", "IVF", "AC", "DC", "EMF", "LED", "LCR", "SHM", "BOD", "GMO"}
_QUESTION_START = re.compile(
    r"^(\(|(what|why|how|which|when|where|who|calculate|find|explain|give|state|define|describe|"
    r"show|prove|derive|draw|write|name|list|compare|distinguish|discuss|determine|estimate|"
    r"obtain|suggest|identify|predict|account|a|an|consider|answer|fill|match|if|two|three|one)\b"
    r"|the following\b|in a\b)",
    re.I,
)


def _section_key(number: str) -> tuple[int, ...]:
    return tuple(int(x) for x in number.split("."))


# ─── Chunking ────────────────────────────────────────────────────────────────

def _split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z(\"'‘“])", text)
    return [p.strip() for p in parts if p.strip()]


def _overlap_tail(text: str) -> str:
    """Last sentence(s) of a chunk, up to OVERLAP_CHARS, to seed the next chunk."""
    tail = ""
    for sent in reversed(_split_sentences(text)):
        if len(tail) + len(sent) + 1 > OVERLAP_CHARS:
            break
        tail = (sent + " " + tail).strip()
    return tail


def _hard_wrap(paragraph: str) -> list[str]:
    """Split a paragraph longer than MAX_CHUNK_CHARS at sentence (or word) boundaries."""
    pieces, buf = [], ""
    for sent in _split_sentences(paragraph):
        while len(sent) > MAX_CHUNK_CHARS:                 # pathological run-on sentence
            cut = sent.rfind(" ", 0, TARGET_CHUNK_CHARS) or TARGET_CHUNK_CHARS
            pieces.append((buf + " " + sent[:cut]).strip())
            buf, sent = "", sent[cut:].strip()
        if buf and len(buf) + len(sent) + 1 > TARGET_CHUNK_CHARS:
            pieces.append(buf)
            buf = sent
        else:
            buf = (buf + " " + sent).strip()
    if buf:
        pieces.append(buf)
    return pieces


def _pack_paragraphs(paragraphs: list[str]) -> list[str]:
    """Greedily pack paragraphs into chunks of ~TARGET chars, with sentence overlap."""
    units: list[str] = []
    for p in paragraphs:
        units.extend(_hard_wrap(p) if len(p) > MAX_CHUNK_CHARS else [p])
    chunks: list[str] = []
    buf = ""
    fresh = ""          # text added since the overlap seed; a chunk needs some of it
    for u in units:
        if fresh and len(buf) + len(u) + 2 > TARGET_CHUNK_CHARS and len(buf) + len(u) + 2 > MIN_CHUNK_CHARS:
            if len(buf) + len(u) + 2 <= MAX_CHUNK_CHARS and len(fresh) < MIN_CHUNK_CHARS:
                buf, fresh = buf + "\n\n" + u, fresh + u          # too small to close yet
                continue
            chunks.append(buf)
            seed = _overlap_tail(buf)
            buf = (seed + "\n\n" + u).strip() if seed else u
            fresh = u
        else:
            buf = (buf + "\n\n" + u).strip() if buf else u
            fresh = (fresh + " " + u).strip()
    if buf and fresh:
        if chunks and len(fresh) < MIN_CHUNK_CHARS and len(chunks[-1]) + len(fresh) + 2 <= MAX_CHUNK_CHARS + MIN_CHUNK_CHARS:
            chunks[-1] = chunks[-1] + "\n\n" + fresh
        else:
            chunks.append(buf)
    return chunks


def _table_cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _is_separator_row(line: str) -> bool:
    return bool(re.match(r"^\s*\|[\s:\-|]+\|?\s*$", line))


def split_markdown_table_rows(table_lines: list[str]) -> list[str]:
    """One self-describing string per table row ("Header: value | Header: value")."""
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
    out = []
    for line in rows[data_start:]:
        if _is_separator_row(line):
            continue
        cells = [_strip_inline_markup(c) for c in _table_cells(line)]
        if not any(cells):
            continue
        if header and len(header) == len(cells):
            hdr = [_strip_inline_markup(h) for h in header]
            parts = [f"{h}: {v}" for h, v in zip(hdr, cells) if v and h]
            content = " | ".join(parts) if parts else " | ".join(c for c in cells if c)
        else:
            content = " | ".join(c for c in cells if c)
        if len(content.strip()) >= 3:
            out.append(content)
    return out


def chunk_markdown(text: str, meta: dict) -> list[dict]:
    """
    Turn pymupdf4llm markdown into retrieval chunks.

    - Sections follow NCERT's numbered headings ("4.9.1 Friction"), whatever markdown
      level pymupdf4llm gave them; un-numbered headings ("Momentum", "Problem 2.1")
      stay inside the chunk text as a lead-in line.
    - Page furniture (page numbers, "2024-25", running subject/chapter headers) is dropped.
    - Paragraphs are packed into ~900-char chunks that fit the embedding model's window,
      with a one-sentence overlap between neighbours; tables become one chunk per row.
    """
    chapter_name = meta.get("chapter_name", "")
    chapter_number = meta.get("chapter_number") or 0
    section = "Introduction"
    last_key: tuple[int, ...] = ()
    in_back_matter = False
    paragraphs: list[str] = []
    para_lines: list[str] = []
    table: list[str] = []
    out: list[dict] = []

    def flush_para():
        if para_lines:
            para = " ".join(para_lines).strip()
            if para:
                paragraphs.append(para)
            para_lines.clear()

    def flush_section():
        flush_para()
        for c in _pack_paragraphs(paragraphs):
            out.append({"section": section, "chunk_type": "text", "content": c})
        paragraphs.clear()

    def flush_table():
        for row in split_markdown_table_rows(table):
            out.append({"section": section, "chunk_type": "table_row", "content": row})
        table.clear()

    for raw in text.splitlines():
        stripped = raw.strip()
        if stripped.startswith("|"):
            flush_para()
            table.append(stripped)
            continue
        if table:
            flush_table()
        if not stripped:
            flush_para()
            continue
        plain = _plain(stripped)
        if not plain or _is_noise_line(plain, chapter_name):
            continue
        # pymupdf4llm emits headings as "#..." lines, bold lines, or fully-bold bullets
        # ("- **2.3 Developments ...**"). Plain TOC bullets ("- 4.1 Introduction") are not headings.
        unbulleted = re.sub(r"^[-*•]\s+", "", stripped)
        is_heading = stripped.startswith("#") or (
            unbulleted.startswith("**") and unbulleted.rstrip().endswith("**") and len(plain) <= 100
        )
        sec = _SECTION_RE.match(plain) if is_heading else None
        if sec:
            key = _section_key(sec.group(1))
            title = sec.group(2)
            # A real section: right chapter, numbering moves forward, not inside the
            # exercises, and not phrased like a question ("2.24 What is ...").
            if (not in_back_matter
                    and (not chapter_number or key[0] == chapter_number)
                    and key > last_key
                    and not title.rstrip().endswith("?")
                    and not _QUESTION_START.match(title)):
                flush_section()
                last_key = key
                section = f"{sec.group(1)} {_title(title)}"
                continue
        if is_heading and _BACK_MATTER_RE.match(plain):
            flush_section()
            in_back_matter = True
            section = _title(_BACK_MATTER_RE.match(plain).group(1))
            continue
        if stripped.startswith("#"):
            # Chapter banner ("CHAPTER FOUR", "Unit 2", the chapter title) carries no content.
            if re.match(r"^(chapter|unit)\b", plain, re.I) or plain.lower() == chapter_name.lower():
                continue
            flush_para()
            paragraphs.append(plain.rstrip(":") + ":")   # sub-heading as lead-in line
            continue
        bullet = re.match(r"^[-*•]\s+", stripped)
        if bullet:
            flush_para()
            paragraphs.append("- " + plain)
            continue
        para_lines.append(_strip_inline_markup(stripped))
    if table:
        flush_table()
    flush_section()

    # Fold tiny text chunks into a same-section neighbour so nothing is embedded alone
    # with too little meaning (lead-in lines, a stray bullet at a section's end).
    merged: list[dict] = []
    for c in out:
        prev = merged[-1] if merged else None
        same = prev is not None and prev["chunk_type"] == c["chunk_type"] == "text" and prev["section"] == c["section"]
        if same and len(prev["content"]) < 60:
            c = {**c, "content": merged.pop()["content"] + "\n\n" + c["content"]}
        elif same and len(c["content"]) < MIN_CHUNK_CHARS // 2 and len(prev["content"]) + len(c["content"]) <= MAX_CHUNK_CHARS + MIN_CHUNK_CHARS:
            prev["content"] += "\n\n" + c["content"]
            continue
        merged.append(c)

    for i, c in enumerate(merged):
        c["chunk_id"] = i + 1
        c["previous_text"] = "" if i == 0 else merged[i - 1]["content"][-PREVIOUS_TEXT_CHARS:]
    return merged


# ─── Embedding & storage ────────────────────────────────────────────────────

def embedding_text(chunk: dict, meta: dict) -> str:
    return (
        f"{meta.get('subject', '')} Class {meta.get('class_level', '')}: {meta.get('chapter_name', '')}\n"
        f"Section: {chunk['section']}\n\n{chunk['content']}"
    )


def embed_chunks(chunks: list[dict], meta: dict) -> list[dict]:
    model = get_model()
    texts = [embedding_text(c, meta) for c in chunks]
    embeddings = model.encode(texts, batch_size=64, show_progress_bar=False, normalize_embeddings=True)
    for chunk, emb in zip(chunks, embeddings):
        chunk["embedding"] = emb.tolist()
    print(f"[embed] {len(chunks)} chunks")
    return chunks


def delete_pdf_points(pdf_name: str, client: QdrantClient):
    client.delete(
        collection_name=QDRANT_COLLECTION,
        points_selector=FilterSelector(filter=Filter(
            must=[FieldCondition(key="pdf_name", match=MatchValue(value=pdf_name))]
        )),
    )


def upsert_to_qdrant(chunks: list[dict], meta: dict, client: QdrantClient):
    points = []
    for chunk in chunks:
        payload = {
            **meta,
            "chunk_id": chunk["chunk_id"],
            "section": chunk["section"],
            "chunk_type": chunk["chunk_type"],
            "content": chunk["content"],
            "previous_text": chunk["previous_text"],
        }
        point_id = str(uuid.uuid5(POINT_NAMESPACE, f"{meta['pdf_name']}#{chunk['chunk_id']}"))
        points.append(PointStruct(id=point_id, vector=chunk["embedding"], payload=payload))
    for i in range(0, len(points), 100):
        client.upsert(collection_name=QDRANT_COLLECTION, points=points[i:i + 100])
    print(f"[qdrant] {len(points)} points upserted")


def is_already_ingested(pdf_name: str, client: QdrantClient) -> bool:
    results = client.scroll(
        collection_name=QDRANT_COLLECTION,
        scroll_filter=Filter(must=[FieldCondition(key="pdf_name", match=MatchValue(value=pdf_name))]),
        limit=1,
        with_payload=False,
        with_vectors=False,
    )
    return len(results[0]) > 0


def build_chunks(pdf_path: Path, meta: dict) -> list[dict]:
    text = extract_text(str(pdf_path), meta["pdf_name"])
    if len(text) < 5000:
        print("[extract] Low yield — trying OCR")
        text = extract_text_ocr(str(pdf_path), meta["pdf_name"]) or text
    return chunk_markdown(text, meta)


def process_pdf(pdf_path: Path, client: Optional[QdrantClient], force: bool = False, dry_run: bool = False):
    if should_skip(pdf_path):
        print(f"[skip] {pdf_path.name} (answer/appendix)")
        return
    meta = parse_metadata_from_path(pdf_path)
    if not dry_run and not force and is_already_ingested(meta["pdf_name"], client):
        print(f"[skip] Already in Qdrant: {pdf_path.name}")
        return
    print(f"\n[process] Class {meta['class_level']} | {meta['subject']} {meta['part']} | Ch.{meta['chapter_number']} {meta['chapter_name']}")
    chunks = build_chunks(pdf_path, meta)
    if dry_run:
        sizes = [len(c["content"]) for c in chunks if c["chunk_type"] == "text"]
        sections = sorted({c["section"] for c in chunks}, key=lambda s: [int(x) if x.isdigit() else 0 for x in re.findall(r"\d+", s)] or [999])
        print(f"[dry-run] {len(chunks)} chunks ({len(sizes)} text, {len(chunks) - len(sizes)} table rows); "
              f"text chars min/avg/max = {min(sizes, default=0)}/{sum(sizes) // max(len(sizes), 1)}/{max(sizes, default=0)}")
        print(f"[dry-run] sections: {sections}")
        return
    chunks = embed_chunks(chunks, meta)
    if force:
        delete_pdf_points(meta["pdf_name"], client)
    upsert_to_qdrant(chunks, meta, client)
    print(f"[done] {len(chunks)} chunks stored")


def main():
    parser = argparse.ArgumentParser(description="Ingest NCERT chapter PDFs into Qdrant.")
    parser.add_argument("input_path", help="Dataset root directory or single PDF file")
    parser.add_argument("--force", action="store_true", help="Replace PDFs that are already in Qdrant")
    parser.add_argument("--dry-run", action="store_true", help="Extract and chunk only; print stats, upload nothing")
    args = parser.parse_args()
    client = None if args.dry_run else get_qdrant_client()
    if client:
        ensure_collection(client)
    input_path = Path(args.input_path)
    if input_path.is_file() and input_path.suffix.lower() == ".pdf":
        pdf_files = [input_path]
    elif input_path.is_dir():
        pdf_files = sorted(input_path.rglob("*.pdf"))
        print(f"Found {len(pdf_files)} PDF(s) in {input_path}")
    else:
        print("Error: provide a valid PDF path or directory.")
        return
    failed = []
    for pdf in pdf_files:
        try:
            process_pdf(pdf, client, args.force, args.dry_run)
        except Exception as exc:  # keep going; report at the end
            print(f"[error] {pdf.name}: {exc}")
            failed.append(pdf.name)
    if failed:
        print(f"\n[summary] {len(failed)} PDF(s) failed: {failed}")


if __name__ == "__main__":
    main()
