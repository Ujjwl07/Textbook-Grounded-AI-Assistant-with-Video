import pytest
from rag_llm_module.infrastructure.prompt_loader.filesystem_loader import FileSystemPromptRepository
from rag_llm_module.application.services.prompt_manager import PromptManagerService
from rag_llm_module.domain.exceptions import PromptTemplateNotFoundError, PromptRenderError


def test_filesystem_prompt_repository_loads_template():
    repo = FileSystemPromptRepository(templates_dir="templates")
    template = repo.get_template("script_generation", "v1.0.0")
    assert template.name == "script_generation"
    assert template.version == "v1.0.0"
    assert "class_num" in template.required_variables


def test_prompt_manager_renders_system_and_user_prompts():
    repo = FileSystemPromptRepository(templates_dir="templates")
    manager = PromptManagerService(repository=repo, strict_check=True)

    vars_input = {
        "subject": "Physics",
        "topic": "Gravity",
        "chapter_name": "Gravitation",
        "chapter_num": 5,
        "class_num": 11,
        "retrieved_context": "Gravity is a fundamental interaction which causes mutual attraction between all things with mass or energy.",
    }

    rendered = manager.prepare_prompt("script_generation", "v1.0.0", vars_input)
    assert rendered.template_name == "script_generation"
    assert rendered.template_version == "v1.0.0"
    assert "STEM Educator" in rendered.system_prompt
    assert "Physics" in rendered.user_prompt


def test_prompt_manager_strict_check_raises_error_on_missing_var():
    repo = FileSystemPromptRepository(templates_dir="templates")
    manager = PromptManagerService(repository=repo, strict_check=True)

    incomplete_vars = {"subject": "Physics"}
    with pytest.raises(PromptRenderError):
        manager.prepare_prompt("script_generation", "v1.0.0", incomplete_vars)


def test_missing_template_raises_not_found_error():
    repo = FileSystemPromptRepository(templates_dir="templates")
    with pytest.raises(PromptTemplateNotFoundError):
        repo.get_template("non_existent_template", "v9.9.9")
