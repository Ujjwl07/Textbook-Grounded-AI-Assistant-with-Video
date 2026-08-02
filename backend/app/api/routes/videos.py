from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.core.config import get_settings
from app.services.cache_manager import cache_manager
from app.services.job_queue import job_queue

router = APIRouter(tags=["videos"])


@router.get("/video/{job_id}")
async def get_video(job_id: str) -> dict:
    job = job_queue.get_job(job_id)
    if job and job.video_url:
        return {
            "job_id": job.job_id,
            "video_url": job.video_url,
            "topic": job.topic,
            "subject": job.subject,
            "class_level": job.class_level,
        }

    record = await cache_manager.get_video_record(job_id)
    if not record:
        raise HTTPException(status_code=404, detail="Video not found")
    return {
        "job_id": record["job_id"],
        "video_url": record["video_url"],
        "topic": record.get("topic"),
        "subject": record.get("subject"),
        "class_level": record.get("class_level"),
    }


@router.get("/video-file/{filename}")
async def get_local_video_file(filename: str) -> FileResponse:
    settings = get_settings()
    file_path = settings.video_output_dir / Path(filename).name
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(file_path)
