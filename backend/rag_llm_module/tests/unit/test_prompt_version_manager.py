import json

import pytest

from prompt_manager import (
    PromptException,
    PromptVersionManager,
)


def _make_prompt_tree(tmp_path):
    prompts_dir = tmp_path / "prompts"
    v1 = prompts_dir / "v1"
    v2 = prompts_dir / "v2"
    v1.mkdir(parents=True)
    v2.mkdir(parents=True)
    (v1 / "master.prompt").write_text("SYSTEM:\nExplain {topic} clearly.\n", encoding="utf-8")
    (v2 / "master.prompt").write_text(
        "SYSTEM:\nExplain {topic} clearly with context grounding.\n",
        encoding="utf-8",
    )
    return prompts_dir


def test_sync_from_disk_stores_every_prompt_version(tmp_path):
    prompts_dir = _make_prompt_tree(tmp_path)
    manager = PromptVersionManager(prompts_dir=str(prompts_dir))

    assert manager.list_versions("master") == ["v1", "v2"]
    metadata = manager.get_metadata("master", "v1")
    assert metadata.author == "system"
    assert metadata.timestamp_utc.endswith("Z")
    assert metadata.content_hash


def test_save_version_tracks_metadata_and_edit(tmp_path):
    prompts_dir = _make_prompt_tree(tmp_path)
    manager = PromptVersionManager(prompts_dir=str(prompts_dir))

    metadata = manager.save_version(
        "master",
        "SYSTEM:\nExplain {topic} clearly with citations.\n",
        version="v3",
        author="Shubham",
        performance={"faithfulness": 0.93, "latency_ms": 120},
        notes="Added citation requirement.",
        source_version="v2",
    )

    assert metadata.version == "v3"
    assert metadata.author == "Shubham"
    assert metadata.performance["faithfulness"] == 0.93
    exported = json.loads(manager.export_json(prompt_name="master"))
    record = exported["prompts"]["v3"]["master"]
    assert record["edit"]["changed_lines"] > 0
    assert "Added citation requirement." in manager.generate_changelog("master")


def test_compare_prompts_returns_diff_and_performance_delta(tmp_path):
    prompts_dir = _make_prompt_tree(tmp_path)
    manager = PromptVersionManager(prompts_dir=str(prompts_dir))
    manager.save_version(
        "master",
        "SYSTEM:\nExplain {topic} clearly with context grounding and citations.\n",
        version="v3",
        author="qa",
        performance={"faithfulness": 0.90},
        source_version="v2",
    )

    comparison = manager.compare_prompts("master", "v2", "v3")

    assert comparison.prompt_name == "master"
    assert comparison.similarity_score > 0.0
    assert comparison.added_lines >= 1
    assert any(line.startswith("+") for line in comparison.diff)
    assert comparison.performance_delta["faithfulness"]["from"] is None
    assert comparison.performance_delta["faithfulness"]["to"] == 0.90


def test_rollback_creates_new_version_without_overwriting(tmp_path):
    prompts_dir = _make_prompt_tree(tmp_path)
    manager = PromptVersionManager(prompts_dir=str(prompts_dir))

    metadata = manager.rollback(
        "master",
        target_version="v1",
        new_version="v3",
        author="Shubham",
        notes="Restore simpler wording.",
    )

    assert metadata.operation == "rollback"
    assert manager.load_prompt("master", "v3") == manager.load_prompt("master", "v1")


def test_existing_version_requires_explicit_overwrite(tmp_path):
    prompts_dir = _make_prompt_tree(tmp_path)
    manager = PromptVersionManager(prompts_dir=str(prompts_dir))

    with pytest.raises(PromptException):
        manager.save_version("master", "SYSTEM:\nNew content.\n", version="v2")
