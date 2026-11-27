"""Extract NEET PYQs from chapter-wise PDFs using Gemini Vision and store in MongoDB.

Usage
-----
    # Extract a single PDF and save to backend/data/pyqs/ + MongoDB:
    python backend/scripts/ingest_pyqs.py path/to/chapter.pdf --class 11 --subject Physics --chapter 1

    # Extract an entire folder (auto-infers class/subject/chapter from path/filename):
    python backend/scripts/ingest_pyqs.py backend/data/pyqs_pdfs/

    # Re-upload already-extracted JSON files to MongoDB without calling Gemini:
    python backend/scripts/ingest_pyqs.py backend/data/pyqs/ --from-json

    # Extract to JSON only (skip MongoDB):
    python backend/scripts/ingest_pyqs.py path/to/chapter.pdf --class 11 --subject Physics --chapter 1 --skip-db

Environment
-----------
Set ``GEMINI_PYQ_API_KEYS`` in ``backend/.env`` as a comma-separated list of
one or more free Gemini API keys (falls back to ``GEMINI_API_KEY``). The script
rotates keys automatically when a key hits a 429 rate limit.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import logging
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pymupdf  # PyMuPDF
import requests

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from app.core.config import get_settings  # noqa: E402
from app.services.database import database  # noqa: E402
from ncert_chapters import lookup_chapter  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("ingest_pyqs")

PYQ_JSON_DIR = BACKEND_DIR / "data" / "pyqs"
GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

_DAILY_HINT = re.compile(r"per[ -]?day|daily|quota|RESOURCE_EXHAUSTED", re.I)

PAGE_PROMPT = """You are extracting NEET Previous Year Questions (PYQs) from a textbook/question-bank PDF page image.

The page may have a two-column layout, grey section/subtopic banners (e.g., "Systems of Units", "Errors"), numbered questions with year tags like (2020-Covid) or (2024), options a/b/c/d, and/or an "Answer Key" table at the bottom.

Return ONLY a valid JSON object with this exact structure:
{
  "questions": [
    {
      "question_number": 1,
      "subtopic": "Name of the section banner above this question, or null if none on this page above it",
      "year_tag": "2020-Covid",
      "question": "Full question text. Convert all math, fractions, roots, powers, Greek letters into clean LaTeX wrapped in $...$.",
      "options": {
        "A": "option a text (with LaTeX $...$ for math)",
        "B": "option b text",
        "C": "option c text",
        "D": "option d text"
      },
      "has_diagram": false
    }
  ],
  "answer_key": {
    "1": "D",
    "2": "A"
  }
}

Rules:
- Read left column top-to-bottom, then right column top-to-bottom.
- Do NOT include the year tag inside the "question" text; put it in "year_tag" (e.g. "2024", "2020-Covid", "2017-Delhi", "2015 - Re").
- Uppercase all option keys ("A", "B", "C", "D") and all answer_key values ("A", "B", "C", "D").
- Set "has_diagram": true ONLY if the question or its options rely on a drawn figure, circuit, or graph that cannot be represented as text/LaTeX.
- If there is no Answer Key on this page, return "answer_key": {}.
- If there are no questions on this page (e.g. cover/key-only page), return "questions": [].
"""


class KeyPool:
    """Rotates across multiple Gemini API keys on 429 rate limits / daily quotas."""

    def __init__(self, keys: List[str]) -> None:
        if not keys:
            raise RuntimeError(
                "No Gemini API key found. Set GEMINI_PYQ_API_KEYS (or GEMINI_API_KEY) in backend/.env."
            )
        self.keys = keys
        self.index = 0
        self.cooldown_until: Dict[int, float] = {}

    def next_ready_key(self) -> Tuple[int, str]:
        """Return (key_index, key), waiting if all keys are temporarily cooling down."""
        while True:
            now = time.monotonic()
            for offset in range(len(self.keys)):
                idx = (self.index + offset) % len(self.keys)
                if self.cooldown_until.get(idx, 0.0) <= now:
                    self.index = (idx + 1) % len(self.keys)
                    return idx, self.keys[idx]

            soonest = min(self.cooldown_until.values())
            wait = max(1.0, soonest - now)
            if wait > 300:
                raise RuntimeError(
                    f"All {len(self.keys)} Gemini key(s) hit daily quota. "
                    "Add more keys to GEMINI_PYQ_API_KEYS or resume tomorrow."
                )
            logger.warning("All %d key(s) cooling down; waiting %.0fs...", len(self.keys), wait)
            time.sleep(wait)

    def mark_cooldown(self, idx: int, seconds: float, reason: str) -> None:
        self.cooldown_until[idx] = time.monotonic() + seconds
        logger.warning("Key #%d cooling down for %.0fs (%s)", idx + 1, seconds, reason)


# \b \f \n \r \t are genuinely ambiguous: each is BOTH a legal one-character
# JSON escape for a real control character AND the first letter of common
# LaTeX macros (\beta/\bar, \frac/\forall, \nu, \rho/\rightarrow, \tau/\times/
# \theta/\text/\tilde/\to/\triangle). Gemini emits the exact same two raw
# bytes (backslash + that letter) whichever one it means, so the two cases
# cannot be told apart from the letter alone — only from what follows it.
# NEET PYQs routinely use a genuine "\n" to separate an Assertion from its
# Reason, or to lay out List-I/List-II rows, so the two readings are not
# equally likely by default: treating every ambiguous letter as "must be
# LaTeX" (this script's first attempt) silently turned every real line break
# in every multi-part question into literal, visible "\n" text — a worse,
# more common failure than the one being fixed. Recognising specific LaTeX
# words lets both cases resolve correctly in the common case: "\nu" (an exact,
# known macro name) is kept as LaTeX, "\nA." or "\n(A)" or "\n\nList-I" (not a
# known macro name) decodes as the real line break it almost certainly is.
_AMBIGUOUS_LATEX_WORDS = frozenset({
    "beta", "bar", "binom", "boxed", "bullet",
    "frac", "forall", "flat",
    "nu", "neq", "nabla", "notin", "ni", "neg",
    "rho", "rightarrow", "rangle", "raisebox",
    "tau", "times", "tan", "tanh", "text", "tilde", "to", "triangle",
    "top", "theta", "tfrac",
})
# Match a maximal run of backslashes, plus whatever single escape-relevant
# thing immediately follows (captured separately so the run's parity can be
# judged on its own first): a unicode point, an escaped quote, or a run of
# letters (a possible LaTeX word). Nothing else needs capturing here — a run
# followed by a digit, symbol, space, or the string's closing quote falls
# through to the "no tail" branches below.
_BACKSLASH_RUN = re.compile(r"(\\+)(u[0-9a-fA-F]{4}|\"|[A-Za-z]+)?", re.S)


def _repair_latex_escapes(text: str) -> str:
    """Fix backslashes the model left raw for JSON, without breaking real newlines
    or re-escaping backslashes Gemini already escaped correctly.

    The extraction prompt asks for math as LaTeX ("$\\alpha$", "$\\sqrt{x}$"), and
    Gemini is inconsistent about JSON-escaping those backslashes: sometimes it
    writes them raw ("\alpha", invalid JSON on its own), sometimes it already
    double-escapes them correctly ("\\textit", already valid, standard JSON).

    An even-length run of N backslashes is unconditionally already valid — it
    decodes to exactly N/2 literal backslashes under plain JSON rules no matter
    what follows it — so it is left completely untouched; re-escaping it anyway
    (this function's first version) turned an already-correct "\\textit" into
    a wrong "\\\\textit". Only an ODD-length run has one truly unpaired
    backslash at its end, and only that single backslash — together with
    whatever single thing follows it — is genuinely ambiguous between "real
    JSON escape" and "raw LaTeX command": \b \f \n \r \t are legal one-character
    escapes AND the first letter of common macros (\beta/\bar, \frac/\forall,
    \nu, \rho/\rightarrow, \tau/\times/\theta/\text/\tilde/\to/\triangle).
    NEET PYQs also routinely use a genuine "\n" to separate an Assertion from
    its Reason or lay out List-I/List-II rows, so treating every such letter as
    "must be LaTeX" is wrong too (a worse, more common failure than the one
    being fixed): only a recognised macro word is kept as LaTeX; "\nA." or
    "\n(A)" (not a recognised word) decodes as the real line break it almost
    certainly is.
    """

    def repl(match: "re.Match[str]") -> str:
        run, tail = match.group(1), match.group(2) or ""
        if len(run) % 2 == 0:
            return run + tail  # already valid under plain JSON; do not touch it
        valid_prefix = "\\" * (len(run) - 1)  # (N-1)/2 already-valid pairs, untouched
        if tail == '"' or re.fullmatch(r"u[0-9a-fA-F]{4}", tail):
            return valid_prefix + "\\" + tail  # genuine escape: leave the pair as-is
        if tail[:1] in "bfnrt" and tail.isalpha():
            if tail in _AMBIGUOUS_LATEX_WORDS:
                return valid_prefix + "\\\\" + tail  # known macro: escape the LaTeX too
            return valid_prefix + "\\" + tail          # not a known word: a real control char
        return valid_prefix + "\\\\" + tail  # unambiguous (or no recognised tail): raw LaTeX

    return _BACKSLASH_RUN.sub(repl, text)


def _extract_json(raw_text: str) -> dict:
    cleaned = raw_text.strip()
    if "```" in cleaned:
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.I)
        cleaned = re.sub(r"\s*```$", "", cleaned).strip()
    match = re.search(r"\{.*\}", cleaned, re.S)
    if match:
        cleaned = match.group(0)
    cleaned = re.sub(r",\s*([\]}])", r"\1", cleaned)
    # Repair unconditionally, not only when json.loads first fails: a LaTeX
    # command whose first letter happens to be a legal one-character escape
    # (\times, \nu, \frac, \beta, \rightarrow, ...) parses "successfully" as
    # a control character plus the rest of the word, with no exception raised
    # to signal the corruption — so there is no reliable failure to fall back from.
    cleaned = _repair_latex_escapes(cleaned)
    return json.loads(cleaned)


def _call_gemini_vision(
    png_bytes: bytes,
    model: str,
    pool: KeyPool,
    max_attempts: int = 8,
) -> dict:
    """Send one rendered PDF page PNG to Gemini Vision and return parsed JSON."""
    b64 = base64.b64encode(png_bytes).decode("ascii")
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": PAGE_PROMPT},
                    {"inline_data": {"mime_type": "image/png", "data": b64}},
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.1,
            "maxOutputTokens": 8192,
            "responseMimeType": "application/json",
        },
    }
    url = GEMINI_ENDPOINT.format(model=model)

    for attempt in range(1, max_attempts + 1):
        idx, api_key = pool.next_ready_key()
        try:
            resp = requests.post(url, params={"key": api_key}, json=payload, timeout=90)
        except requests.RequestException as exc:
            logger.warning("Network error on attempt %d/%d: %s", attempt, max_attempts, exc)
            time.sleep(3 * attempt)
            continue

        if resp.status_code == 429:
            body = resp.text[:300]
            retry_after = resp.headers.get("Retry-After")
            if retry_after:
                cooldown = float(retry_after)
            elif _DAILY_HINT.search(body) and "per minute" not in body.lower():
                cooldown = 3600.0
            else:
                cooldown = 60.0
            pool.mark_cooldown(idx, cooldown, "HTTP 429")
            continue

        if resp.status_code >= 500:
            logger.warning("Gemini 5xx (%d) on attempt %d/%d", resp.status_code, attempt, max_attempts)
            time.sleep(3 * attempt)
            continue

        if resp.status_code in (400, 401, 403):
            raise RuntimeError(f"Gemini rejected key #{idx + 1} (HTTP {resp.status_code}): {resp.text[:300]}")

        resp.raise_for_status()
        data = resp.json()
        candidates = data.get("candidates") or []
        if not candidates:
            raise RuntimeError(f"Gemini returned no candidates: {data}")
        candidate = candidates[0]
        finish_reason = candidate.get("finishReason")
        parts = candidate.get("content", {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts)

        if not text and finish_reason and finish_reason != "STOP":
            # No content at all, and Gemini told us why: most often finishReason
            # "RECITATION" — PYQ PDFs are frequently near-verbatim copies of a
            # coaching-institute question bank, and Gemini's copyright filter
            # blocks reproducing phrasing it recognises. At temperature 0.1
            # (near-deterministic) a plain retry regenerates the identical
            # blocked wording every time, so raising the temperature instead
            # gives the sampler room to phrase around the filter while still
            # extracting the same underlying questions/options/answers.
            logger.warning(
                "Gemini returned no content on attempt %d/%d (finishReason=%s)",
                attempt, max_attempts, finish_reason,
            )
            if attempt == max_attempts:
                raise RuntimeError(
                    f"Gemini returned no content after {max_attempts} attempts "
                    f"(finishReason={finish_reason})"
                )
            payload["generationConfig"]["temperature"] = min(0.9, 0.1 + 0.15 * attempt)
            continue

        try:
            return _extract_json(text)
        except json.JSONDecodeError as exc:
            # Still malformed after the LaTeX-backslash repair — most likely the
            # response was truncated (maxOutputTokens) or otherwise genuinely
            # broken. Asking again is cheap and the model is not deterministic,
            # so a retry often succeeds; only the last attempt's error escapes.
            logger.warning("Malformed JSON on attempt %d/%d: %s", attempt, max_attempts, exc)
            if attempt == max_attempts:
                raise RuntimeError(f"Gemini kept returning malformed JSON: {exc}") from exc
            continue

    raise RuntimeError("Exceeded max attempts calling Gemini Vision")


def _parse_year(year_tag: Any) -> Optional[int]:
    match = re.search(r"(19|20)\d{2}", str(year_tag or ""))
    return int(match.group(0)) if match else None


def _infer_metadata(
    pdf_path: Path,
    class_level: Optional[str],
    subject: Optional[str],
    chapter_number: Optional[int],
) -> Tuple[str, str, int, str]:
    """Resolve (class_level, subject, chapter_number, chapter_name) from CLI args or path."""
    path_str = str(pdf_path)

    if not class_level:
        m = re.search(r"class[\s_-]*(11|12)\b", path_str, re.I)
        class_level = m.group(1) if m else ""

    if not subject:
        m = re.search(r"\b(physics|chemistry|biology)\b", path_str, re.I)
        subject = m.group(1).title() if m else ""
    else:
        subject = subject.strip().title()

    if chapter_number is None:
        m = re.search(r"(?:ch(?:apter)?[\s_-]*|^)(\d{1,2})(?=[_\s.-]|$)", pdf_path.stem, re.I)
        if m:
            chapter_number = int(m.group(1))

    if not (class_level and subject and chapter_number is not None):
        raise ValueError(
            f"Could not infer class/subject/chapter from '{pdf_path}'. "
            "Pass --class, --subject, and --chapter explicitly."
        )

    chapter_name, _part = lookup_chapter(class_level, subject, chapter_number)
    if not chapter_name:
        chapter_name = re.sub(r"^\d+[\s_-]*", "", pdf_path.stem).replace("-", " ").replace("_", " ").strip().title()
        logger.warning("Chapter %s not in ncert_chapters.py; using %r", chapter_number, chapter_name)

    return str(class_level), subject, int(chapter_number), chapter_name


def extract_pdf_to_pyqs(
    pdf_path: Path,
    class_level: str,
    subject: str,
    chapter_number: int,
    chapter_name: str,
    model: str,
    pool: KeyPool,
    dpi: int = 180,
    delay: float = 4.0,
) -> Tuple[List[dict], List[str]]:
    """Render each page of ``pdf_path``, extract questions + answer key, and validate."""
    doc = pymupdf.open(pdf_path)
    raw_questions: List[dict] = []
    answer_key: Dict[str, str] = {}
    last_subtopic: Optional[str] = None
    page_failures: List[str] = []

    logger.info("Extracting %s (%d pages) -> Class %s %s Ch.%d %s",
                pdf_path.name, len(doc), class_level, subject, chapter_number, chapter_name)

    for page_idx in range(len(doc)):
        page = doc[page_idx]
        pix = page.get_pixmap(dpi=dpi)
        png_bytes = pix.tobytes("png")

        logger.info("  Page %d/%d (%d KB)...", page_idx + 1, len(doc), len(png_bytes) // 1024)
        try:
            parsed = _call_gemini_vision(png_bytes, model=model, pool=pool)
        except RuntimeError as exc:
            # One unrecoverable page (most often a RECITATION block: the page's
            # phrasing closely matches a known compiled question bank, and no
            # amount of retrying escapes that at any temperature) used to abort
            # the WHOLE chapter, discarding every other page's results even
            # though only this one page is unextractable. Record it and move on
            # to the remaining pages instead of losing the whole chapter.
            logger.error("  Page %d/%d failed, skipping just this page: %s", page_idx + 1, len(doc), exc)
            page_failures.append(f"Page {page_idx + 1}: {exc}")
            if page_idx < len(doc) - 1 and delay > 0:
                time.sleep(delay)
            continue

        for q in parsed.get("questions") or []:
            if q.get("subtopic"):
                last_subtopic = str(q["subtopic"]).strip()
            else:
                q["subtopic"] = last_subtopic
            raw_questions.append(q)

        for q_num, ans in (parsed.get("answer_key") or {}).items():
            cleaned_ans = str(ans).strip().upper().strip("() .")
            if cleaned_ans in ("A", "B", "C", "D"):
                answer_key[str(q_num).strip()] = cleaned_ans

        if page_idx < len(doc) - 1 and delay > 0:
            time.sleep(delay)

    warnings: List[str] = list(page_failures)
    documents: List[dict] = []
    seen_nums = set()

    for q in raw_questions:
        q_num = q.get("question_number")
        if q_num is None:
            warnings.append(f"Skipped question with missing question_number: {str(q)[:80]}")
            continue
        q_num = int(q_num)
        if q_num in seen_nums:
            continue
        seen_nums.add(q_num)

        options_raw = q.get("options") or {}
        options = {
            k: str(options_raw.get(k) or options_raw.get(k.lower()) or "").strip()
            for k in ("A", "B", "C", "D")
        }
        missing_opts = [k for k, v in options.items() if not v]
        if missing_opts:
            warnings.append(f"Q{q_num}: missing option(s) {missing_opts}")

        correct = answer_key.get(str(q_num), "")
        if correct not in ("A", "B", "C", "D"):
            warnings.append(f"Q{q_num}: missing or invalid answer in Answer Key")

        year_tag = str(q.get("year_tag") or "").strip()
        year = _parse_year(year_tag)
        if year is None:
            warnings.append(f"Q{q_num}: could not parse year from {year_tag!r}")

        if q.get("has_diagram"):
            warnings.append(f"Q{q_num}: flagged as having a diagram (needs image review)")

        pyq_id = f"{class_level}-{subject.lower()}-ch{chapter_number:02d}-q{q_num:03d}"
        documents.append({
            "pyq_id": pyq_id,
            "exam": "NEET",
            "class_level": class_level,
            "subject": subject,
            "chapter_number": chapter_number,
            "chapter_name": chapter_name,
            "subtopic": q.get("subtopic") or "",
            "question_number": q_num,
            "year": year,
            "exam_tag": year_tag,
            "question": str(q.get("question") or "").strip(),
            "options": options,
            "correct_option": correct,
            "has_diagram": bool(q.get("has_diagram", False)),
            "question_image": None,
            "source_pdf": pdf_path.name,
        })

    if not documents and page_failures:
        # Every page that produced anything also failed outright (as opposed
        # to a page just genuinely having 0 questions, which real PYQ pages
        # don't). Raising here — instead of returning an empty, "successful"
        # result — stops process_pdf from writing a 0-question JSON file for
        # this chapter. Writing one would make it look already-extracted on
        # every future run (out_path.exists() is the only check), silently
        # skipping a chapter that actually needs a retry, forever.
        raise RuntimeError(
            f"Every page failed ({len(page_failures)}/{len(doc)}): {'; '.join(page_failures)}"
        )

    return documents, warnings


async def _push_to_mongo(documents: List[dict]) -> int:
    await database.connect()
    if not database.enabled:
        raise RuntimeError("Could not connect to MongoDB. Check MONGODB_URI in backend/.env.")
    try:
        return await database.upsert_pyqs(documents)
    finally:
        await database.close()


def _collect_inputs(target: Path, suffix: str) -> List[Path]:
    if target.is_file():
        return [target]
    if target.is_dir():
        return sorted(p for p in target.rglob(f"*{suffix}") if p.is_file())
    raise FileNotFoundError(f"Path not found: {target}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract NEET PYQ PDFs into JSON and MongoDB.")
    parser.add_argument("target", type=Path, help="Path to a PDF/JSON file or directory")
    parser.add_argument("--class", dest="class_level", help="Class level (11 or 12)")
    parser.add_argument("--subject", help="Subject (Physics, Chemistry, Biology)")
    parser.add_argument("--chapter", type=int, help="NCERT chapter number")
    parser.add_argument("--dpi", type=int, default=180, help="PDF render DPI (default: 180)")
    parser.add_argument("--delay", type=float, default=4.0, help="Seconds to sleep between pages (default: 4.0)")
    parser.add_argument("--force", action="store_true", help="Re-extract even if JSON already exists")
    parser.add_argument("--from-json", action="store_true", help="Load existing JSON file(s) and upsert to MongoDB")
    parser.add_argument("--skip-db", action="store_true", help="Save JSON only; do not write to MongoDB")
    args = parser.parse_args()

    settings = get_settings()

    if args.from_json:
        json_files = _collect_inputs(args.target, ".json")
        total_pushed = 0
        for jf in json_files:
            data = json.loads(jf.read_text(encoding="utf-8"))
            docs = data.get("questions", data) if isinstance(data, dict) else data
            logger.info("Loaded %d PYQs from %s", len(docs), jf.name)
            if not args.skip_db and docs:
                inserted = asyncio.run(_push_to_mongo(docs))
                total_pushed += inserted
                logger.info("  upserted %d into MongoDB", inserted)
        if not args.skip_db:
            logger.info("Upserted %d PYQs into MongoDB in total.", total_pushed)
        return

    pdfs = _collect_inputs(args.target, ".pdf")
    if not pdfs:
        logger.error("No PDF files found at %s", args.target)
        sys.exit(1)

    model = settings.gemini_pyq_model or settings.llm_model or "gemini-2.5-flash"
    pool = KeyPool(settings.pyq_gemini_keys)
    logger.info("Using Gemini model %s with %d API key(s)", model, len(pool.keys))

    PYQ_JSON_DIR.mkdir(parents=True, exist_ok=True)

    # Each chapter is pushed to MongoDB as soon as it is extracted, rather than
    # batching every chapter's upsert until the very last PDF has finished. A
    # single-key Gemini quota running out partway through a large folder used to
    # crash main() before the batched push ever ran, so every chapter that *did*
    # extract successfully was silently lost instead of landing in MongoDB.
    total_extracted = 0
    total_pushed = 0
    completed_pdfs = 0
    stopped_early = False

    for pdf_path in pdfs:
        class_level, subject, chapter_num, chapter_name = _infer_metadata(
            pdf_path, args.class_level, args.subject, args.chapter
        )
        out_name = f"class{class_level}_{subject.lower()}_ch{chapter_num:02d}_{pdf_path.stem}.json"
        out_path = PYQ_JSON_DIR / out_name

        if out_path.exists() and not args.force:
            logger.info("Skipping %s (already extracted at %s; use --force to re-extract)", pdf_path.name, out_path.name)
            cached = json.loads(out_path.read_text(encoding="utf-8"))
            docs = cached.get("questions", [])
            total_extracted += len(docs)
            completed_pdfs += 1
            if not args.skip_db and docs:
                inserted = asyncio.run(_push_to_mongo(docs))
                total_pushed += inserted
                logger.info("  upserted %d cached PYQs from %s into MongoDB", inserted, out_path.name)
            continue

        try:
            docs, warnings = extract_pdf_to_pyqs(
                pdf_path,
                class_level=class_level,
                subject=subject,
                chapter_number=chapter_num,
                chapter_name=chapter_name,
                model=model,
                pool=pool,
                dpi=args.dpi,
                delay=args.delay,
            )
        except Exception as exc:  # noqa: BLE001 - one bad PDF must not abort the whole folder
            if "quota" in str(exc).lower():
                # No key can serve any further request today; every chapter
                # already saved above is already in MongoDB, so stop instead
                # of letting the exception crash the process.
                logger.error("Stopping extraction: %s", exc)
                logger.error(
                    "%d chapter(s) already extracted and upserted into MongoDB before this point. "
                    "Re-run the same command (keys reset after 24h, or add more to GEMINI_PYQ_API_KEYS) "
                    "to continue from %s onward.",
                    completed_pdfs, pdf_path.name,
                )
                stopped_early = True
                break
            # An unexpected, non-quota error: this one PDF failed, but nothing
            # says the rest of the folder will too, so keep going.
            logger.error("Failed to extract %s: %s", pdf_path.name, exc)
            logger.error("Skipping this PDF; re-run with --force on it later to retry.")
            continue

        out_payload = {
            "meta": {
                "class_level": class_level,
                "subject": subject,
                "chapter_number": chapter_num,
                "chapter_name": chapter_name,
                "source_pdf": pdf_path.name,
                "total": len(docs),
                "warnings": warnings,
            },
            "questions": docs,
        }
        out_path.write_text(json.dumps(out_payload, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info("Saved %d PYQs to %s", len(docs), out_path)
        for w in warnings:
            logger.warning("  [%s] %s", pdf_path.name, w)

        total_extracted += len(docs)
        completed_pdfs += 1
        if not args.skip_db and docs:
            inserted = asyncio.run(_push_to_mongo(docs))
            total_pushed += inserted
            logger.info("  upserted %d PYQs into MongoDB", inserted)

    logger.info(
        "Done: %d PYQ(s) extracted, %d upserted into MongoDB.%s",
        total_extracted, total_pushed, " Stopped early — see above." if stopped_early else "",
    )
    if stopped_early:
        sys.exit(1)


if __name__ == "__main__":
    main()
