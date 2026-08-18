import asyncio
import uuid
import logging
from datetime import datetime
from typing import Dict, Optional

from app.models.schemas import GenerateRequest, JobState, JobStatus
from app.services.cache_manager import cache_manager
from app.services.storage import video_storage
from app.services.websocket_manager import websocket_manager
from app.tts.tts_generator import TTSGenerator
from app.video.scene_presets import get_fallback_scenes
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
            # 1. Initialization stage (5%)
            await self._set_progress(job, 5, "initializing", "Initializing generation engines")
            await asyncio.sleep(0.5)

            # 2. Retrieval stage (15%)
            await self._set_progress(job, 15, "retrieving", "Searching NCERT textbook context")
            await asyncio.sleep(0.5)
            
            # 3. Scripting stage (30%)
            await self._set_progress(job, 30, "scripting", "Generating personalization script")
            await asyncio.sleep(0.5)
            
            # 4. Segmentation stage (45%)
            await self._set_progress(job, 45, "segmenting", "Segmenting script into educational scenes")
            await asyncio.sleep(0.5)

            # 5. Audio and Video Assembly stages (60% to 92%)
            await self._set_progress(job, 60, "audio", "Synthesizing vocal narration and rendering slide templates")
            
            # Construct scene input
            # In a fully integrated setting, these would come from RAG retrieval + LLM generation/segmentation.
            # We use our dynamic fallback scenes representing the textbook assistant content.
            scenes = get_fallback_scenes(job.topic, job.subject, job.class_level)
            
            local_path = str(video_storage.settings.video_output_dir / f"{job.job_id}.mp4")
            
            # Generate the video (takes care of TTS, slide drawing, Ken Burns, Karaoke subtitles)
            await self.assembler.assemble_full_video(scenes, job.subject, local_path)
            
            # 6. Upload stage (92%)
            await self._set_progress(job, 92, "uploading", "Uploading final video clip to storage")
            video_url = await video_storage.upload_video(local_path, public_id=job.job_id)
            
            job.video_url = video_url
            job.local_video_path = local_path

            # 7. Complete stage (100%)
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
            await self._set_progress(job, 100, "complete", "Your custom video is ready!", JobStatus.completed)
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
            logger.exception("Video generation job failed")
            job.error = str(exc)
            await self._set_progress(job, job.progress, "failed", f"Generation failed: {str(exc)}", JobStatus.failed)


job_queue = JobQueue()
