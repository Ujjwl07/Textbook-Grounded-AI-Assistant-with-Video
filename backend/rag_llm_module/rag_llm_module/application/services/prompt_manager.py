from typing import Dict, Any, Optional
from jinja2 import Template, Environment, StrictUndefined
from rag_llm_module.domain.entities.prompt import PromptTemplate, RenderedPrompt
from rag_llm_module.domain.interfaces.prompt_repository import IPromptRepository
from rag_llm_module.domain.exceptions import PromptRenderError
from rag_llm_module.config.logging_config import get_logger

logger = get_logger("application.prompt_manager")


class PromptManagerService:
    """
    Application Service responsible for retrieving templates, validating parameters,
    and rendering Jinja2 prompts into structured RenderedPrompt objects.
    """

    def __init__(self, repository: IPromptRepository, strict_check: bool = True):
        self.repository = repository
        self.strict_check = strict_check

    def prepare_prompt(
        self,
        template_name: str,
        version: Optional[str] = None,
        variables: Optional[Dict[str, Any]] = None,
    ) -> RenderedPrompt:
        """
        Loads template, validates input variables, and renders System & User prompt blocks.
        """
        if variables is None:
            variables = {}

        if not version or version == "latest":
            version = self.repository.get_latest_version(template_name)

        template: PromptTemplate = self.repository.get_template(template_name, version)

        # Validate missing variables
        missing_vars = [v for v in template.required_variables if v not in variables]
        if missing_vars and self.strict_check:
            err_msg = f"Missing required variables for prompt '{template_name}:{version}': {missing_vars}"
            logger.error(err_msg)
            raise PromptRenderError(err_msg)

        try:
            j2_env = Environment(undefined=StrictUndefined, trim_blocks=True, lstrip_blocks=True)
            j2_template = j2_env.from_string(template.template_body)
            rendered_text = j2_template.render(**variables)
        except Exception as e:
            logger.error(f"Failed rendering template '{template_name}:{version}': {str(e)}")
            raise PromptRenderError(f"Rendering failed: {str(e)}") from e

        # Extract SYSTEM: and USER: sections
        system_prompt, user_prompt = self._split_system_user_prompts(rendered_text)

        logger.debug(f"Successfully rendered prompt '{template_name}:{version}'")

        return RenderedPrompt(
            template_name=template_name,
            template_version=version,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            rendered_variables=variables,
        )

    @staticmethod
    def _split_system_user_prompts(raw_rendered: str) -> tuple[str, str]:
        """Parses SYSTEM: and USER: blocks from rendered prompt text."""
        system_prefix = "SYSTEM:"
        user_prefix = "USER:"

        system_prompt = ""
        user_prompt = raw_rendered

        if system_prefix in raw_rendered and user_prefix in raw_rendered:
            parts = raw_rendered.split(user_prefix, 1)
            system_part = parts[0].replace(system_prefix, "", 1).strip()
            user_part = parts[1].strip()
            return system_part, user_part

        return system_prompt, user_prompt
