from fastapi import APIRouter

from app.core.config import get_settings
from app.services.cache_manager import cache_manager

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check() -> dict:
    settings = get_settings()
    return {
        "status": "ok",
        "app": settings.app_name,
        "version": settings.app_version,
        "database_connected": cache_manager.enabled,
        "cloudinary_enabled": settings.cloudinary_enabled,
    }
