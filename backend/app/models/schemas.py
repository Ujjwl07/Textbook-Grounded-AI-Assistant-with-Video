from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional

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
    error: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class VideoRecord(BaseModel):
    video_id: str
    topic: str
    subject: Optional[str] = None
    class_level: Optional[str] = None
    video_url: str
    transcript: Optional[str] = None
    scenes: List[Dict] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class QuizSubmitRequest(BaseModel):
    question_id: str = Field(..., min_length=1, max_length=120)
    selected_option: str = Field(..., min_length=1, max_length=10)


class QuizSubmitResponse(BaseModel):
    correct: bool
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


class QuizHistoryResponse(BaseModel):
    user_id: str
    total: int
    attempts: List[QuizAttempt] = Field(default_factory=list)


class UserDashboard(BaseModel):
    user_id: str
    ability: float
    mastery_by_topic: Dict[str, float]
    weak_areas: List[str]
    weak_areas: List[str]
    strong_areas: List[str]
    videos_watched: int = 0


class UserRegisterRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=120)
    email: str = Field(..., min_length=5, max_length=254)
    password: str = Field(..., min_length=8, max_length=128)


class UserLoginRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=254)
    password: str = Field(..., min_length=8, max_length=128)


class UserPublic(BaseModel):
    id: str
    name: str
    email: str
    is_admin: bool = False
    created_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserPublic


class AdminCreateRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=254)
