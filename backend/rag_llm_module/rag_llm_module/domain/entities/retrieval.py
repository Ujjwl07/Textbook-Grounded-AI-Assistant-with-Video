from pydantic import BaseModel, Field, ConfigDict
from typing import Dict, Any, Optional


class RetrieverPayload(BaseModel):
    """
    Input data model received downstream from the Retrieval module (Team 1).
    Immutable value object representing retrieved academic context.
    """
    model_config = ConfigDict(frozen=True)

    subject: str = Field(..., min_length=1, description="Academic subject (e.g. Physics, Chemistry, Biology)")
    topic: str = Field(..., min_length=1, description="Specific sub-topic name")
    chapter_name: str = Field(..., min_length=1, description="Chapter title")
    chapter_num: int = Field(..., ge=1, description="Chapter number")
    class_num: int = Field(..., ge=1, le=12, description="Target educational grade / class level (1-12)")
    retrieved_context: str = Field(..., min_length=5, description="Passages retrieved from vector database / knowledge graph")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Optional metadata (source URLs, chunk IDs, confidence scores)")

    def to_template_vars(self) -> Dict[str, Any]:
        """Convert payload to dictionary suitable for Jinja2 template rendering."""
        return {
            "subject": self.subject,
            "topic": self.topic,
            "chapter_name": self.chapter_name,
            "chapter_num": self.chapter_num,
            "class_num": self.class_num,
            "retrieved_context": self.retrieved_context,
            "metadata": self.metadata,
        }
