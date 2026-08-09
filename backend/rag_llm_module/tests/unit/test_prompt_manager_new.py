import pytest
from prompt_manager import (
    Prompt,
    PromptManager,
    PromptLoader,
    PromptValidator,
    PromptRegistry,
    PromptVersion,
    PromptNotFoundError,
    InvalidPromptVersionError,
    PromptValidationError,
)

@pytest.fixture
def manager():
    return PromptManager(prompts_dir="prompts")

@pytest.fixture
def sample_kwargs():
    return {
        "subject": "Physics",
        "topic": "Newton's Laws",
        "chapter_name": "Laws of Motion",
        "chapter_num": 3,
        "class_num": 11,
        "retrieved_context": "Newton's First Law states that an object stays at rest unless acted upon by a net force.",
    }


def test_prompt_loader_lists_versions(manager):
    loader = manager.loader
    versions = loader.list_available_versions()
    assert "v1" in versions
    assert "v2" in versions


def test_prompt_version_validation():
    v1 = PromptVersion(version_str="v1")
    v2 = PromptVersion(version_str="v2")
    assert v1 < v2
    assert str(v1) == "v1"

    with pytest.raises(InvalidPromptVersionError):
        PromptVersion(version_str="version_1")


def test_master_prompt_v1_generation(manager, sample_kwargs):
    prompt_obj = manager.get_prompt("master", version="v1", **sample_kwargs)
    assert isinstance(prompt_obj, Prompt)
    assert prompt_obj.name == "master"
    assert prompt_obj.version == "v1"
    assert prompt_obj.subject == "Physics"
    assert "Newton's First Law" in prompt_obj.content
    assert prompt_obj.applied_addendum is True  # Physics addendum auto injected
    assert "PHYSICS SUBJECT ADDENDUM" in prompt_obj.content


def test_master_prompt_v2_generation(manager, sample_kwargs):
    prompt_obj = manager.get_prompt("master", version="v2", **sample_kwargs)
    assert isinstance(prompt_obj, Prompt)
    assert prompt_obj.version == "v2"
    assert "[VERSION 2 ENHANCED]" in prompt_obj.content
    assert "PHYSICS SUBJECT ADDENDUM [v2]" in prompt_obj.content


def test_scene_prompt_generation(manager, sample_kwargs):
    prompt_obj = manager.get_prompt("scene", version="v1", **sample_kwargs)
    assert isinstance(prompt_obj, Prompt)
    assert prompt_obj.name == "scene"
    assert "Visual Scene Director" in prompt_obj.content or "visual scenes" in prompt_obj.content


def test_quiz_prompt_generation(manager, sample_kwargs):
    prompt_obj = manager.get_prompt("quiz", version="v1", **sample_kwargs)
    assert isinstance(prompt_obj, Prompt)
    assert prompt_obj.name == "quiz"
    assert "assessment" in prompt_obj.content.lower()


def test_missing_placeholder_raises_validation_error(manager):
    incomplete_kwargs = {
        "subject": "Physics",
        "topic": "Newton's Laws",
        # missing chapter_name, chapter_num, class_num, retrieved_context
    }
    with pytest.raises(PromptValidationError):
        manager.get_prompt("master", version="v1", **incomplete_kwargs)


def test_missing_prompt_file_raises_not_found_error(manager, sample_kwargs):
    with pytest.raises(PromptNotFoundError):
        manager.get_prompt("non_existent_prompt", version="v1", **sample_kwargs)


def test_prompt_caching(manager, sample_kwargs):
    prompt1 = manager.get_prompt("master", version="v1", **sample_kwargs)
    prompt2 = manager.get_prompt("master", version="v1", **sample_kwargs)
    assert prompt1 is prompt2  # Same cached instance

    manager.clear_cache()
    prompt3 = manager.get_prompt("master", version="v1", **sample_kwargs)
    assert prompt1 is not prompt3  # New instance after cache clear
