from fastapi import APIRouter, Depends, HTTPException, status

from app.models.schemas import QuizHistoryResponse, QuizSubmitRequest, QuizSubmitResponse, QuizAttempt
from app.services.adaptive_engine import adaptive_engine
from app.services.auth_service import get_current_user
from app.services.cache_manager import cache_manager

router = APIRouter(prefix="/quiz", tags=["quiz"])


@router.post("/submit", response_model=QuizSubmitResponse)
async def submit_quiz_answer(
    request: QuizSubmitRequest,
    current_user: dict = Depends(get_current_user),
) -> QuizSubmitResponse:
    student_id = current_user["id"]
    if request.student_id != student_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot submit quiz for another student")
    stored_profile = await cache_manager.get_student(student_id)
    profile = adaptive_engine.from_dict(stored_profile, student_id)
    is_correct = request.selected_option.upper() == request.correct_option.upper()
    profile = adaptive_engine.update_after_answer(
        profile=profile,
        topic=request.topic,
        difficulty=request.difficulty,
        is_correct=is_correct,
        question_id=request.question_id,
    )
    await cache_manager.save_student(adaptive_engine.to_dict(profile))
    await cache_manager.save_quiz_attempt(
        {
            "attempt_id": f"{student_id}:{request.question_id}:{request.topic}",
            "student_id": student_id,
            "question_id": request.question_id,
            "topic": request.topic,
            "difficulty": request.difficulty,
            "selected_option": request.selected_option,
            "correct_option": request.correct_option,
            "correct": is_correct,
            "updated_ability": profile.ability,
            "updated_mastery": profile.topic_mastery[request.topic],
        }
    )

    return QuizSubmitResponse(
        correct=is_correct,
        updated_ability=profile.ability,
        updated_mastery=profile.topic_mastery[request.topic],
        next_topic=adaptive_engine.next_topic(profile),
        explanation="Answer recorded and mastery updated.",
    )


@router.get("/history/{student_id}", response_model=QuizHistoryResponse)
async def get_quiz_history(
    student_id: str,
    current_user: dict = Depends(get_current_user),
) -> QuizHistoryResponse:
    if student_id != current_user["id"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot access another user's quiz history")
    attempts = await cache_manager.get_quiz_attempts(student_id)
    return QuizHistoryResponse(
        student_id=student_id,
        total=len(attempts),
        attempts=[QuizAttempt(**attempt) for attempt in attempts],
    )
