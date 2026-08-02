import asyncio
import uuid
from datetime import datetime
from typing import Dict, Optional

from app.models.schemas import GenerateRequest, JobState, JobStatus
from app.services.cache_manager import cache_manager
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

    async def create_job(self, request: GenerateRequest, student_id: str) -> JobState:
        job_id = str(uuid.uuid4())
        job = JobState(
            job_id=job_id,
            status=JobStatus.queued,
            topic=request.topic,
            subject=request.subject,
            class_level=request.class_level,
            student_id=student_id,
        )
        self.jobs[job_id] = job
        return job

    def get_job(self, job_id: str) -> Optional[JobState]:
        return self.jobs.get(job_id)

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

            cache_key = cache_manager.build_cache_key(job.topic, job.subject, job.class_level)
            await cache_manager.save_cached_video(
                cache_key,
                {
                    "topic": job.topic,
                    "subject": job.subject,
                    "class_level": job.class_level,
                    "video_url": video_url,
                    "job_id": job.job_id,
                },
            )
            await self._set_progress(job, 100, "complete", "Video is ready", JobStatus.completed)
            await cache_manager.save_video_record(
                {
                    "job_id": job.job_id,
                    "topic": job.topic,
                    "subject": job.subject,
                    "class_level": job.class_level,
                    "video_url": video_url,
                    "local_video_path": local_path,
                    "student_id": job.student_id,
                    "status": job.status.value,
                    "progress": job.progress,
                    "stage": job.stage,
                    "message": job.message,
                }
            )
        except Exception as exc:
            job.error = str(exc)
            await self._set_progress(job, job.progress, "failed", "Generation failed", JobStatus.failed)


job_queue = JobQueue()
