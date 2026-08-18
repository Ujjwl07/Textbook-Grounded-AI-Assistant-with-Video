from typing import Protocol, List
from rag_llm_module.domain.entities.prompt import PromptTemplate


class IPromptRepository(Protocol):
    """Protocol interface for retrieving prompt templates from storage (Filesystem, DB, Git)."""

    def get_template(self, template_name: str, version: str) -> PromptTemplate:
        """Fetch template by name and version. Throws PromptTemplateNotFoundError if missing."""
        ...

    def list_versions(self, template_name: str) -> List[str]:
        """List all available versions for a template sorted by semver."""
        ...

    def get_latest_version(self, template_name: str) -> str:
        """Fetch latest version string for a template."""
        ...
