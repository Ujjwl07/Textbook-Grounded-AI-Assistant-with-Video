import asyncio
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.services.auth_service import get_current_user, get_user_from_token
from app.services.database import database
from app.services.job_queue import job_queue
from app.llm.llm_router import AllProvidersFailedError, LLMRequestError, acall_llm, parse_json
from app.rag.retriever import retriever

router = APIRouter(tags=["videos"])


LESSON_FIELDS = (
    "job_id", "video_url", "topic", "subject", "class_level", "duration_seconds", "orientation",
    "scene_parts", "scene_titles", "sources", "source_label", "resolved_subject",
    "resolved_class_level", "chapter_number", "chapter_name", "timeline", "scene_source", "created_at",
)


async def _owned_lesson(job_id: str, current_user: dict) -> dict:
    """The finished video ``job_id`` as a dict, if it belongs to the caller."""
    job = job_queue.get_job(job_id)
    if job and job.video_url:
        data = job.model_dump(mode="json")
    else:
        data = await database.get_video_record(job_id)
        if not data or not data.get("video_url"):
            raise HTTPException(status_code=404, detail="Video not found")
    if data.get("user_id") != current_user["id"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot access another user's video")
    return data


@router.get("/video/{job_id}")
async def get_video(job_id: str, current_user: dict = Depends(get_current_user)) -> dict:
    data = await _owned_lesson(job_id, current_user)
    lesson = {key: data.get(key) for key in LESSON_FIELDS}
    lesson["duration_seconds"] = lesson["duration_seconds"] or 60
    lesson["orientation"] = lesson["orientation"] or "landscape"
    for key in ("scene_parts", "scene_titles", "sources", "timeline"):
        lesson[key] = lesson[key] or []
    # Flashcards are generated on request and cached on the video record.
    record = data if "flashcards" in data else (await database.get_video_record(job_id) or {})
    lesson["flashcards"] = record.get("flashcards") or []
    progress = await database.get_lesson_progress(current_user["id"], job_id)
    lesson["progress"] = {
        "completed": bool(progress.get("completed")),
        "saved": bool(progress.get("saved")),
        "notes": progress.get("notes") or "",
    }
    return lesson


class LessonProgressUpdate(BaseModel):
    completed: Optional[bool] = None
    saved: Optional[bool] = None
    notes: Optional[str] = Field(default=None, max_length=20000)


@router.put("/video/{job_id}/progress")
async def update_lesson_progress(
    job_id: str, body: LessonProgressUpdate, current_user: dict = Depends(get_current_user)
) -> dict:
    """Mark a lesson complete, save it, or store the student's notes on it."""
    await _owned_lesson(job_id, current_user)
    fields = body.model_dump(exclude_none=True)
    if "completed" in fields:
        fields["completed_at"] = datetime.utcnow() if fields["completed"] else None
    if not fields:
        raise HTTPException(status_code=400, detail="Nothing to update")
    doc = await database.update_lesson_progress(current_user["id"], job_id, fields)
    return {
        "completed": bool(doc.get("completed")),
        "saved": bool(doc.get("saved")),
        "notes": doc.get("notes") or "",
    }


FLASHCARD_SYSTEM = (
    "You write revision flashcards for Indian NEET students from NCERT textbook material. "
    "Use only facts present in the material you are given."
)


@router.post("/video/{job_id}/flashcards")
async def lesson_flashcards(
    job_id: str, refresh: bool = Query(default=False), current_user: dict = Depends(get_current_user)
) -> dict:
    """Flashcards for a lesson, written from its narration (or the textbook) and cached."""
    data = await _owned_lesson(job_id, current_user)
    record = await database.get_video_record(job_id) or {}
    if record.get("flashcards") and not refresh:
        return {"cards": record["flashcards"], "cached": True}

    subject = data.get("resolved_subject") or data.get("subject")
    class_level = data.get("resolved_class_level") or data.get("class_level")
    material = "\n\n".join(
        f"{scene.get('title', '')}: {scene.get('text', '')}" for scene in data.get("timeline") or []
    ).strip()
    if not material:
        # Older videos kept no narration: use the textbook passages instead.
        result = await asyncio.to_thread(
            retriever.retrieve, query=data.get("topic") or "", top_k=6,
            subject=subject, class_level=class_level, caller=f"Flashcards:{job_id[:8]}",
        )
        material = result.context_text or ""
    if not material:
        raise HTTPException(status_code=422, detail="No textbook material found for this lesson")

    prompt = (
        f"Topic: {data.get('topic')} (Class {class_level or ''} {subject or ''})\n\n"
        f"MATERIAL:\n{material[:9000]}\n\n"
        "Write 8 flashcards that test the key facts, definitions, formulas and NEET traps in this material. "
        'Reply with JSON only: {"cards": [{"front": "short question", "back": "concise answer (max 40 words)"}]}'
    )
    try:
        text, _provider = await acall_llm("flashcards", prompt, system=FLASHCARD_SYSTEM, json_mode=True, max_tokens=1500)
        parsed = parse_json(text)
    except (AllProvidersFailedError, LLMRequestError, ValueError) as exc:
        raise HTTPException(status_code=503, detail=f"Couldn't write flashcards right now: {exc}")
    raw = parsed.get("cards", []) if isinstance(parsed, dict) else parsed
    cards = [
        {"front": str(c.get("front", "")).strip()[:300], "back": str(c.get("back", "")).strip()[:600]}
        for c in raw or [] if isinstance(c, dict) and c.get("front") and c.get("back")
    ][:12]
    if not cards:
        raise HTTPException(status_code=503, detail="The AI returned no usable flashcards; try again")
    await database.update_video_record(job_id, {"flashcards": cards})
    return {"cards": cards, "cached": False}


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
    download: bool = Query(default=False),
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
    response = _range_response(file_path, range_header)
    if download:
        name = re.sub(r"[^A-Za-z0-9 _-]+", "", record.get("topic") or "lesson").strip() or "lesson"
        response.headers["Content-Disposition"] = f'attachment; filename="{name[:80]}.mp4"'
    return response


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
