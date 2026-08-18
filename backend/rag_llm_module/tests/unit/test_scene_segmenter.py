import pytest
from scene_segmenter import (
    Scene,
    SceneCollection,
    JSONAutoRepairer,
    SceneValidator,
    VideoGeneratorAdapter,
    SceneSegmenter,
)
from script_generator import MockLLMClient
from prompt_manager import PromptManager


@pytest.fixture
def segmenter():
    prompt_manager = PromptManager(prompts_dir="prompts")
    llm_client = MockLLMClient()
    return SceneSegmenter(prompt_manager=prompt_manager, llm_client=llm_client)


def test_json_auto_repairer_cleans_markdown():
    raw_markdown = "```json\n[{\"scene_id\": 1, \"title\": \"HOOK\", \"narration\": \"Text\", \"bullets\": [], \"visual_type\": \"Split\", \"animation\": \"Fade\", \"background\": \"Bg\", \"subtitle\": \"Sub\", \"duration\": 10.0}]\n```"
    repaired = JSONAutoRepairer.repair(raw_markdown)
    assert not repaired.startswith("```")
    assert repaired.startswith("[")


def test_json_auto_repairer_parses_valid_json():
    raw = "[{\"scene_id\": 1, \"title\": \"HOOK\", \"narration\": \"Hi\", \"bullets\": [], \"visual_type\": \"Split\", \"animation\": \"Fade\", \"background\": \"Bg\", \"subtitle\": \"Sub\", \"duration\": 10.0}]"
    parsed = JSONAutoRepairer.parse_and_repair(raw)
    assert isinstance(parsed, list)
    assert parsed[0]["title"] == "HOOK"


def test_scene_schema_generation():
    schema = Scene.get_json_schema()
    assert "properties" in schema
    assert "scene_id" in schema["properties"]
    assert "narration" in schema["properties"]


@pytest.mark.asyncio
async def test_scene_segmenter_execution(segmenter):
    script_text = "HOOK:\nWelcome to physics.\n\nCONCEPT:\nForce causes acceleration.\n\nEXAMPLE:\n10 N on 2 kg gives 5 m/s2.\n\nMEMORY:\nF=ma.\n\nNEET ALERT:\nWatch units!"
    collection = await segmenter.segment_script(script_text, subject="Physics", topic="Newton's Laws")

    assert isinstance(collection, SceneCollection)
    assert len(collection.scenes) == 5
    assert collection.scenes[0].scene_id == 1
    assert collection.scenes[4].scene_id == 5


def test_video_generator_adapters():
    scenes = [
        Scene(
            scene_id=i,
            title=f"Scene {i}",
            narration=f"Narration {i}",
            bullets=[f"Bullet {i}"],
            visual_type="Split-Screen",
            formula="F=ma" if i == 2 else None,
            animation="Zoom-In",
            background=f"Background {i}",
            subtitle=f"Subtitle {i}",
            duration=10.0,
        )
        for i in range(1, 6)
    ]
    collection = SceneCollection(script_title="Test Lesson", total_duration_sec=50.0, scenes=scenes)

    sora_prompts = VideoGeneratorAdapter.to_sora_prompts(collection)
    assert len(sora_prompts) == 5
    assert "Cinematic style" in sora_prompts[0]["prompt"]

    manim_code = VideoGeneratorAdapter.to_manim_script(collection)
    assert "class GeneratedLessonScene" in manim_code
    assert "MathTex(r'F=ma')" in manim_code
