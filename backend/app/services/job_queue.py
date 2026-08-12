import asyncio
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

from app.models.schemas import GenerateRequest, JobState, JobStatus
from app.services.database import database
from app.services.storage import video_storage
from app.services.websocket_manager import websocket_manager


GENERATION_STAGES = [
    (5, "initializing", "Starting generation"),
    (15, "retrieving", "Finding relevant textbook context"),
    (30, "scripting", "Preparing explanation script"),
    (45, "segmenting", "Breaking content into scenes"),
    (60, "audio", "Generating narration"),
    (78, "rendering", "Rendering video visuals"),
    (92, "uploading", "Uploading video"),
    (100, "complete", "Video is ready"),
]


class JobQueue:
    def __init__(self) -> None:
        self.jobs: Dict[str, JobState] = {}

    async def create_job(self, request: GenerateRequest, user_id: str) -> JobState:
        job_id = str(uuid.uuid4())
        job = JobState(
            job_id=job_id,
            status=JobStatus.queued,
            topic=request.topic,
            subject=request.subject,
            class_level=request.class_level,
            user_id=user_id,
        )
        self.jobs[job_id] = job
        await database.save_video_record(self._record_from_job(job))
        return job

    def get_job(self, job_id: str) -> Optional[JobState]:
        return self.jobs.get(job_id)

    def _record_from_job(self, job: JobState) -> dict:
        return {
            "job_id": job.job_id,
            "topic": job.topic,
            "subject": job.subject,
            "class_level": job.class_level,
            "user_id": job.user_id,
            "video_url": job.video_url,
            "local_video_path": job.local_video_path,
            "local_filename": Path(job.local_video_path).name if job.local_video_path else None,
            "status": job.status.value,
            "progress": job.progress,
            "stage": job.stage,
            "message": job.message,
            "error": job.error,
            "created_at": job.created_at,
            "updated_at": job.updated_at,
        }

    async def _set_progress(
        self,
        job: JobState,
        progress: int,
        stage: str,
        message: str,
        status: JobStatus = JobStatus.running,
    ) -> None:
        job.progress = progress
        job.stage = stage
        job.message = message
        job.status = status
        job.updated_at = datetime.utcnow()
        await database.save_video_record(self._record_from_job(job))
        await websocket_manager.broadcast(job.job_id, job.model_dump(mode="json"))

    async def run_generation(self, job_id: str) -> None:
        job = self.jobs[job_id]
        try:
            for progress, stage, message in GENERATION_STAGES[:-1]:
                await self._set_progress(job, progress, stage, message)
                await asyncio.sleep(video_storage.settings.generation_mock_delay_seconds)

            local_path = video_storage.create_placeholder_video(job.job_id, job.topic)
            video_url = await video_storage.upload_video(local_path, public_id=job.job_id)
            job.video_url = video_url
            job.local_video_path = local_path

            await self._set_progress(job, 100, "complete", "Video is ready", JobStatus.completed)
        except Exception as exc:
            job.error = str(exc)
            await self._set_progress(job, job.progress, "failed", "Generation failed", JobStatus.failed)


job_queue = JobQueue()
