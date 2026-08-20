import os
import re
from typing import List, Dict
from jinja2 import Environment, FileSystemLoader, StrictUndefined, meta
from rag_llm_module.domain.entities.prompt import PromptTemplate
from rag_llm_module.domain.interfaces.prompt_repository import IPromptRepository
from rag_llm_module.domain.exceptions import PromptTemplateNotFoundError
from rag_llm_module.config.logging_config import get_logger

logger = get_logger("infrastructure.filesystem_prompt_loader")


class FileSystemPromptRepository(IPromptRepository):
    """
    FileSystem implementation of IPromptRepository using Jinja2 templates.
    Loads versioned files located at: `<templates_dir>/<template_name>/<version>.jinja2`
    """

    def __init__(self, templates_dir: str = "templates"):
        self.templates_dir = os.path.abspath(templates_dir)
        if not os.path.exists(self.templates_dir):
            os.makedirs(self.templates_dir, exist_ok=True)
            
        self.env = Environment(
            loader=FileSystemLoader(self.templates_dir),
            undefined=StrictUndefined,
            autoescape=False,
            trim_blocks=True,
            lstrip_blocks=True,
        )
        logger.info(f"Initialized FileSystemPromptRepository at {self.templates_dir}")

    def get_template(self, template_name: str, version: str) -> PromptTemplate:
        """Fetch template by name and version."""
        rel_path = os.path.join(template_name, f"{version}.jinja2")
        full_path = os.path.join(self.templates_dir, rel_path)

        if not os.path.isfile(full_path):
            logger.error(f"Template file missing: {full_path}")
            raise PromptTemplateNotFoundError(template_name, version)

        with open(full_path, "r", encoding="utf-8") as f:
            template_body = f.read()

        # Parse AST to identify required variables
        ast = self.env.parse(template_body)
        required_vars = list(meta.find_undeclared_variables(ast))

        return PromptTemplate(
            name=template_name,
            version=version,
            template_body=template_body,
            required_variables=required_vars,
            description=f"Loaded from filesystem path: {rel_path}",
        )

    def list_versions(self, template_name: str) -> List[str]:
        """List all available versions for a given template directory."""
        dir_path = os.path.join(self.templates_dir, template_name)
        if not os.path.isdir(dir_path):
            return []

        versions = []
        pattern = re.compile(r"^(v\d+\.\d+\.\d+)\.jinja2$")
        for filename in os.listdir(dir_path):
            match = pattern.match(filename)
            if match:
                versions.append(match.group(1))

        # Sort semver strings
        versions.sort(key=lambda s: [int(u) for u in s.lstrip("v").split(".")])
        return versions

    def get_latest_version(self, template_name: str) -> str:
        """Fetch latest semver template string."""
        versions = self.list_versions(template_name)
        if not versions:
            raise PromptTemplateNotFoundError(template_name, "latest")
        return versions[-1]
