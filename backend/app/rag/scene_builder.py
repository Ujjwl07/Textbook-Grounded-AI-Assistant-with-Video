"""Build video scenes from retrieved NCERT text.

This is the bridge that was missing: the video pipeline previously read scenes
from ``app.video.scene_presets``, so a generated video never touched the textbook
corpus. Here the five parts are assembled from passages actually retrieved from
Qdrant, with every on-screen definition carrying its chapter citation.

What this is not
----------------
This is a **retrieval-grounded assembler, not a script writer.** The project's
design (guide Section 4) has an LLM turn retrieved context into a pedagogical
5-part script; that step needs an API key the project does not have configured
yet. Until then this module selects and lightly formats real NCERT sentences —
it never paraphrases and never invents, so nothing on screen is ungrounded.

When the LLM stage lands, it replaces ``build_scenes`` and consumes the same
``RetrievalResult``; the scene dict contract does not change.
"""

import logging
import re
from typing import Optional

from app.rag.figures import get_figure_store
from app.rag.retriever import (
    NCERTRetriever,
    clean_ncert_text,
    get_retriever,
)

logger = logging.getLogger(__name__)

# Formula-ish lines worth putting on the EXAMPLE slide, in rough priority order.
_FORMULA_HINT = re.compile(r"[=∝]")

SUBJECT_TITLES = {"physics": "Physics", "chemistry": "Chemistry", "biology": "Biology"}


# A sentence that opens with a discourse marker or a bare pronoun refers back to
# something the slide will not show, so it reads as a non-sequitur on its own:
# "However, it is not special to the inverse square law of gravitation." is true
# but useless as a standalone bullet.
_DEPENDENT_OPENER = re.compile(
    r"^\s*(however|but|thus|therefore|hence|also|moreover|furthermore|besides|"
    r"this|that|these|those|it|its|they|their|them|such|so|then|here|"
    r"consequently|similarly|again|now|both|each|either|neither|"
    r"in this case|for this|as a result|on the other hand)\b",
    re.I,
)


def is_self_contained(text: str) -> bool:
    """True when a sentence can stand alone on a slide."""
    stripped = (text or "").strip()
    if not stripped or _DEPENDENT_OPENER.match(stripped):
        return False
    # Needs a subject and a verb's worth of words to be a usable statement.
    return 6 <= len(stripped.split()) <= 45


def _tidy(text: str, limit: int = 320) -> str:
    """Clean extracted text for display: drop markdown residue, trim length."""
    cleaned = clean_ncert_text(text)
    cleaned = re.sub(r"\s*_\s*", " ", cleaned)          # italic underscores
    cleaned = re.sub(r"\s+([,.;:])", r"\1", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    if len(cleaned) > limit:
        cut = cleaned[:limit].rsplit(" ", 1)[0]
        cleaned = cut.rstrip(" ,;:") + "…"
    return cleaned


def _shorten_for_bullet(text: str, limit: int = 110) -> str:
    """A bullet must read at a glance; keep the first clause."""
    cleaned = _tidy(text, limit=limit + 40)
    # Prefer cutting at a clause boundary rather than mid-phrase.
    for sep in (" — ", "; ", ", which ", ", where "):
        if sep in cleaned and len(cleaned) > limit:
            cleaned = cleaned.split(sep)[0]
    if len(cleaned) > limit:
        cleaned = cleaned[:limit].rsplit(" ", 1)[0].rstrip(" ,;:") + "…"
    return cleaned


def _collect_figures(passages, chapter_name: str, limit: int = 2) -> list:
    """Resolve figure labels mentioned in retrieved passages to image files."""
    store = get_figure_store()
    if store.count() == 0:
        return []
    found, seen = [], set()
    for passage in passages:
        figure = store.first_in_text(passage.text, chapter_name=chapter_name)
        if figure and figure.path not in seen:
            seen.add(figure.path)
            found.append(figure)
            if len(found) >= limit:
                break
    return found


def build_scenes(
    topic: str,
    subject: str,
    class_level: str,
    retriever: Optional[NCERTRetriever] = None,
) -> Optional[list]:
    """Assemble five scenes for ``topic`` from retrieved NCERT passages.

    Returns None when retrieval finds nothing usable, so the caller can fall back
    to the hand-written presets rather than render an empty video.
    """
    retriever = retriever or get_retriever()

    # Subject and class are resolved against the corpus rather than defaulted.
    # A missing subject used to fall back to "physics", which sent a query for
    # Photosynthesis to the Class 11 Physics chapter on Thermodynamics.
    requested_subject = SUBJECT_TITLES.get((subject or "").lower()) if subject else None
    scope = retriever.find_topic_scope(
        topic, subject=requested_subject, class_level=class_level
    )
    if not scope:
        logger.info("No chapter matched topic %r; falling back to presets", topic)
        return None

    chapter = scope["chapter"]
    subject_title = scope["subject"] or requested_subject or "Physics"
    class_level = scope["class_level"] or class_level or "11"
    subject_key = subject_title.lower()

    # Core passages for the concept and example scenes.
    overview = retriever.search_passages(
        f"{topic}: what it is and how it works",
        subject=subject_title,
        class_level=class_level,
        chapter_name=chapter,
        top_k_chunks=8,
        top_k_passages=8,
        window=1,
        min_words=10,
    )
    if not overview:
        logger.info("No passages for topic %r in chapter %r", topic, chapter)
        return None

    definition = retriever.find_definition(
        topic, subject=subject_title, class_level=class_level, chapter_name=chapter
    )
    cautions = retriever.find_cautions(
        topic, subject=subject_title, class_level=class_level, limit=6
    )

    citation = (definition.citation if definition else overview[0].citation)

    # Facts for the concept/example scenes, excluding whatever became the
    # definition so the same sentence is not shown twice, and excluding
    # sentences that cannot stand alone on a slide.
    definition_text = definition.text if definition else ""
    facts = [p for p in overview
             if p.text != definition_text and is_self_contained(p.text)]

    # Each scene draws from a distinct slice: reusing the same two sentences on
    # three consecutive slides made the video look like it was repeating itself.
    def take(count: int) -> list:
        taken, facts[:] = facts[:count], facts[count:]
        return taken

    concept_facts = take(2)
    example_facts = take(3)
    memory_facts = take(3)

    concept_bullets = [_shorten_for_bullet(p.text) for p in concept_facts]
    example_points = [_shorten_for_bullet(p.text) for p in example_facts]
    memory_bullets = [_shorten_for_bullet(p.text) for p in memory_facts]

    # Steps for the process panel, from the concept + example slices.
    steps = [_shorten_for_bullet(p.text, limit=68) for p in (concept_facts + example_facts)[:4]]

    formula_candidates = [p.text for p in overview if _FORMULA_HINT.search(p.text)]

    # Real NCERT diagrams, resolved from the "Fig. 7.2" labels the prose itself
    # mentions. Empty until the textbook PDFs are ingested with figure
    # extraction; the slides simply fall back to drawn panels until then.
    figures = _collect_figures(overview, chapter)

    # Drawn concept diagram, used on scenes with no real figure. Selected from
    # the topic; app.video.diagrams returns nothing when no diagram fits, and
    # the slide then falls back to its text panel.
    diagram_fields = {
        "diagram_topic": topic,
        "diagram_chapter": chapter,
        "diagram_subject": subject_title,
    }

    # The caution search runs over the same chapter, so it can return the
    # definition itself or a sentence already shown. Exclude anything used.
    shown = {definition_text}
    shown.update(p.text for p in concept_facts + example_facts + memory_facts)
    alert_passages = [
        p for p in cautions if p.text not in shown and is_self_contained(p.text)
    ][:3]
    alert_bullets = [_shorten_for_bullet(p.text) for p in alert_passages]
    if not alert_bullets:
        alert_bullets = [
            "Read the wording carefully — NEET tests exact definitions.",
            "Watch units and sign conventions in numerical parts.",
        ]

    scenes = [
        {
            "part": "HOOK",
            "slide_title": topic,
            "slide_bullets": [
                f"From {chapter.title()} — Class {class_level} {subject_title}.",
                "Grounded entirely in the NCERT textbook.",
            ],
            "narration_text": (
                f"Today we are studying {topic}, from the NCERT Class {class_level} "
                f"{subject_title} chapter on {chapter.title()}. Everything in this video "
                "comes straight from your textbook."
            ),
            "visual_type": "alert",
            "visual_data": {"caption": f"Class {class_level} {subject_title}"},
            "animation_type": "fade_in",
            "duration_hint_seconds": 12,
        },
        {
            "part": "CONCEPT",
            "slide_title": f"What is {topic}?",
            "definition": _tidy(definition.text, limit=300) if definition else "",
            "definition_source": citation if definition else "",
            "slide_bullets": concept_bullets,
            "narration_text": (
                (f"According to NCERT, {_tidy(definition.text, limit=300)} " if definition
                 else f"Let us look at what the NCERT chapter says about {topic}. ")
                + " ".join(_tidy(p.text, limit=220) for p in concept_facts[:1])
            ),
            "visual_type": "process" if steps else "alert",
            "visual_data": {"steps": steps} if steps else {"caption": topic},
            **({} if steps else diagram_fields),
            "animation_type": "slide_left",
            "duration_hint_seconds": 18,
        },
        {
            "part": "EXAMPLE",
            "slide_title": "From the Textbook",
            "slide_bullets": example_points or concept_bullets,
            "narration_text": " ".join(
                _tidy(p.text, limit=240) for p in example_facts[:2]
            ) or f"Let us apply what the chapter says about {topic}.",
            # A real textbook figure wins over a drawn panel; the renderer
            # ignores visual_type when image_path is set and present.
            "visual_type": "formula" if formula_candidates else "diagram",
            "formula_latex": _extract_formula(formula_candidates) if formula_candidates else None,
            "visual_data": {"title": chapter.title(), "labels": []},
            "image_path": figures[0].path if figures else None,
            "image_caption": figures[0].caption if figures else None,
            **({} if (formula_candidates or figures) else diagram_fields),
            "animation_type": "zoom",
            "duration_hint_seconds": 16,
        },
        {
            "part": "MEMORY",
            "slide_title": "Points to Remember",
            "slide_bullets": memory_bullets or concept_bullets,
            "narration_text": (
                f"Here is what to carry into the exam about {topic}. "
                + " ".join(_tidy(p.text, limit=200) for p in memory_facts[:2])
            ),
            # No labelled diagram here: truncating retrieved sentences to fit
            # 26-character labels produced "These observations led…", which is
            # noise. An alert panel with the chapter name is honest instead.
            "visual_type": "alert",
            "visual_data": {"caption": chapter.title()},
            "image_path": figures[1].path if len(figures) > 1 else None,
            "image_caption": figures[1].caption if len(figures) > 1 else None,
            **({} if len(figures) > 1 else diagram_fields),
            "animation_type": "slide_left",
            "duration_hint_seconds": 14,
        },
        {
            "part": "NEET_ALERT",
            "slide_title": "Watch Out For This",
            "slide_bullets": alert_bullets,
            "narration_text": (
                "Now the traps. "
                + (" ".join(_tidy(p.text, limit=220) for p in alert_passages[:2])
                   if alert_passages
                   else "Read the exact wording in the question, and check your units and "
                        "sign conventions before you answer.")
            ),
            "visual_type": "alert",
            "visual_data": {"caption": f"NEET trap — {topic}"},
            "animation_type": "zoom",
            "duration_hint_seconds": 14,
        },
    ]

    logger.info(
        "Built %s scenes for %r from Class %s %s / %s "
        "(definition: %s, cautions: %s, figures: %s)",
        len(scenes), topic, class_level, subject_title, chapter,
        bool(definition), len(cautions), len(figures),
    )

    # Stamp the resolved scope on every scene. The caller needs it to pick the
    # narration voice: with only the requested subject available, a Biology
    # lesson whose subject was inferred would be read in the Physics voice.
    for scene in scenes:
        scene["subject"] = subject_key
        scene["class_level"] = class_level
        scene["chapter_name"] = chapter

    return scenes


def _extract_formula(candidates: list) -> Optional[str]:
    """Pull a short equation out of a retrieved sentence, as LaTeX-ish text.

    Extraction from PDF loses most equation structure, so this deliberately only
    accepts something that already looks like a compact equation, and returns
    None otherwise rather than rendering a mangled formula.
    """
    for text in candidates:
        for fragment in re.findall(r"[A-Za-z0-9πΔ()\[\]/^_*+\-. ]{3,28}=[A-Za-z0-9πΔ()\[\]/^_*+\-. ]{1,28}", text):
            fragment = fragment.strip()
            # Reject prose that merely contains '=' inside a longer sentence.
            if len(fragment.split()) > 8:
                continue
            if any(ch.isalpha() for ch in fragment):
                return fragment.replace("*", r"\times ")
    return None
