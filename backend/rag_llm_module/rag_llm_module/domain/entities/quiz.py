from pydantic import BaseModel, Field
from typing import List, Literal


class QuizChoice(BaseModel):
    """Option choice for multiple choice question."""
    option_id: Literal["A", "B", "C", "D"]
    text: str = Field(..., min_length=1)


class QuizQuestion(BaseModel):
    """Single taxonomical evaluation question."""
    question_id: int = Field(..., ge=1)
    question_type: Literal["multiple_choice", "conceptual_short"]
    blooms_taxonomy_level: Literal["Remember", "Understand", "Apply", "Analyze", "Evaluate", "Create"] = Field(
        default="Understand", description="Pedagogical cognitive level"
    )
    prompt_text: str = Field(..., min_length=5, description="Question stem text")
    choices: List[QuizChoice] = Field(default_factory=list, description="4 choices for multiple choice")
    correct_option_id: Literal["A", "B", "C", "D"] = Field(..., description="ID of correct option")
    explanation: str = Field(..., min_length=10, description="Comprehensive rationale referencing ground truth context")


class QuizSet(BaseModel):
    """Complete collection of questions generated from academic content."""
    subject: str
    topic: str
    class_num: int
    questions: List[QuizQuestion] = Field(..., min_length=1)
