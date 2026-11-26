import re
import asyncio
import uuid
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

from app.models.schemas import GenerateRequest, JobState, JobStatus
from app.rag.scene_builder import build_scenes
from app.rag.retriever import retriever
from app.llm.gemini_service import GeminiUnavailable, describe_gemini_failure, gemini_service
from app.llm.llm_router import AllProvidersFailedError
from app.services.database import database
from app.services.storage import video_storage
from app.services.websocket_manager import websocket_manager
from app.tts.tts_generator import TTSGenerator
from app.video.slide_generator import SlideRenderer
from app.video.video_assembler import VideoAssembler

logger = logging.getLogger(__name__)


class TopicNotInCorpus(Exception):
    """The requested topic is not in the indexed textbooks.

    Distinct from a generation failure: nothing is broken, the corpus simply
    does not cover what was asked for, and the student needs different wording
    rather than a retry.
    """


def _not_found_message(topic: str) -> str:
    return (
        f"“{topic}” was not found in the indexed NCERT textbooks. "
        "Try a Class 11 or 12 Physics, Chemistry or Biology topic — for "
        "example “Photosynthesis”, “Ray Optics” or "
        "“Chemical Kinetics”."
    )

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
        self._locks: dict = {}
        # Database writes per job run in order, and a write built from an older
        # state is dropped: a late "encoding" update used to land after
        # "complete" and leave the saved record stuck at running.
        self._save_locks: dict = {}
        self._saved_at: dict = {}
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
            duration_seconds=request.duration_seconds,
            orientation=request.orientation,
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
            "scene_source": job.scene_source,
            "duration_seconds": job.duration_seconds,
            "orientation": job.orientation,
            "step": job.step,
            "step_times": job.step_times,
            "scene_parts": job.scene_parts,
            "scene_titles": job.scene_titles,
            "scenes_done": job.scenes_done,
            "sources": job.sources,
            "source_label": job.source_label,
            "resolved_subject": job.resolved_subject,
            "resolved_class_level": job.resolved_class_level,
            "chapter_number": job.chapter_number,
            "chapter_name": job.chapter_name,
            "timeline": job.timeline,
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
        logger.info(
            "Job %s [%s%%] %s: %s (%s)",
            job.job_id[:8], progress, stage, message, status.value if hasattr(status, "value") else status,
        )
        job.progress = progress
        job.stage = stage
        job.message = message
        job.status = status
        job.updated_at = datetime.utcnow()
        await self._save(job)
        await websocket_manager.broadcast(job.job_id, job.model_dump(mode="json"))

    async def _save(self, job: JobState) -> None:
        record = self._record_from_job(job)
        stamp = job.updated_at
        async with self._save_locks.setdefault(job.job_id, asyncio.Lock()):
            last = self._saved_at.get(job.job_id)
            if last and stamp < last:
                return
            await database.save_video_record(record)
            self._saved_at[job.job_id] = stamp

    # The five steps the "Generating" page shows, with the progress range each
    # one covers and the stage name stored on the job.
    STEPS = {
        "retrieve": (2, 20, "retrieving"),
        "script": (20, 46, "scripting"),
        "narrate": (46, 66, "narrating"),
        "render": (66, 72, "rendering"),
        "encode": (72, 97, "encoding"),
    }
    STEP_ORDER = list(STEPS)

    def _close_step(self, job: JobState) -> None:
        """Record how long the current step took."""
        if job.step and job.step_started_at:
            job.step_times[job.step] = round((datetime.utcnow() - job.step_started_at).total_seconds(), 1)

    async def _step(self, job: JobState, step: str, message: str) -> None:
        """Finish the current step and start ``step``."""
        self._close_step(job)
        job.step = step
        job.step_started_at = datetime.utcnow()
        start, _end, stage = self.STEPS[step]
        await self._set_progress(job, max(job.progress, start), stage, message)

    async def _assembler_progress(self, job: JobState, step: str, done: int, total: int, message: str) -> None:
        """Turn the assembler's narrate/render/encode reports into job progress."""
        lock = self._locks.setdefault(job.job_id, asyncio.Lock())
        async with lock:
            if job.status != JobStatus.running or step not in self.STEPS:
                return
            # Updates can arrive late from the encode thread: never go backwards.
            if job.step in self.STEP_ORDER and self.STEP_ORDER.index(step) < self.STEP_ORDER.index(job.step):
                return
            if step != job.step:
                self._close_step(job)
                job.step = step
                job.step_started_at = datetime.utcnow()
            start, end, stage = self.STEPS[step]
            progress = start + int((end - start) * (done / total if total else 0))
            if step == "narrate":
                job.scenes_done = done
            await self._set_progress(job, max(job.progress, progress), stage, message)

    def _progress_reporter(self, job: JobState):
        """A thread-safe on_progress callback for the assembler."""
        loop = asyncio.get_running_loop()

        def report(step, done, total, message):
            loop.call_soon_threadsafe(
                lambda: asyncio.ensure_future(self._assembler_progress(job, step, done, total, message))
            )

        return report

    async def _build_scenes(self, job: JobState, subject, class_level, context) -> tuple:
        """Scenes for ``job``, and the name of the stage that produced them.

        Gemini writes the script when it can. When it is overloaded — the API
        answers 503 for minutes at a time under load, and generate_text already
        retries with backoff before giving up — the video is still assembled,
        from passages retrieved out of the textbook rather than from nothing.

        That fallback is quoted NCERT prose, so it is grounded; what it is not
        is a written script. The distinction is recorded on the job and returned
        by the status endpoint, because a fallback nobody can see is exactly the
        silent fallback this pipeline removed.
        """
        # One job-level attempt: the LLM router already falls back across
        # Gemini -> Groq -> OpenRouter, so retrying here would only repeat that.
        try:
            scenes, provider = await gemini_service.generate_educational_scenes_with_provider(
                topic=job.topic,
                subject=subject,
                class_level=class_level,
                retrieved_context=context,
                target_seconds=job.duration_seconds,
            )
            logger.info("Job %s: the script was written by %s", job.job_id[:8], provider)
            return scenes, provider
        except (GeminiUnavailable, AllProvidersFailedError) as exc:
            logger.warning(
                "Job %s: AI status: %s - assembling scenes from the textbook passages instead",
                job.job_id[:8], describe_gemini_failure(exc),
            )
        except Exception as exc:
            # A bad key or a malformed prompt is a real defect. Retrieval can
            # still carry this one video, but the traceback must be recorded.
            logger.error(
                "Job %s: AI status: %s - assembling scenes from the textbook passages instead",
                job.job_id[:8], describe_gemini_failure(exc),
            )
            logger.exception("Job %s: AI scene generation failed", job.job_id)

        try:
            scenes = build_scenes(job.topic, subject, class_level)
        except Exception:
            logger.exception("Job %s: retrieval-grounded scene build failed", job.job_id)
            scenes = None
        if scenes:
            return scenes, "retrieval"

        # No hand-written presets here any more. They exist to exercise the
        # renderer, and their content is generic physics: a Biology topic that
        # reached them was taught "F = ma" under a heading claiming to quote
        # NCERT. Failing is the honest outcome, and the caller turns this into
        # a message the student can act on.
        raise TopicNotInCorpus(
            f"No usable textbook passages were found for '{job.topic}'."
        )

    async def run_generation(self, job_id: str) -> None:
        job = self.jobs[job_id]
        try:
            # 1. Retrieve: search the NCERT corpus. On a worker thread so the
            # embedding model does not stall other requests and live updates.
            await self._step(job, "retrieve", "Searching the NCERT textbook corpus")
            retrieval_res = await asyncio.to_thread(
                retriever.retrieve,
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

            # Subject and class may have been left out by the client or set
            # wrongly; retrieval resolves them against the corpus. Both the
            # prompt and the narration voice need the resolved values, not the
            # requested ones.
            applied = retrieval_res.filters_applied
            subject = applied.get("resolved_subject") or job.subject
            class_level = applied.get("resolved_class_level") or job.class_level
            job.resolved_subject = subject
            job.resolved_class_level = class_level
            job.sources, job.source_label, job.chapter_number, job.chapter_name = _sources_from(
                retrieval_res.chunks, subject, class_level
            )

            # Checked before the LLM, not after: the retrieved chunks are always
            # *something*, and the model would write a confident lesson out of a
            # chapter that has nothing to do with the question.
            if not applied.get("topic_matched", True):
                logger.info(
                    "Job %s: %r did not match the corpus (best score %.3f)",
                    job.job_id, job.topic, applied.get("match_score", 0.0),
                )
                self._close_step(job)
                job.scene_source = "none"
                job.error = _not_found_message(job.topic)
                await self._set_progress(
                    job, job.progress, "topic_not_found", job.error, JobStatus.failed
                )
                return

            # 2. Script: the AI writes the scenes (with provider fallback).
            n_passages = len(job.sources)
            await self._step(job, "script", f"Writing the storyboard from {n_passages} textbook passage{'s' if n_passages != 1 else ''}")
            scenes, job.scene_source = await self._build_scenes(
                job, subject, class_level, retrieved_context
            )
            job.scene_parts = [str(sc.get("part", "")) for sc in scenes]
            job.scene_titles = [str(sc.get("slide_title", "")) for sc in scenes]

            # Stamp the resolved scope on every scene. The renderer tints
            # backgrounds by subject and the assembler picks the narration voice
            # from it, and the model is not asked to echo it back.
            for scene in scenes:
                scene.setdefault("subject", (subject or "physics").lower())
                scene.setdefault("class_level", class_level or "")

            # 3-5. Narrate, render and encode, reported live by the assembler.
            await self._step(job, "narrate", f"Narrating {len(scenes)} scenes")
            local_path = str(video_storage.settings.video_output_dir / f"{job.job_id}.mp4")
            # Narrate in the voice of the subject the topic actually belongs to,
            # which may have been inferred rather than supplied by the client.
            voice_subject = (subject or "physics").lower()
            await self.assembler.assemble_full_video(
                scenes, voice_subject, local_path,
                orientation=job.orientation, short=job.duration_seconds <= 30,
                on_progress=self._progress_reporter(job),
                timeline=job.timeline,
            )
            await asyncio.sleep(0)  # let queued progress updates land first
            async with self._locks.setdefault(job.job_id, asyncio.Lock()):
                self._close_step(job)
                job.step = None

            # 6. Save / upload the finished file.
            await self._set_progress(job, 98, "uploading", "Saving your video")
            video_url = await video_storage.upload_video(local_path, public_id=job.job_id)
            
            job.video_url = video_url
            job.local_video_path = local_path

            await self._set_progress(job, 100, "complete", "Video is ready", JobStatus.completed)
        except TopicNotInCorpus:
            self._close_step(job)
            logger.info("Job %s: no usable passages for %r", job.job_id, job.topic)
            job.scene_source = "none"
            job.error = _not_found_message(job.topic)
            await self._set_progress(
                job, job.progress, "topic_not_found", job.error, JobStatus.failed
            )
        except Exception as exc:
            self._close_step(job)
            logger.exception("Video generation job failed")
            job.error = str(exc)
            await self._set_progress(job, job.progress, "failed", f"Generation failed: {str(exc)}", JobStatus.failed)


def _sources_from(chunks, subject, class_level) -> tuple:
    """The retrieved passages as short labels for the progress page, and the main chapter."""
    from collections import Counter

    sources, seen = [], set()
    for chunk in chunks or []:
        chapter = f"Ch {chunk.chapter_number}" if getattr(chunk, "chapter_number", "") not in ("", None) else "NCERT"
        title = (getattr(chunk, "section", "") or getattr(chunk, "chapter_name", "") or "").strip()
        title = re.sub(r"^[\d.]+\s*", "", title)[:60] or "Textbook passage"
        if (chapter, title) in seen:
            continue
        seen.add((chapter, title))
        sources.append({"chapter": chapter, "title": title})
        if len(sources) >= 8:
            break
    label, number, name = None, None, None
    named = Counter(
        (getattr(c, "chapter_number", ""), getattr(c, "chapter_name", "")) for c in chunks or [] if getattr(c, "chapter_name", "")
    )
    if named:
        (number, name), _ = named.most_common(1)[0]
        subj = (subject or "").title()
        label = f"NCERT Class {class_level} {subj} · Ch. {number} {name}".replace("  ", " ").strip()
        number = str(number) if number not in ("", None) else None
        name = str(name).strip() or None
    return sources, label, number, name


job_queue = JobQueue()
