from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, WebSocket, WebSocketDisconnect

from app.models.schemas import GenerateRequest, GenerateResponse, JobStatus
from app.services.auth_service import get_current_user, get_user_from_token
from app.services.database import database
from app.services.job_queue import job_queue
from app.services.websocket_manager import websocket_manager

router = APIRouter(tags=["generation"])


@router.post("/generate", response_model=GenerateResponse)
async def generate_video(
    request: GenerateRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
) -> GenerateResponse:
    job = await job_queue.create_job(request, user_id=current_user["id"])
    background_tasks.add_task(job_queue.run_generation, job.job_id)
    return GenerateResponse(
        job_id=job.job_id,
        status=job.status,
        message="Generation job queued",
    )


@router.get("/status/{job_id}")
async def get_generation_status(job_id: str, current_user: dict = Depends(get_current_user)) -> dict:
    job = job_queue.get_job(job_id)
    if job:
        if job.user_id != current_user["id"]:
            raise HTTPException(status_code=403, detail="Cannot access another user's job")
        return job.model_dump(mode="json")

    record = await database.get_video_record(job_id)
    if not record:
        raise HTTPException(status_code=404, detail="Job not found")
    if record.get("user_id") != current_user["id"]:
        raise HTTPException(status_code=403, detail="Cannot access another user's job")
    return record


@router.websocket("/ws/{job_id}")
async def generation_websocket(websocket: WebSocket, job_id: str) -> None:
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=1008)
        return
    try:
        current_user = await get_user_from_token(token)
    except HTTPException:
        await websocket.close(code=1008)
        return

    job = job_queue.get_job(job_id)
    record = None if job else await database.get_video_record(job_id)
    owner_id = job.user_id if job else record.get("user_id") if record else None
    if owner_id != current_user["id"]:
        await websocket.close(code=1008)
        return

    await websocket_manager.connect(job_id, websocket)
    try:
        if job:
            await websocket.send_json(job.model_dump(mode="json"))
        elif record:
            await websocket.send_json(record)
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        websocket_manager.disconnect(job_id, websocket)
