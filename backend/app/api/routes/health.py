from fastapi import APIRouter

from app.core.config import get_settings
from app.services.database import database

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check() -> dict:
    settings = get_settings()
    return {
        "status": "ok",
        "app": settings.app_name,
        "version": settings.app_version,
        "database_connected": database.enabled,
        "cloudinary_enabled": settings.cloudinary_enabled,
    }
