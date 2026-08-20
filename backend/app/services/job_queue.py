import asyncio
import uuid
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

from app.models.schemas import GenerateRequest, JobState, JobStatus
from app.rag.retriever import retriever
from app.llm.gemini_service import gemini_service
from app.services.database import database
from app.services.storage import video_storage
from app.services.websocket_manager import websocket_manager
from app.tts.tts_generator import TTSGenerator
from app.video.slide_generator import SlideRenderer
from app.video.video_assembler import VideoAssembler

logger = logging.getLogger(__name__)

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
        # Instantiate TTS and Slide Renderers
        self.tts = TTSGenerator()
        self.slide_renderer = SlideRenderer()
        self.assembler = VideoAssembler(self.tts, self.slide_renderer)

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
            # 1. Initialization stage (5%)
            await self._set_progress(job, 5, "initializing", "Initializing generation engines")
            await asyncio.sleep(0.5)

            # 2. Retrieval stage (15%)
            await self._set_progress(job, 15, "retrieving", "Searching NCERT textbook context")
            retrieval_res = retriever.retrieve(
                query=job.topic,
                subject=job.subject,
                class_level=job.class_level,
                caller=f"JobQueue:{job.job_id[:8]}",
                log_to_file=True,
            )
            retrieved_context = retrieval_res.context_text
            logger.info(
                f"Job {job.job_id}: Extracted {retrieval_res.total_chunks} chunks for topic '{job.topic}' "
                f"(logged to {retrieval_res.log_file_path})"
            )
            await asyncio.sleep(0.3)
            
            # 3. Scripting stage (30%)
            await self._set_progress(job, 30, "scripting", "Generating curriculum-grounded script via Gemini")
            
            # 4. Segmentation stage (45%)
            await self._set_progress(job, 45, "segmenting", "Segmenting script into educational scenes")
            scenes = await gemini_service.generate_educational_scenes(
                topic=job.topic,
                subject=job.subject,
                class_level=job.class_level,
                retrieved_context=retrieved_context,
            )

            # 5. Audio and Video Assembly stages (60% to 92%)
            await self._set_progress(job, 60, "audio", "Synthesizing vocal narration and rendering slide templates")
            
            local_path = str(video_storage.settings.video_output_dir / f"{job.job_id}.mp4")
            
            # Generate the video (takes care of TTS, slide drawing, Ken Burns, Karaoke subtitles)
            await self.assembler.assemble_full_video(scenes, job.subject, local_path)
            
            # 6. Upload stage (92%)
            await self._set_progress(job, 92, "uploading", "Uploading final video clip to storage")
            video_url = await video_storage.upload_video(local_path, public_id=job.job_id)
            
            job.video_url = video_url
            job.local_video_path = local_path

            await self._set_progress(job, 100, "complete", "Video is ready", JobStatus.completed)
        except Exception as exc:
            logger.exception("Video generation job failed")
            job.error = str(exc)
            await self._set_progress(job, job.progress, "failed", f"Generation failed: {str(exc)}", JobStatus.failed)


job_queue = JobQueue()
