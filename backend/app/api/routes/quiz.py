from fastapi import APIRouter, Depends, HTTPException, status

from app.models.schemas import QuizAttempt, QuizHistoryResponse, QuizSubmitRequest, QuizSubmitResponse
from app.services.adaptive_engine import adaptive_engine
from app.services.auth_service import get_current_user
from app.services.database import database

router = APIRouter(prefix="/quiz", tags=["quiz"])


@router.post("/submit", response_model=QuizSubmitResponse)
async def submit_quiz_answer(
    request: QuizSubmitRequest,
    current_user: dict = Depends(get_current_user),
) -> QuizSubmitResponse:
    user_id = current_user["id"]
    question = await database.get_quiz_question(request.question_id)
    if not question:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Quiz question not found")

    profile = adaptive_engine.from_dict(current_user, user_id)
    correct_option = str(question["correct_option"]).upper()
    is_correct = request.selected_option.upper() == correct_option
    topic = question["topic"]
    difficulty = question.get("difficulty", "MEDIUM")
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

    await database.save_quiz_attempt(
        {
            "attempt_id": f"{user_id}:{request.question_id}",
            "user_id": user_id,
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

    return QuizSubmitResponse(
        correct=is_correct,
        updated_ability=profile.ability,
        updated_mastery=profile.topic_mastery[topic],
        next_topic=adaptive_engine.next_topic(profile),
        explanation=question.get("explanation", "Answer recorded and mastery updated."),
    )


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
