import pytest
from script_generator import (
    ScriptGenerator,
    ScriptParser,
    ScriptValidator,
    MockLLMClient,
    Script,
    ResponseFormatter,
)
from prompt_manager import PromptManager


@pytest.fixture
def generator():
    prompt_manager = PromptManager(prompts_dir="prompts")
    llm_client = MockLLMClient()
    return ScriptGenerator(prompt_manager=prompt_manager, llm_client=llm_client)


@pytest.mark.asyncio
async def test_script_generator_execution(generator):
    script = await generator.generate_script(
        subject="Physics",
        topic="Newton's Laws",
        chapter="Laws of Motion",
        class_num=11,
        retrieved_context="Newton's First Law states that an object continues in its state of rest unless acted upon by a net force.",
    )

    assert isinstance(script, Script)
    assert script.subject == "Physics"
    assert script.class_num == 11
    assert len(script.hook) > 0
    assert len(script.concept) > 0
    assert len(script.example) > 0
    assert len(script.memory) > 0
    assert len(script.neet_alert) > 0
    assert script.metrics.total_tokens > 0
    assert script.metrics.latency_sec >= 0.0
    assert script.validation.word_count > 0


@pytest.mark.asyncio
async def test_script_parser_parsing():
    raw_text = (
        "HOOK:\nThis is the hook section text.\n\n"
        "CONCEPT:\nThis is the concept section text.\n\n"
        "EXAMPLE:\nThis is the example section text.\n\n"
        "MEMORY:\nThis is the memory section text.\n\n"
        "NEET ALERT:\nThis is the neet alert section text."
    )
    parsed_dict, sections_list = ScriptParser.parse(raw_text)

    assert "HOOK" in parsed_dict
    assert "CONCEPT" in parsed_dict
    assert "EXAMPLE" in parsed_dict
    assert "MEMORY" in parsed_dict
    assert "NEET ALERT" in parsed_dict
    assert len(sections_list) == 5


@pytest.mark.asyncio
async def test_script_validator_word_count():
    parsed_dict = {
        "HOOK": "Hook text",
        "CONCEPT": "Concept text",
        "EXAMPLE": "Example text",
        "MEMORY": "Memory text",
        "NEET ALERT": "Alert text",
    }
    short_text = "Short text under 250 words"
    context = "Some context"

    result = ScriptValidator.validate(parsed_dict, short_text, context)
    assert result.word_count_valid is False
    assert len(result.errors) > 0


@pytest.mark.asyncio
async def test_script_streaming(generator):
    chunks = []
    async for chunk in generator.generate_script_stream(
        subject="Physics",
        topic="Newton's Laws",
        chapter="Laws of Motion",
        class_num=11,
        retrieved_context="Newton's First Law states that an object continues in its state of rest unless acted upon by a net force.",
    ):
        chunks.append(chunk)

    assert len(chunks) > 0
    full_streamed = "".join(chunks)
    assert "HOOK:" in full_streamed
