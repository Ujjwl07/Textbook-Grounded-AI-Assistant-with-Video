from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Literal

from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"


class GenerateRequest(BaseModel):
    topic: str = Field(..., min_length=2, max_length=160)
    subject: Optional[str] = Field(default=None, max_length=80)
    class_level: Optional[str] = Field(default=None, max_length=40)
    output_mode: str = Field(default="video", pattern="^(video|answer|quiz)$")
    # Target length of the finished video, and its shape: 16:9 or a 9:16 reel.
    duration_seconds: Literal[30, 60, 120, 300] = 60
    orientation: Literal["landscape", "portrait"] = "landscape"
    # Narration (voice) and on-screen caption languages. Captions default to
    # the voice language; a different one makes a bilingual lesson. Hindi and
    # Punjabi go through Sarvam-Translate and the Bulbul v3 voice.
    voice_language: Literal["en-IN", "hi-IN", "pa-IN"] = "en-IN"
    caption_language: Optional[Literal["en-IN", "hi-IN", "pa-IN"]] = None
    pace: Literal[0.8, 1.0, 1.25] = 1.0


class GenerateResponse(BaseModel):
    job_id: str
    status: JobStatus
    video_url: Optional[str] = None
    message: str


class JobState(BaseModel):
    job_id: str
    status: JobStatus
    progress: int = 0
    stage: str = "queued"
    message: str = "Queued"
    topic: str
    subject: Optional[str] = None
    class_level: Optional[str] = None
    user_id: Optional[str] = None
    video_url: Optional[str] = None
    local_video_path: Optional[str] = None
    # Which stage produced the scenes: "gemini", "retrieval" or "presets". A
    # fallback that nobody can see is a silent fallback, so it is recorded on
    # the job and returned by the status and video endpoints.
    scene_source: Optional[str] = None
    duration_seconds: int = 60
    orientation: str = "landscape"
    voice_language: str = "en-IN"
    caption_language: str = "en-IN"
    pace: float = 1.0
    # Live progress for the "Generating" page: the five steps (retrieve, script,
    # narrate, render, encode), how long each finished one took, and what the
    # step is working on.
    step: Optional[str] = None
    step_times: Dict[str, float] = Field(default_factory=dict)
    step_started_at: Optional[datetime] = None
    scene_parts: List[str] = Field(default_factory=list)
    scene_titles: List[str] = Field(default_factory=list)
    scenes_done: int = 0
    sources: List[Dict[str, str]] = Field(default_factory=list)
    source_label: Optional[str] = None
    resolved_subject: Optional[str] = None
    resolved_class_level: Optional[str] = None
    # The NCERT chapter most passages came from, for the watch page.
    chapter_number: Optional[str] = None
    chapter_name: Optional[str] = None
    # One entry per scene: part, title, start/duration (s), narration, word times.
    timeline: List[Dict[str, Any]] = Field(default_factory=list)
    error: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class QuizSubmitRequest(BaseModel):
    question_id: str = Field(..., min_length=1, max_length=120)
    selected_option: str = Field(..., min_length=1, max_length=10)


class QuizGenerateRequest(BaseModel):
    """Ask for a quiz on a topic, or on the topic of an existing video job.

    ``topic`` alone is the standalone service: no video is needed. ``job_id``
    reuses a video's topic, subject and class so the quiz matches the lesson.
    """

    topic: Optional[str] = Field(default=None, min_length=2, max_length=160)
    job_id: Optional[str] = Field(default=None, max_length=80)
    subject: Optional[str] = Field(default=None, max_length=80)
    class_level: Optional[str] = Field(default=None, max_length=40)
    num_questions: int = Field(default=5, ge=3, le=10)


class QuizQuestionPublic(BaseModel):
    """A question as the student sees it: no answer, no explanation."""

    question_id: str
    difficulty: str
    question: str
    options: Dict[str, str]


class QuizStartResponse(BaseModel):
    quiz_id: str
    topic: str
    subject: Optional[str] = None
    class_level: Optional[str] = None
    total: int
    generator: str
    notes: List[str] = Field(default_factory=list)


class QuizSummary(BaseModel):
    correct: int
    total: int
    ability: float
    mastery: Optional[float] = None
    next_topic: Optional[str] = None


class QuizNextResponse(BaseModel):
    quiz_id: str
    topic: str
    done: bool
    answered: int
    total: int
    question: Optional[QuizQuestionPublic] = None
    summary: Optional[QuizSummary] = None


class QuizSubmitResponse(BaseModel):
    correct: bool
    correct_option: str = ""
    updated_ability: float
    updated_mastery: float
    next_topic: Optional[str] = None
    explanation: str


class QuizAttempt(BaseModel):
    attempt_id: str
    user_id: str
    question_id: str
    topic: str
    difficulty: str
    selected_option: str
    correct_option: str
    correct: bool
    updated_ability: float
    updated_mastery: float
    created_at: datetime = Field(default_factory=datetime.utcnow)
    quiz_id: Optional[str] = None
    question: Optional[str] = None
    subject: Optional[str] = None
    selected_text: Optional[str] = None
    correct_text: Optional[str] = None
    explanation: Optional[str] = None
    mistake_type: Optional[str] = None
    mistake_reason: Optional[str] = None
    mistake_source: Optional[str] = None


class QuizHistoryResponse(BaseModel):
    user_id: str
    total: int
    attempts: List[QuizAttempt] = Field(default_factory=list)


class UserDashboard(BaseModel):
    user_id: str
    ability: float
    mastery_by_topic: Dict[str, float]
    weak_areas: List[str]
    strong_areas: List[str]
    videos_watched: int = 0


class UserPublic(BaseModel):
    id: str
    name: str
    email: str
    is_admin: bool = False
    created_at: datetime
    streak_days: int = 0


class AdminCreateRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=254)
