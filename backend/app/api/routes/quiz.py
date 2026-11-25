import logging
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status

from app.models.schemas import (
    QuizAttempt,
    QuizGenerateRequest,
    QuizHistoryResponse,
    QuizNextResponse,
    QuizQuestionPublic,
    QuizStartResponse,
    QuizSubmitRequest,
    QuizSubmitResponse,
    QuizSummary,
)
from app.quiz.rule_based import LETTERS
from app.quiz.service import QuizUnavailable, generate_quiz
from app.services.adaptive_engine import adaptive_engine
from app.quiz.mistakes import classify_by_rule, classify_with_gemini
from app.services.auth_service import get_current_user
from app.services.database import database
from app.services.job_queue import job_queue

router = APIRouter(prefix="/quiz", tags=["quiz"])
logger = logging.getLogger(__name__)


async def _lesson_for_job(job_id: str, user_id: str) -> dict:
    """Topic, subject and class of one of the student's own video jobs."""
    job = job_queue.get_job(job_id)
    lesson = job.model_dump() if job else await database.get_video_record(job_id)
    if not lesson:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video job not found")
    if lesson.get("user_id") != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot use another user's video")
    return lesson


@router.post("/generate", response_model=QuizStartResponse)
async def generate_quiz_for_topic(
    request: QuizGenerateRequest,
    current_user: dict = Depends(get_current_user),
) -> QuizStartResponse:
    """Build a quiz from the textbook passages for a topic.

    Works with no video: send ``topic``. Send ``job_id`` instead to quiz on a
    lesson the student generated. Either way nothing here touches the video
    queue, so generating a quiz never delays a render.
    """
    user_id = current_user["id"]
    topic, subject, class_level = request.topic, request.subject, request.class_level

    if request.job_id:
        lesson = await _lesson_for_job(request.job_id, user_id)
        topic = topic or lesson.get("topic")
        subject = subject or lesson.get("subject")
        class_level = class_level or lesson.get("class_level")
    if not topic:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Give a topic, or the job_id of a video, to build a quiz from.",
        )

    try:
        quiz = await generate_quiz(topic, subject, class_level, request.num_questions)
    except QuizUnavailable as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    quiz_id = uuid4().hex
    question_docs = [
        {
            "question_id": uuid4().hex,
            "quiz_id": quiz_id,
            "user_id": user_id,
            "topic": quiz.topic,
            "subject": quiz.subject,
            "class_level": quiz.class_level,
            "difficulty": q.difficulty,
            "question": q.question,
            "options": dict(zip(LETTERS, q.options)),
            "correct_option": q.correct_option,
            "explanation": q.explanation,
            "citation": q.citation,
            "source_quote": q.source_quote,
            "source": q.source,
            "kind": q.kind,
        }
        for q in quiz.questions
    ]
    await database.save_quiz(
        {
            "quiz_id": quiz_id,
            "user_id": user_id,
            "topic": quiz.topic,
            "requested_topic": quiz.requested_topic,
            "subject": quiz.subject,
            "class_level": quiz.class_level,
            "job_id": request.job_id,
            "generator": quiz.generator,
            "notes": quiz.notes,
            "total": len(question_docs),
        },
        question_docs,
    )
    logger.info(
        "Quiz %s for %r: %s question(s), generator=%s%s",
        quiz_id[:8], topic, len(question_docs), quiz.generator,
        f" (from video {request.job_id[:8]})" if request.job_id else "",
    )
    return QuizStartResponse(
        quiz_id=quiz_id,
        topic=quiz.topic,
        subject=quiz.subject,
        class_level=quiz.class_level,
        total=len(question_docs),
        generator=quiz.generator,
        notes=quiz.notes,
    )


@router.get("/{quiz_id}/next", response_model=QuizNextResponse)
async def next_quiz_question(
    quiz_id: str,
    current_user: dict = Depends(get_current_user),
) -> QuizNextResponse:
    """The next question for this student, chosen by their current ability.

    Answers and explanations are never sent here; ``/quiz/submit`` returns them
    once the student has committed to an option.
    """
    user_id = current_user["id"]
    quiz = await database.get_quiz(quiz_id)
    if not quiz:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Quiz not found")
    if quiz["user_id"] != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot access another user's quiz")

    questions = await database.get_quiz_questions(quiz_id)
    attempts = await database.get_attempts_for_quiz(user_id, quiz_id)
    answered = {attempt["question_id"] for attempt in attempts}
    remaining = [q for q in questions if q["question_id"] not in answered]
    profile = adaptive_engine.from_dict(current_user, user_id)

    base = {
        "quiz_id": quiz_id,
        "topic": quiz["topic"],
        "answered": len(answered),
        "total": len(questions),
    }
    chosen = adaptive_engine.pick_next_question(profile, remaining)
    if chosen:
        return QuizNextResponse(
            **base,
            done=False,
            question=QuizQuestionPublic(
                question_id=chosen["question_id"],
                difficulty=adaptive_engine.normalise_difficulty(chosen.get("difficulty")),
                question=chosen["question"],
                options=chosen["options"],
            ),
        )

    return QuizNextResponse(
        **base,
        done=True,
        summary=QuizSummary(
            correct=sum(1 for attempt in attempts if attempt.get("correct")),
            total=len(questions),
            ability=profile.ability,
            mastery=profile.topic_mastery.get(quiz["topic"]),
            next_topic=adaptive_engine.next_topic(profile),
        ),
    )


@router.post("/submit", response_model=QuizSubmitResponse)
async def submit_quiz_answer(
    request: QuizSubmitRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
) -> QuizSubmitResponse:
    user_id = current_user["id"]
    question = await database.get_quiz_question(request.question_id)
    if not question:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Quiz question not found")
    if question.get("user_id") not in (None, user_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot answer another user's question")

    attempt_id = f"{user_id}:{request.question_id}"
    if await database.get_quiz_attempt(attempt_id):
        # One answer per question: otherwise ability could be pushed up by
        # resubmitting the same easy question.
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This question was already answered")

    profile = adaptive_engine.from_dict(current_user, user_id)
    correct_option = str(question["correct_option"]).upper()
    is_correct = request.selected_option.upper() == correct_option
    topic = question["topic"]
    difficulty = adaptive_engine.normalise_difficulty(question.get("difficulty"))
    profile = adaptive_engine.update_after_answer(
        profile=profile,
        topic=topic,
        difficulty=difficulty,
        is_correct=is_correct,
        question_id=request.question_id,
    )

    profile_dict = adaptive_engine.to_dict(profile)
    await database.update_user(user_id, {
        "ability": profile_dict["ability"],
        "topic_mastery": profile_dict["topic_mastery"],
        "response_history": profile_dict["response_history"],
    })

    # Details the dashboard needs for "Recent questions" and "Mistake analysis".
    options = question.get("options") or {}
    selected = request.selected_option.upper()
    quiz_doc = await database.get_quiz(question.get("quiz_id")) if question.get("quiz_id") else None
    await database.save_quiz_attempt(
        {
            "question": question.get("question", ""),
            "subject": (quiz_doc or {}).get("subject"),
            "selected_text": options.get(selected, ""),
            "correct_text": options.get(correct_option, ""),
            "explanation": question.get("explanation", ""),
            # A quick rule-based label now; Gemini refines it in the background.
            "mistake_type": None if is_correct else classify_by_rule(question, difficulty, profile.ability),
            "mistake_source": None if is_correct else "rule",
            "attempt_id": attempt_id,
            "user_id": user_id,
            "quiz_id": question.get("quiz_id"),
            "question_id": request.question_id,
            "topic": topic,
            "difficulty": difficulty,
            "selected_option": request.selected_option,
            "correct_option": correct_option,
            "correct": is_correct,
            "updated_ability": profile.ability,
            "updated_mastery": profile.topic_mastery[topic],
        }
    )

    if not is_correct:
        background_tasks.add_task(_refine_mistake, attempt_id, question, selected, correct_option, difficulty)

    return QuizSubmitResponse(
        correct=is_correct,
        correct_option=correct_option,
        updated_ability=profile.ability,
        updated_mastery=profile.topic_mastery[topic],
        next_topic=adaptive_engine.next_topic(profile),
        explanation=question.get("explanation", "Answer recorded and mastery updated."),
    )


async def _refine_mistake(attempt_id: str, question: dict, selected: str, correct: str, difficulty: str) -> None:
    """Ask an AI model (via the LLM router) what kind of mistake this was; store its label and reason."""
    result = await classify_with_gemini(question, selected, correct, difficulty)
    if not result:
        return
    try:
        await database.update_quiz_attempt(attempt_id, {
            "mistake_type": result["type"],
            "mistake_reason": result["reason"],
            "mistake_source": result.get("provider", "ai"),
        })
        logger.info("Mistake %s classified by %s as %s", attempt_id, result.get("provider"), result["type"])
    except Exception:
        logger.exception("Could not save AI mistake label for %s", attempt_id)


@router.get("/history/{user_id}", response_model=QuizHistoryResponse)
async def get_quiz_history(
    user_id: str,
    current_user: dict = Depends(get_current_user),
) -> QuizHistoryResponse:
    if user_id != current_user["id"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot access another user's quiz history")
    attempts = await database.get_quiz_attempts(user_id)
    return QuizHistoryResponse(
        user_id=user_id,
        total=len(attempts),
        attempts=[QuizAttempt(**attempt) for attempt in attempts],
    )
