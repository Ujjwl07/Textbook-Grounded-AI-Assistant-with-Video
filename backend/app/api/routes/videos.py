from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from fastapi.responses import StreamingResponse

from app.core.config import get_settings
from app.services.auth_service import get_current_user, get_user_from_token
from app.services.database import database
from app.services.job_queue import job_queue

router = APIRouter(tags=["videos"])


@router.get("/video/{job_id}")
async def get_video(job_id: str, current_user: dict = Depends(get_current_user)) -> dict:
    job = job_queue.get_job(job_id)
    if job and job.video_url:
        if job.user_id != current_user["id"]:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot access another user's video")
        return {
            "job_id": job.job_id,
            "video_url": job.video_url,
            "topic": job.topic,
            "subject": job.subject,
            "class_level": job.class_level,
        }

    record = await database.get_video_record(job_id)
    if not record:
        raise HTTPException(status_code=404, detail="Video not found")
    if record.get("user_id") != current_user["id"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot access another user's video")
    return {
        "job_id": record["job_id"],
        "video_url": record["video_url"],
        "topic": record.get("topic"),
        "subject": record.get("subject"),
        "class_level": record.get("class_level"),
    }


@router.get("/videos")
async def list_my_videos(current_user: dict = Depends(get_current_user)) -> dict:
    videos = await database.list_user_videos(current_user["id"])
    return {"total": len(videos), "videos": videos}


@router.get("/video-file/{filename}")
async def stream_local_video_file(
    filename: str,
    range_header: str | None = Header(default=None, alias="Range"),
    authorization: str | None = Header(default=None, alias="Authorization"),
    token: str | None = Query(default=None),
) -> StreamingResponse:
    current_user = await _authenticate_stream_request(authorization, token)
    record = await database.get_video_by_filename(Path(filename).name)
    if not record:
        raise HTTPException(status_code=404, detail="Video not found")
    if record.get("user_id") != current_user["id"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot access another user's video")

    settings = get_settings()
    file_path = settings.video_output_dir / Path(filename).name
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return _range_response(file_path, range_header)


async def _authenticate_stream_request(authorization: str | None, token: str | None) -> dict:
    bearer_token = token
    if authorization and authorization.lower().startswith("bearer "):
        bearer_token = authorization.split(" ", 1)[1]
    if not bearer_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing access token")
    return await get_user_from_token(bearer_token)


def _range_response(file_path: Path, range_header: str | None) -> StreamingResponse:
    file_size = file_path.stat().st_size
    start = 0
    end = file_size - 1
    status_code = status.HTTP_200_OK
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(file_size),
        "Content-Type": _media_type(file_path),
    }

    if range_header:
        unit, _, byte_range = range_header.partition("=")
        if unit.strip().lower() != "bytes":
            raise HTTPException(status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE, detail="Invalid range")
        start_text, _, end_text = byte_range.partition("-")
        start = int(start_text) if start_text else 0
        end = int(end_text) if end_text else file_size - 1
        if start > end or start < 0 or end >= file_size:
            raise HTTPException(status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE, detail="Invalid range")
        status_code = status.HTTP_206_PARTIAL_CONTENT
        headers["Content-Range"] = f"bytes {start}-{end}/{file_size}"
        headers["Content-Length"] = str(end - start + 1)

    def iter_file():
        with file_path.open("rb") as video:
            video.seek(start)
            remaining = end - start + 1
            chunk_size = 1024 * 1024
            while remaining > 0:
                chunk = video.read(min(chunk_size, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk

    return StreamingResponse(iter_file(), status_code=status_code, headers=headers, media_type=headers["Content-Type"])


def _media_type(file_path: Path) -> str:
    suffix = file_path.suffix.lower()
    if suffix == ".mp4":
        return "video/mp4"
    if suffix == ".webm":
        return "video/webm"
    if suffix == ".mov":
        return "video/quicktime"
    return "application/octet-stream"
