"""Quiz generation: rule-based questions, Gemini validation, fallback and adaptivity.

Offline by design: the retriever and Gemini are replaced with fakes, so these run
without Qdrant, Mongo or a network.

Run from the repo root:  python -m pytest tests/test_quiz_generation.py
"""

import asyncio
import json
import random
import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import pytest  # noqa: E402

from app.llm.gemini_service import GeminiUnavailable  # noqa: E402
from app.quiz import rule_based, service  # noqa: E402
from app.quiz.validation import normalise_difficulty, quote_is_grounded, validate_item  # noqa: E402
from app.services.adaptive_engine import UserLearningProfile, adaptive_engine  # noqa: E402

PASSAGE = (
    "The cell cycle is the sequence of events by which a cell duplicates its genome, "
    "synthesises the other constituents of the cell and divides into two daughter cells. "
    "The stages through which a cell passes from one division to the next is called cell cycle. "
    "The first atomic theory was proposed by John Dalton in 1808 and regarded the atom as indivisible. "
    "During interphase the chromosomes replicate while the nuclear envelope remains intact around them. "
    "Chromosomes condense during prophase and become visible under the microscope as thread like structures. "
    "Spindle fibres attach to the chromosomes at the kinetochore and pull the chromosomes towards opposite poles. "
    "Cytokinesis divides the cytoplasm of the cell after the chromosomes have separated into two groups. "
    "Mitosis is followed by cytokinesis and the chromosomes decondense inside each new daughter nucleus. "
    "The interphase lasts more than 95% of the duration of the cell cycle in a typical human cell."
)


def chunk(text=PASSAGE, chunk_type="text"):
    return SimpleNamespace(
        content=text, chunk_type=chunk_type, class_level="11", subject="biology",
        chapter_name="Cell Cycle and Cell Division", section="Summary", score=0.8,
    )


GOOD_QUOTE = (
    "Spindle fibres attach to the chromosomes at the kinetochore and pull the "
    "chromosomes towards opposite poles"
)


def good_item(**overrides):
    item = {
        "question": "Which structure do spindle fibres attach to on a chromosome?",
        "options": {"A": "Kinetochore", "B": "Nucleolus", "C": "Ribosome", "D": "Centriole"},
        "correct_option": "A",
        "difficulty": "easy",
        "explanation": "Spindle fibres attach at the kinetochore.",
        "source_quote": GOOD_QUOTE,
    }
    item.update(overrides)
    return item


# -- rule-based ---------------------------------------------------------------

def test_rule_based_questions_are_well_formed_and_grounded():
    questions = rule_based.generate([chunk()], "cell cycle", {"EASY": 2, "MEDIUM": 2, "HARD": 1}, seed=3)
    assert questions, "the passage supports at least one question"
    for q in questions:
        assert len(q.options) == 4
        assert len({o.lower() for o in q.options}) == 4
        assert q.correct_option in rule_based.LETTERS
        assert q.difficulty in ("EASY", "MEDIUM", "HARD")
        # Grounded by construction: the stem and explanation are the textbook's sentence.
        assert q.source_quote in PASSAGE.replace("  ", " ") or q.source_quote.rstrip(".") in PASSAGE
        # The answer is never left readable in the stem.
        answer = q.options[q.correct_index]
        assert answer.lower() not in q.question.lower().replace("_____", "")


def test_rule_based_never_repeats_a_source_sentence():
    questions = rule_based.generate([chunk()], "cell cycle", {"EASY": 3, "MEDIUM": 3, "HARD": 3}, seed=1)
    sources = [q.source_quote for q in questions]
    assert len(sources) == len(set(sources))


def test_rule_based_skips_table_rows_and_returns_nothing_for_empty_input():
    assert rule_based.generate([chunk("a | b | c", chunk_type="table_row")], "x", {"MEDIUM": 3}) == []
    assert rule_based.generate([], "x", {"MEDIUM": 3}) == []


def test_percentage_options_stay_at_or_below_100():
    questions = rule_based.generate([chunk()], "cell cycle", {"EASY": 0, "MEDIUM": 0, "HARD": 3}, seed=5)
    for q in questions:
        for option in q.options:
            if option.endswith("%"):
                assert 0 < float(option[:-1]) <= 100


# -- validation ---------------------------------------------------------------

def test_valid_gemini_item_passes_and_keeps_the_right_answer_after_shuffling():
    for seed in range(20):
        q = validate_item(good_item(), PASSAGE, random.Random(seed))
        assert q is not None
        assert q.options[q.correct_index] == "Kinetochore"
        assert q.difficulty == "EASY"
        assert q.source == "gemini"


@pytest.mark.parametrize("override", [
    {"source_quote": "Paris is the capital of France and a very large city"},   # not in the text
    {"source_quote": "too short"},
    {"options": {"A": "Same", "B": "same", "C": "x", "D": "y"}},                  # duplicates
    {"options": {"A": "x", "B": "y", "C": "z"}},                                  # three options
    {"correct_option": "E"},
    {"correct_option": ""},
    {"explanation": ""},
    {"question": "Short?"},
    {"question": "According to the passage, which structure do spindle fibres attach to?"},
])
def test_invalid_gemini_items_are_dropped(override):
    assert validate_item(good_item(**override), PASSAGE, random.Random(0)) is None


def test_difficulty_normalisation():
    assert normalise_difficulty("easy") == "EASY"
    assert normalise_difficulty(" Hard ") == "HARD"
    assert normalise_difficulty("expert") is None
    assert adaptive_engine.normalise_difficulty("expert") == "MEDIUM"
    assert adaptive_engine.normalise_difficulty(None) == "MEDIUM"


def test_quote_grounding_tolerates_stray_spacing_but_not_invention():
    assert quote_is_grounded(GOOD_QUOTE.replace(" ", "  "), PASSAGE)
    assert not quote_is_grounded("Mitochondria are the powerhouse of every living cell today", PASSAGE)


# -- adaptivity ---------------------------------------------------------------

def _pool():
    return [{"question_id": level, "difficulty": level} for level in ("EASY", "MEDIUM", "HARD")]


@pytest.mark.parametrize("ability,expected", [(0.0, "MEDIUM"), (-2.0, "EASY"), (2.5, "HARD"), (1.2, "HARD")])
def test_next_question_tracks_ability(ability, expected):
    profile = UserLearningProfile(user_id="u", ability=ability)
    assert adaptive_engine.pick_next_question(profile, _pool())["question_id"] == expected


def test_next_question_with_nothing_left_is_none():
    assert adaptive_engine.pick_next_question(UserLearningProfile(user_id="u"), []) is None


def test_answering_updates_ability_in_the_right_direction():
    profile = UserLearningProfile(user_id="u")
    adaptive_engine.update_after_answer(profile, "Cell Cycle", "hard", True, "q1")
    assert profile.ability > 0
    profile2 = UserLearningProfile(user_id="u")
    adaptive_engine.update_after_answer(profile2, "Cell Cycle", "EASY", False, "q1")
    assert profile2.ability < 0


@pytest.mark.parametrize("count", range(service.MIN_QUESTIONS, service.MAX_QUESTIONS + 1))
def test_mix_adds_up_and_always_has_a_hard_question(count):
    mix = service.mix_for(count)
    assert sum(mix.values()) == count
    assert mix["HARD"] >= 1 and mix["EASY"] >= 1 and mix["MEDIUM"] >= 0


# -- service: Gemini first, textbook text when it fails -----------------------

class FakeRetriever:
    def __init__(self, matched=True, chunks=None):
        self.matched = matched
        self.chunks = [chunk()] if chunks is None else chunks

    def retrieve(self, topic, **kwargs):
        return SimpleNamespace(
            chunks=self.chunks,
            context_text=PASSAGE,
            filters_applied={
                "topic_matched": self.matched,
                "match_score": 0.7 if self.matched else 0.1,
                "resolved_subject": "biology",
                "resolved_class_level": "11",
            },
        )


@pytest.fixture
def fake_env(monkeypatch):
    monkeypatch.setattr(service, "retriever", FakeRetriever())
    monkeypatch.setattr(service.gemini_service.settings, "gemini_api_key", "test-key", raising=False)
    monkeypatch.setattr(type(service.gemini_service), "is_configured", property(lambda self: True))
    return monkeypatch


def run(coro):
    return asyncio.run(coro)


def test_gemini_down_still_returns_a_quiz_from_the_textbook(fake_env):
    async def down(*args, **kwargs):
        raise GeminiUnavailable("503")

    fake_env.setattr(service.gemini_service, "generate_text", down)
    quiz = run(service.generate_quiz("cell cycle", num_questions=4))
    assert quiz.questions
    assert quiz.generator == "rule_based"
    assert all(q.source == "rule_based" for q in quiz.questions)
    assert any("Gemini was unavailable" in note for note in quiz.notes)


def test_gemini_timeout_falls_back(fake_env):
    async def slow(*args, **kwargs):
        await asyncio.sleep(5)

    fake_env.setattr(service.gemini_service, "generate_text", slow)
    fake_env.setattr(service.get_settings(), "quiz_llm_timeout_seconds", 0.05)
    quiz = run(service.generate_quiz("cell cycle", num_questions=3))
    assert quiz.generator == "rule_based"


def test_gemini_garbage_falls_back(fake_env):
    async def garbage(*args, **kwargs):
        return "I cannot help with that."

    fake_env.setattr(service.gemini_service, "generate_text", garbage)
    quiz = run(service.generate_quiz("cell cycle", num_questions=3))
    assert quiz.generator == "rule_based"
    assert quiz.notes


def test_good_gemini_questions_are_used_and_topped_up_from_the_textbook(fake_env):
    async def one_good_one_bad(*args, **kwargs):
        return json.dumps([good_item(), good_item(source_quote="Paris is the capital of France and a big city")])

    fake_env.setattr(service.gemini_service, "generate_text", one_good_one_bad)
    quiz = run(service.generate_quiz("cell cycle", num_questions=4))
    sources = [q.source for q in quiz.questions]
    assert sources.count("gemini") == 1
    assert "rule_based" in sources
    assert quiz.generator == "mixed"
    assert any("grounding check" in note for note in quiz.notes)
    gemini_q = next(q for q in quiz.questions if q.source == "gemini")
    assert gemini_q.citation.startswith("NCERT Class 11 Biology")


def test_all_gemini_questions_good_means_no_fallback_questions(fake_env):
    items = [
        good_item(question=f"Which structure do spindle fibres attach to on a chromosome? ({n})",
                  difficulty=level)
        for n, level in enumerate(["EASY", "EASY", "MEDIUM", "MEDIUM", "HARD"])
    ]

    async def good(*args, **kwargs):
        return json.dumps(items)

    fake_env.setattr(service.gemini_service, "generate_text", good)
    quiz = run(service.generate_quiz("cell cycle", num_questions=5))
    assert quiz.generator == "gemini"
    assert [q.difficulty for q in quiz.questions] == ["EASY", "EASY", "MEDIUM", "MEDIUM", "HARD"]


def test_topic_not_in_the_textbooks_is_a_clear_404(fake_env):
    fake_env.setattr(service, "retriever", FakeRetriever(matched=False))
    with pytest.raises(service.QuizUnavailable) as caught:
        run(service.generate_quiz("blorp"))
    assert caught.value.status_code == 404


def test_text_too_thin_for_any_question_is_a_clear_error(fake_env):
    fake_env.setattr(service, "retriever", FakeRetriever(chunks=[chunk("Short.")]))

    async def down(*args, **kwargs):
        raise GeminiUnavailable("503")

    fake_env.setattr(service.gemini_service, "generate_text", down)
    with pytest.raises(service.QuizUnavailable) as caught:
        run(service.generate_quiz("cell cycle"))
    assert caught.value.status_code == 422


# -- HTTP API: generate -> next -> submit -> summary --------------------------

class FakeDB:
    """In-memory stand-in for the Mongo-backed ``database`` the routes use."""

    def __init__(self, user):
        self.user = user
        self.quizzes, self.questions, self.attempts, self.videos = {}, [], {}, {}

    async def save_quiz(self, quiz, questions):
        self.quizzes[quiz["quiz_id"]] = quiz
        self.questions.extend(questions)

    async def get_quiz(self, quiz_id):
        return self.quizzes.get(quiz_id)

    async def get_quiz_questions(self, quiz_id):
        return [q for q in self.questions if q["quiz_id"] == quiz_id]

    async def get_quiz_question(self, question_id):
        return next((q for q in self.questions if q["question_id"] == question_id), None)

    async def get_quiz_attempt(self, attempt_id):
        return self.attempts.get(attempt_id)

    async def get_attempts_for_quiz(self, user_id, quiz_id):
        return [a for a in self.attempts.values() if a["user_id"] == user_id and a["quiz_id"] == quiz_id]

    async def save_quiz_attempt(self, attempt):
        self.attempts[attempt["attempt_id"]] = attempt

    async def update_user(self, user_id, fields):
        self.user.update(fields)

    async def get_video_record(self, job_id):
        return self.videos.get(job_id)


@pytest.fixture
def api(fake_env):
    from fastapi.testclient import TestClient

    from app.api.routes import quiz as quiz_routes
    from app.main import app
    from app.services.auth_service import get_current_user

    user = {"id": "u1", "ability": 0.0, "topic_mastery": {}, "response_history": []}
    db = FakeDB(user)
    fake_env.setattr(quiz_routes, "database", db)
    fake_env.setattr(quiz_routes.job_queue, "get_job", lambda job_id: None)

    async def down(*args, **kwargs):
        raise GeminiUnavailable("503")

    fake_env.setattr(service.gemini_service, "generate_text", down)
    app.dependency_overrides[get_current_user] = lambda: user
    yield SimpleNamespace(client=TestClient(app), db=db, user=user, monkeypatch=fake_env)
    app.dependency_overrides.clear()


def test_full_quiz_flow_over_http(api):
    c = api.client
    started = c.post("/api/quiz/generate", json={"topic": "cell cycle", "num_questions": 4})
    assert started.status_code == 200, started.text
    body = started.json()
    assert body["generator"] == "rule_based" and body["total"] >= 1 and body["notes"]
    quiz_id = body["quiz_id"]

    seen, correct = set(), 0
    while True:
        step = c.get(f"/api/quiz/{quiz_id}/next").json()
        if step["done"]:
            break
        question = step["question"]
        # The answer must never reach the student before they commit to one.
        assert "correct_option" not in question and "explanation" not in question
        assert question["question_id"] not in seen
        seen.add(question["question_id"])

        stored = next(q for q in api.db.questions if q["question_id"] == question["question_id"])
        pick = stored["correct_option"]
        res = c.post("/api/quiz/submit", json={"question_id": question["question_id"], "selected_option": pick})
        assert res.status_code == 200, res.text
        out = res.json()
        assert out["correct"] is True and out["correct_option"] == pick and out["explanation"]
        correct += 1

        # One answer per question: resubmitting must not move ability again.
        again = c.post("/api/quiz/submit", json={"question_id": question["question_id"], "selected_option": pick})
        assert again.status_code == 409

    assert len(seen) == body["total"]
    summary = step["summary"]
    assert summary["correct"] == correct == body["total"]
    assert summary["ability"] > 0
    assert summary["mastery"] is not None and summary["mastery"] > 0.5


def test_wrong_answers_lower_ability(api):
    c = api.client
    quiz_id = c.post("/api/quiz/generate", json={"topic": "cell cycle"}).json()["quiz_id"]
    question = c.get(f"/api/quiz/{quiz_id}/next").json()["question"]
    stored = next(q for q in api.db.questions if q["question_id"] == question["question_id"])
    wrong = next(letter for letter in "ABCD" if letter != stored["correct_option"])
    res = c.post("/api/quiz/submit", json={"question_id": question["question_id"], "selected_option": wrong}).json()
    assert res["correct"] is False
    assert res["correct_option"] == stored["correct_option"]
    assert api.user["ability"] < 0


def test_quiz_without_a_video_needs_only_a_topic_and_a_job_id_alone_is_enough(api):
    c = api.client
    assert c.post("/api/quiz/generate", json={}).status_code == 422
    assert c.post("/api/quiz/generate", json={"job_id": "nope"}).status_code == 404

    api.db.videos["job1"] = {"user_id": "u1", "topic": "cell cycle", "subject": "biology", "class_level": "11"}
    ok = c.post("/api/quiz/generate", json={"job_id": "job1"})
    assert ok.status_code == 200
    assert api.db.quizzes[ok.json()["quiz_id"]]["job_id"] == "job1"

    api.db.videos["theirs"] = {"user_id": "someone-else", "topic": "cell cycle"}
    assert c.post("/api/quiz/generate", json={"job_id": "theirs"}).status_code == 403


def test_unknown_topic_is_404_and_another_users_quiz_is_403(api):
    c = api.client
    api.monkeypatch.setattr(service, "retriever", FakeRetriever(matched=False))
    assert c.post("/api/quiz/generate", json={"topic": "blorp"}).status_code == 404

    api.monkeypatch.setattr(service, "retriever", FakeRetriever())
    quiz_id = c.post("/api/quiz/generate", json={"topic": "cell cycle"}).json()["quiz_id"]
    api.db.quizzes[quiz_id]["user_id"] = "someone-else"
    assert c.get(f"/api/quiz/{quiz_id}/next").status_code == 403
    assert c.get("/api/quiz/does-not-exist/next").status_code == 404
