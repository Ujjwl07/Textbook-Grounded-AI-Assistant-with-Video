from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional


class PromptTemplate(BaseModel):
    """Domain model representing a loaded prompt template."""
    name: str = Field(..., description="Template identifier (e.g. script_generation)")
    version: str = Field(..., description="Semantic version string (e.g. v1.0.0)")
    template_body: str = Field(..., description="Raw template string containing Jinja2 variables")
    required_variables: List[str] = Field(default_factory=list, description="Variables required by the template")
    description: Optional[str] = Field(default=None, description="Description of the template's target persona & purpose")
    author: Optional[str] = Field(default=None)


class RenderedPrompt(BaseModel):
    """Domain model representing an instantiated prompt ready for LLM invocation."""
    template_name: str
    template_version: str
    system_prompt: str
    user_prompt: str
    rendered_variables: Dict[str, Any]

    def get_combined_prompt(self) -> str:
        """Returns unified text string for hashing or legacy single-prompt completion."""
        return f"SYSTEM:\n{self.system_prompt}\n\nUSER:\n{self.user_prompt}"
