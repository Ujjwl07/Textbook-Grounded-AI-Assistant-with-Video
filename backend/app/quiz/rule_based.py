"""Multiple-choice questions built directly from retrieved NCERT text. No LLM.

This is the quiz generator that always works: it needs only the passages the
retriever already returned, runs in well under a second, and every question is
grounded by construction because the stem and the explanation are the
textbook's own sentence. Gemini, when it is available, adds questions that test
more than recall (see ``service.py``); this module is what is left when it is
not.

Three kinds of question are produced, and the difficulty is assigned by kind,
not guessed:

* ``definition`` (EASY)   "...is called ____" / "Which is defined as ...?"
* ``term``       (MEDIUM) a sentence with its central key term blanked out
* ``number``     (HARD)   a sentence with a year or a measured value blanked out

The honest limit is that these are recall and recognition questions. They check
whether the student took in what the video and the chapter said; they cannot
ask for a calculation or an explanation.
"""

from __future__ import annotations

import random
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence

from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS

from app.rag.retriever import split_sentences
from app.rag.scene_builder import is_self_contained

LETTERS = ("A", "B", "C", "D")

# Words that are frequent in NCERT prose without naming anything a student
# could be asked about.
_GENERIC = {
    "called", "known", "shown", "given", "obtained", "following", "figure",
    "example", "value", "values", "number", "numbers", "type", "types", "kind",
    "form", "forms", "used", "using", "also", "different", "various", "several",
    "important", "term", "terms", "case", "cases", "ways", "process", "study",
    "unit", "chapter", "section", "thus", "hence", "called", "state", "states",
    "result", "results", "general", "particular", "similar", "certain", "number",
    "following", "possible", "known", "shows", "show", "makes", "make", "made",
    "called", "taken", "take", "takes", "increase", "decrease", "called",
    "present", "found", "called", "refers", "called", "become", "becomes",
}
_STOP = set(ENGLISH_STOP_WORDS) | _GENERIC

_WORD = re.compile(r"[A-Za-z][A-Za-z\-]{3,19}")

# Endings of adjectives, adverbs, verbs and ordinals. A blank over one of these
# can be filled by a dozen words, and as a distractor it is eliminated at sight.
_NOT_A_NOUN = re.compile(r"(ed|ly|ous|ive|ful|ic|ary|less|able|ible|teenth|tieth|enth|ward|wise)$")

# Sentences that are exercises, equations or calculations, not statements of fact.
_NOT_A_FACT = re.compile(
    r"(→|⟶|=|\^|×|\bcalculate\b|\bdetermine\b|\bfind\b|\bderive\b|\bprove\b|\bshow that\b|"
    r"\bsolve\b|\bwhat is\b|\bhow many\b|\bnumerical\b|\bproblem\b)",
    re.I,
)

_CALLED = re.compile(
    r"^(?P<defn>.{25,170}?)\s+(?:is|are)\s+(?:called|known as|termed|referred to as)\s+"
    r"(?:the\s+|an?\s+)?(?P<term>[A-Za-z][A-Za-z\- ]{2,38}?)\s*(?:[.,;(]|$)"
)
_DEFINED = re.compile(
    r"^(?P<term>[A-Z][A-Za-z\- ]{2,40}?)\s+(?:is|are)\s+defined\s+as\s+"
    r"(?P<defn>.{20,200}?)\s*\.?$"
)

# A year followed by "-18" is a range ("1900-18"), not a date to ask about.
_YEAR = re.compile(r"\b(1[5-9]\d\d|20[0-2]\d)\b(?!\s?[-–]\s?\d)")

# "A" and "u" are deliberately absent: "Figure 10.1 A diagrammatic view" is not
# ten point one amperes.
_UNITS = "nm|pm|cm|mm|km|kg|mg|eV|kJ|MeV|Hz|kHz|MHz|mol|amu|°C|K|J|N|V|W|m|g|s|%"

# A sentence that points at something the quiz does not show.
_REFERS_BACK = re.compile(
    r"\b(this|these|those|above|below|previous|preceding|such|figure|fig|table|"
    r"you|your|we|our|us|chapter|unit|learnt|learned|earlier|later|next|section)\b",
    re.I,
)
_QUANTITY = re.compile(
    rf"(?<![\w.])(?P<num>\d+(?:\.\d+)?)\s?(?P<unit>{_UNITS})(?![A-Za-z])"
)

DIFFICULTY_BY_KIND = {"definition": "EASY", "term": "MEDIUM", "number": "HARD"}


@dataclass
class Fact:
    """One self-contained sentence and where it came from."""

    sentence: str
    citation: str
    chapter: str = ""


@dataclass
class Question:
    question: str
    options: List[str]
    correct_index: int
    difficulty: str
    explanation: str
    source_quote: str
    citation: str
    kind: str
    meta: Dict = field(default_factory=dict)
    # "rule_based" or "gemini"; recorded on every stored question so a quiz that
    # fell back is visible as one, not silently passed off as an LLM quiz.
    source: str = "rule_based"

    @property
    def correct_option(self) -> str:
        return LETTERS[self.correct_index]


def citation_for(chunk) -> str:
    """"NCERT Class 11 Chemistry - Structure of Atom, Summary" for a chunk."""
    bits = ["NCERT"]
    if getattr(chunk, "class_level", None):
        bits.append(f"Class {chunk.class_level}")
    if getattr(chunk, "subject", None):
        bits.append(str(chunk.subject).title())
    head = " ".join(bits)
    tail = ", ".join(
        part for part in (getattr(chunk, "chapter_name", None), getattr(chunk, "section", None)) if part
    )
    return f"{head} - {tail}" if tail else head


def facts_from_chunks(chunks: Iterable) -> List[Fact]:
    """Self-contained prose sentences from the retrieved chunks, de-duplicated."""
    seen = set()
    facts: List[Fact] = []
    for chunk in chunks:
        # Table rows are pipe-delimited cells, not sentences.
        if getattr(chunk, "chunk_type", "text") != "text":
            continue
        citation = citation_for(chunk)
        for sentence in split_sentences(chunk.content):
            if (
                not is_self_contained(sentence)
                or _NOT_A_FACT.search(sentence)
                or _REFERS_BACK.search(sentence)
            ):
                continue
            key = re.sub(r"\W+", " ", sentence.lower()).strip()
            if key in seen:
                continue
            seen.add(key)
            facts.append(Fact(sentence, citation, getattr(chunk, "chapter_name", "") or ""))
    return facts


# --------------------------------------------------------------------------
# Term inventory
# --------------------------------------------------------------------------

def _lemma(word: str, known: Counter) -> str:
    low = word.lower()
    for suffix in ("es", "s"):
        if low.endswith(suffix) and low[: -len(suffix)] in known:
            return low[: -len(suffix)]
    return low


def _proper_nouns(facts: Sequence[Fact]) -> set:
    """Lower-cased words that are capitalised in the middle of a sentence."""
    names = set()
    for fact in facts:
        for match in _WORD.finditer(fact.sentence):
            word = match.group(0)
            if match.start() > 0 and word[0].isupper():
                names.add(word.lower())
    return names


def term_inventory(facts: Sequence[Fact]) -> Counter:
    """Sentence frequency of each noun-like content word, plurals folded in."""
    names = _proper_nouns(facts)
    raw = Counter()
    for fact in facts:
        for word in set(w.lower() for w in _WORD.findall(fact.sentence)):
            if word not in _STOP and word not in names and not _NOT_A_NOUN.search(word):
                raw[word] += 1
    merged = Counter()
    for word, count in raw.items():
        merged[_lemma(word, raw)] += count
    return merged


def _echo(word: str, topic_words: Sequence[str]) -> bool:
    return any(word.startswith(t[:5]) or t.startswith(word[:5]) for t in topic_words if len(t) > 3)


def _same_family(a: str, b: str) -> bool:
    a, b = a.lower(), b.lower()
    return a == b or a.startswith(b) or b.startswith(a)


def _blank(sentence: str, answer: str) -> Optional[str]:
    """``sentence`` with every form of ``answer`` replaced by a blank."""
    pattern = re.compile(rf"\b{re.escape(answer)}(?:s|es)?\b", re.I)
    if not pattern.search(sentence):
        return None
    blanked = pattern.sub("_____", sentence)
    # An answer that is still readable elsewhere in the stem gives itself away.
    if pattern.search(blanked):
        return None
    return blanked


def _finish(options: List[str], answer: str, rng: random.Random) -> Optional[tuple]:
    """Shuffle ``options`` (which include the answer) and return (list, index)."""
    unique: List[str] = []
    seen = set()
    for option in options:
        key = option.strip().lower()
        if key and key not in seen:
            seen.add(key)
            unique.append(option.strip())
    if len(unique) != 4 or answer.strip().lower() not in seen:
        return None
    rng.shuffle(unique)
    return unique, [o.lower() for o in unique].index(answer.strip().lower())


# --------------------------------------------------------------------------
# Distractors
# --------------------------------------------------------------------------

def _content_words(sentence: str) -> set:
    return {w.lower() for w in _WORD.findall(sentence) if w.lower() not in _STOP}


def _term_distractors(
    answer: str,
    sentence: str,
    inventory: Counter,
    topic_words: Sequence[str],
    rng: random.Random,
    preferred: Sequence[str] = (),
    sentence_words: Sequence[set] = (),
) -> List[str]:
    """Three other terms from the chapter that could not be the blank's answer.

    A distractor is rejected when the chapter already uses it alongside most of
    the words around the blank: "light" is a bad distractor for a sentence about
    the light reaction precisely because the textbook says "light reaction"
    elsewhere. That is what makes a wrong option actually wrong.
    """
    in_sentence = {w.lower() for w in _WORD.findall(sentence)}
    answer_l = answer.lower()
    around_blank = _content_words(sentence) - {answer_l}
    chosen: List[str] = []

    def fits_the_stem(term: str) -> bool:
        low = term.lower()
        need = max(4, int(0.6 * len(around_blank)))
        return any(
            low in words and len(words & around_blank) >= need for words in sentence_words
        )

    def acceptable(term: str) -> bool:
        low = term.lower()
        return (
            low not in in_sentence
            and not _same_family(low, answer_l)
            and not any(_same_family(low, c) for c in chosen)
            and not fits_the_stem(low)
        )

    for term in preferred:
        if acceptable(term) and len(chosen) < 3:
            chosen.append(term)

    def similarity(term: str) -> float:
        # Prefer terms shaped like the answer (same ending, similar length): a
        # distractor of the wrong kind is eliminated without reading the stem.
        score = 0.0
        if term[-3:] == answer_l[-3:]:
            score += 2.0
        score -= abs(len(term) - len(answer_l)) * 0.15
        score += min(inventory[term], 6) * 0.1
        return score + rng.random() * 0.4

    pool = [t for t, c in inventory.items() if c >= 2 and acceptable(t)]
    for term in sorted(pool, key=similarity, reverse=True):
        if len(chosen) == 3:
            break
        if acceptable(term):
            chosen.append(term)
    return chosen if len(chosen) == 3 else []


def _year_distractors(year: int, rng: random.Random) -> List[str]:
    steps = [3, 5, 8, 10, 12, 15, 20, 25, 30]
    rng.shuffle(steps)
    out = []
    for step in steps:
        for candidate in (year - step, year + step):
            if 1500 <= candidate <= 2025 and candidate != year and str(candidate) not in out:
                out.append(str(candidate))
                break
        if len(out) == 3:
            break
    return out if len(out) == 3 else []


def _format_number(value: float, like: str) -> str:
    if "." in like:
        decimals = len(like.split(".")[1])
        return f"{value:.{decimals}f}"
    return str(int(round(value)))


def _quantity_distractors(num: str, unit: str, pool: Sequence[tuple], rng: random.Random) -> List[str]:
    value = float(num)
    out: List[str] = []
    seen = {num}

    def add(text: str) -> None:
        if text not in seen and len(out) < 3:
            seen.add(text)
            out.append(text)

    if unit == "%":
        # A percentage cannot pass 100, and scaling 95 by ten says nothing.
        offsets = [5, 10, 15, 20, 25, 30, 40]
        rng.shuffle(offsets)
        for offset in offsets:
            for candidate in (value - offset, value + offset):
                if 0 < candidate <= 100:
                    add(_format_number(candidate, num))
                    break
        return [f"{x}%" for x in out] if len(out) == 3 else []

    # Real values with the same unit from elsewhere in the chapter first.
    for other_num, other_unit in pool:
        if other_unit == unit and other_num not in seen:
            add(other_num)
    factors = [0.5, 2.0, 10.0, 0.1, 1.5, 3.0]
    rng.shuffle(factors)
    for factor in factors:
        if len(out) == 3:
            break
        scaled = value * factor
        if scaled <= 0:
            continue
        add(_format_number(scaled, num))
    return [f"{x} {unit}" if unit != "%" else f"{x}%" for x in out] if len(out) == 3 else []


# --------------------------------------------------------------------------
# Generators, one per kind
# --------------------------------------------------------------------------

def _definition_questions(facts, inventory, topic_words, rng, sentence_words) -> List[Question]:
    terms_defined: List[tuple] = []
    for fact in facts:
        m = _CALLED.match(fact.sentence) or _DEFINED.match(fact.sentence)
        if m:
            terms_defined.append((fact, m))
    defined_terms = [m.group("term").strip() for _, m in terms_defined]

    questions = []
    for fact, m in terms_defined:
        term = m.group("term").strip()
        defn = m.group("defn").strip().rstrip(".")
        if len(term.split()) > 4 or _echo(term.lower(), topic_words) and len(term.split()) == 1:
            continue
        distractors = _term_distractors(
            term, fact.sentence, inventory, topic_words, rng,
            preferred=[t for t in defined_terms if t.lower() != term.lower()],
            sentence_words=sentence_words,
        )
        packed = _finish([term] + distractors, term, rng) if distractors else None
        if not packed:
            continue
        options, index = packed
        if _CALLED.match(fact.sentence):
            stem = f"Complete the statement: {defn} is called _____."
        else:
            stem = f"Which of the following is defined as {defn[0].lower() + defn[1:]}?"
        questions.append(Question(
            stem, options, index, DIFFICULTY_BY_KIND["definition"],
            fact.sentence, fact.sentence, fact.citation, "definition",
        ))
    return questions


def _term_questions(facts, inventory, topic_words, rng, sentence_words) -> List[Question]:
    questions = []
    for fact in facts:
        # A short sentence leaves too little around the blank to be answerable.
        if len(fact.sentence.split()) < 10:
            continue
        words = [w for w in _WORD.findall(fact.sentence)]
        candidates = []
        for index, word in enumerate(words):
            lemma = _lemma(word, inventory)
            if (
                index > 0
                and word[0].islower()
                and lemma not in _STOP
                and len(re.findall(rf"\b{re.escape(lemma)}(?:s|es)?\b", fact.sentence, re.I)) == 1
                and inventory[lemma] >= 2
                and len(lemma) >= 5
                and not _echo(lemma, topic_words)
            ):
                candidates.append((inventory[lemma], word))
        if not candidates:
            continue
        # The most chapter-central term that is not simply the chapter's title.
        _, answer = max(candidates, key=lambda c: (c[0], len(c[1])))
        stem_body = _blank(fact.sentence, answer)
        if not stem_body:
            continue
        distractors = _term_distractors(
            answer, fact.sentence, inventory, topic_words, rng, sentence_words=sentence_words
        )
        packed = _finish([answer.lower()] + distractors, answer.lower(), rng) if distractors else None
        if not packed:
            continue
        options, index = packed
        questions.append(Question(
            f"Fill in the blank: {stem_body}", options, index,
            DIFFICULTY_BY_KIND["term"], fact.sentence, fact.sentence,
            fact.citation, "term",
        ))
    return questions


def _number_questions(facts, rng) -> List[Question]:
    quantities = [
        (m.group("num"), m.group("unit"))
        for fact in facts for m in _QUANTITY.finditer(fact.sentence)
    ]
    questions = []
    for fact in facts:
        sentence = fact.sentence
        year = _YEAR.findall(sentence)
        quantity = list(_QUANTITY.finditer(sentence))
        if len(year) == 1 and sentence.count(year[0]) == 1:
            answer = year[0]
            distractors = _year_distractors(int(answer), rng)
        elif len(quantity) == 1 and not year:
            m = quantity[0]
            answer = m.group(0).strip()
            shown = m.group("num")
            distractors = _quantity_distractors(shown, m.group("unit"), quantities, rng)
            answer = f"{shown} {m.group('unit')}" if m.group("unit") != "%" else f"{shown}%"
        else:
            continue
        if not distractors:
            continue
        # The blank replaces the number *and* its unit, so options carry both.
        if year:
            stem = sentence.replace(answer, "_____", 1)
        else:
            stem = sentence[: quantity[0].start()] + "_____" + sentence[quantity[0].end():]
        packed = _finish([answer] + distractors, answer, rng)
        if not packed:
            continue
        options, index = packed
        questions.append(Question(
            f"Fill in the blank: {stem}", options, index,
            DIFFICULTY_BY_KIND["number"], sentence, sentence, fact.citation, "number",
        ))
    return questions


# --------------------------------------------------------------------------
# Public entry point
# --------------------------------------------------------------------------

def generate(
    chunks: Iterable,
    topic: str,
    mix: Dict[str, int],
    seed: Optional[int] = None,
    exclude_sources: Iterable[str] = (),
) -> List[Question]:
    """Up to ``sum(mix.values())`` questions for ``topic`` from ``chunks``.

    ``mix`` maps EASY/MEDIUM/HARD to the number wanted. When the text cannot
    supply a difficulty (a chapter with no dates or measurements has no HARD
    number questions) the shortfall is filled from the other kinds, so the quiz
    is smaller in variety rather than shorter.

    ``exclude_sources`` is a list of sentences already used by other questions,
    so a quiz topped up from this generator does not repeat itself.
    """
    rng = random.Random(seed)
    facts = facts_from_chunks(chunks)
    if not facts:
        return []

    chapters = {f.chapter for f in facts if f.chapter}
    topic_words = [w for w in re.findall(r"[a-z]+", " ".join([topic, *chapters]).lower()) if len(w) > 3]
    inventory = term_inventory(facts)

    sentence_words = [_content_words(f.sentence) for f in facts]
    pools = {
        "EASY": _definition_questions(facts, inventory, topic_words, rng, sentence_words),
        "MEDIUM": _term_questions(facts, inventory, topic_words, rng, sentence_words),
        "HARD": _number_questions(facts, rng),
    }
    used = {re.sub(r"\W+", " ", s.lower()).strip() for s in exclude_sources}

    def fresh(q: Question) -> bool:
        return re.sub(r"\W+", " ", q.source_quote.lower()).strip() not in used

    for pool in pools.values():
        rng.shuffle(pool)

    chosen: List[Question] = []

    def take(level: str, count: int) -> None:
        for q in pools[level]:
            if count <= 0:
                break
            if fresh(q):
                chosen.append(q)
                used.add(re.sub(r"\W+", " ", q.source_quote.lower()).strip())
                count -= 1

    for level in ("EASY", "MEDIUM", "HARD"):
        take(level, mix.get(level, 0))

    # Top up from whatever is left, easiest kinds first.
    wanted = sum(mix.values())
    for level in ("MEDIUM", "EASY", "HARD"):
        if len(chosen) >= wanted:
            break
        take(level, wanted - len(chosen))

    order = {"EASY": 0, "MEDIUM": 1, "HARD": 2}
    return sorted(chosen, key=lambda q: order[q.difficulty])
