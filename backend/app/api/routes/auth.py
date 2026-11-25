from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status

from app.models.schemas import AdminCreateRequest, UserPublic
from app.services.auth_service import auth_service, get_current_user
from app.services.database import database

# Sign-in and sign-up are handled by Clerk on the frontend; these routes only
# expose the app's own view of the signed-in user.
router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/me", response_model=UserPublic)
async def get_me(current_user: dict = Depends(get_current_user)) -> UserPublic:
    """Return the signed-in user and record today's visit for the daily streak."""
    today = datetime.now(timezone.utc).date()
    last = current_user.get("last_active_date")
    streak = current_user.get("streak_days", 0)
    if last != today.isoformat():
        yesterday = (today - timedelta(days=1)).isoformat()
        streak = streak + 1 if last == yesterday else 1
        updates = {"last_active_date": today.isoformat(), "streak_days": streak}
        await database.update_user(current_user["id"], updates)
        current_user = {**current_user, **updates}
    return auth_service.to_public_user(current_user)


@router.post("/media-token")
async def create_media_token(current_user: dict = Depends(get_current_user)) -> dict:
    """A longer-lived token for <video src=...> streaming, where Clerk's ~60s token is too short."""
    return {"token": auth_service.create_media_token(current_user["id"])}


@router.post("/admins", status_code=201)
async def create_admin(request: AdminCreateRequest, current_user: dict = Depends(get_current_user)):
    if not current_user.get("is_admin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only admins can create new admins")
    await database.add_admin(request.email)
    return {"message": f"Successfully added {request.email} as an admin"}
