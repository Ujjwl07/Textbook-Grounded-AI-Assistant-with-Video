from pydantic import BaseModel, Field
from typing import List, Literal, Optional


class DialogueLine(BaseModel):
    """Single turn of dialogue in an educational script."""
    speaker: Literal["Teacher", "Student", "Narrator"] = Field(..., description="Role of the speaker")
    dialogue: str = Field(..., min_length=1, description="Spoken dialogue text")
    emotion_tone: str = Field(default="Enthusiastic", description="Emotional delivery tone (e.g. Curious, Explanatory)")
    visual_cue: str = Field(default="", description="Visual or animation instruction corresponding to this dialogue line")


class EducationalScript(BaseModel):
    """Complete educational script generated from retrieved academic context."""
    title: str = Field(..., description="Title of the educational script episode")
    summary: str = Field(..., description="High-level pedagogical summary")
    target_grade: int = Field(..., ge=1, le=12, description="Grade level target")
    dialogue: List[DialogueLine] = Field(..., min_length=1, description="Sequential dialogue turns")
    key_learning_points: List[str] = Field(default_factory=list, description="Core takeaways extracted from text")
    estimated_duration_sec: float = Field(default=120.0, description="Estimated vocal duration in seconds")
