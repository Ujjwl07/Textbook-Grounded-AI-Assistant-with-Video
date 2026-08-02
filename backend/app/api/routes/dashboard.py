from fastapi import APIRouter, Depends, HTTPException, status

from app.models.schemas import StudentDashboard
from app.services.adaptive_engine import adaptive_engine
from app.services.auth_service import get_current_user
from app.services.cache_manager import cache_manager

router = APIRouter(tags=["dashboard"])


@router.get("/student/{student_id}/dashboard", response_model=StudentDashboard)
async def get_student_dashboard(
    student_id: str,
    current_user: dict = Depends(get_current_user),
) -> StudentDashboard:
    if student_id != current_user["id"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot access another user's dashboard")
    stored_profile = await cache_manager.get_student(student_id)
    profile = adaptive_engine.from_dict(stored_profile, student_id)
    return StudentDashboard(
        student_id=profile.student_id,
        ability=profile.ability,
        mastery_by_topic=profile.topic_mastery,
        weak_areas=adaptive_engine.weak_topics(profile),
        strong_areas=adaptive_engine.strong_topics(profile),
        videos_watched=profile.videos_watched,
    )
