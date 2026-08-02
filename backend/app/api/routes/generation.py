from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, WebSocket, WebSocketDisconnect

from app.models.schemas import GenerateRequest, GenerateResponse, JobStatus
from app.services.auth_service import get_current_user
from app.services.cache_manager import cache_manager
from app.services.job_queue import job_queue
from app.services.websocket_manager import websocket_manager

router = APIRouter(tags=["generation"])


@router.post("/generate", response_model=GenerateResponse)
async def generate_video(
    request: GenerateRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
) -> GenerateResponse:
    cache_key = cache_manager.build_cache_key(request.topic, request.subject, request.class_level)
    cached = await cache_manager.get_cached_video(cache_key)
    if cached:
        await cache_manager.save_video_record(
            {
                "job_id": cached.get("job_id", cache_key),
                "topic": cached["topic"],
                "subject": cached.get("subject"),
                "class_level": cached.get("class_level"),
                "video_url": cached["video_url"],
                "student_id": current_user["id"],
                "status": JobStatus.completed.value,
            }
        )
        return GenerateResponse(
            job_id=cached.get("job_id", cache_key),
            status=JobStatus.completed,
            cached=True,
            video_url=cached["video_url"],
            message="Returned cached video",
        )

    job = await job_queue.create_job(request, student_id=current_user["id"])
    background_tasks.add_task(job_queue.run_generation, job.job_id)
    return GenerateResponse(
        job_id=job.job_id,
        status=job.status,
        cached=False,
        message="Generation job queued",
    )


@router.get("/status/{job_id}")
async def get_generation_status(job_id: str) -> dict:
    job = job_queue.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job.model_dump(mode="json")


@router.websocket("/ws/{job_id}")
async def generation_websocket(websocket: WebSocket, job_id: str) -> None:
    await websocket_manager.connect(job_id, websocket)
    try:
        job = job_queue.get_job(job_id)
        if job:
            await websocket.send_json(job.model_dump(mode="json"))
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        websocket_manager.disconnect(job_id, websocket)
