from fastapi import APIRouter, Depends, HTTPException, status

from app.models.schemas import UserDashboard
from app.services.adaptive_engine import adaptive_engine
from app.services.auth_service import get_current_user

router = APIRouter(tags=["dashboard"])


@router.get("/users/{user_id}/dashboard", response_model=UserDashboard)
async def get_user_dashboard(
    user_id: str,
    current_user: dict = Depends(get_current_user),
) -> UserDashboard:
    if user_id != current_user["id"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot access another user's dashboard")

    profile = adaptive_engine.from_dict(current_user, current_user["id"])
    return UserDashboard(
        user_id=profile.user_id,
        ability=profile.ability,
        mastery_by_topic=profile.topic_mastery,
        weak_areas=adaptive_engine.weak_topics(profile),
        strong_areas=adaptive_engine.strong_topics(profile),
        videos_watched=profile.videos_watched,
    )
