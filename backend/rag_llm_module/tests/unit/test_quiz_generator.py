import pytest
from quiz_generator import (
    MCQQuestion,
    OptionChoice,
    QuizSet,
    QuizHallucinationDetector,
    QuizValidator,
    QuizGenerator,
)
from script_generator import MockLLMClient
from prompt_manager import PromptManager


@pytest.fixture
def quiz_generator():
    prompt_manager = PromptManager(prompts_dir="prompts")
    llm_client = MockLLMClient()
    return QuizGenerator(prompt_manager=prompt_manager, llm_client=llm_client)


def test_mcq_schema_generation():
    schema = MCQQuestion.get_json_schema()
    assert "properties" in schema
    assert "correct_answer" in schema["properties"]
    assert "ncert_reference" in schema["properties"]


def test_quiz_set_schema_generation():
    schema = QuizSet.get_json_schema()
    assert "properties" in schema
    assert "questions" in schema["properties"]


def test_quiz_validator():
    raw_list = [
        {
            "question_id": 1,
            "difficulty": "Easy",
            "topic": "Newton's Laws",
            "question": "What is inertia?",
            "options": [
                {"option_id": "A", "text": "Velocity"},
                {"option_id": "B", "text": "Mass measure"},
                {"option_id": "C", "text": "Speed"},
                {"option_id": "D", "text": "Distance"},
            ],
            "correct_answer": "B",
            "explanation": "Mass is quantitative measure of inertia.",
            "ncert_reference": "NCERT Physics page 50",
        },
        {
            "question_id": 2,
            "difficulty": "Medium",
            "topic": "Newton's Laws",
            "question": "Zero net force implies?",
            "options": [
                {"option_id": "A", "text": "Rest or uniform motion"},
                {"option_id": "B", "text": "Acceleration"},
                {"option_id": "C", "text": "Deceleration"},
                {"option_id": "D", "text": "Spin"},
            ],
            "correct_answer": "A",
            "explanation": "Newton's first law states uniform motion continues.",
            "ncert_reference": "NCERT Physics page 51",
        },
        {
            "question_id": 3,
            "difficulty": "Hard",
            "topic": "Newton's Laws",
            "question": "Compare accelerations of m1 and m2.",
            "options": [
                {"option_id": "A", "text": "m1 > m2"},
                {"option_id": "B", "text": "m2 > m1"},
                {"option_id": "C", "text": "Equal"},
                {"option_id": "D", "text": "Zero"},
            ],
            "correct_answer": "B",
            "explanation": "Smaller mass has larger acceleration for same force.",
            "ncert_reference": "NCERT Physics page 52",
        },
    ]

    questions = QuizValidator.validate_raw_questions(raw_list, default_topic="Newton's Laws")
    assert len(questions) == 3
    assert questions[0].difficulty == "Easy"
    assert questions[1].difficulty == "Medium"
    assert questions[2].difficulty == "Hard"


@pytest.mark.asyncio
async def test_quiz_generator_execution(quiz_generator):
    context = "Newton's First Law states that every body continues in its state of rest or uniform motion unless compelled by a net force."
    quiz_set = await quiz_generator.generate_quiz(
        subject="Physics",
        topic="Newton's Laws",
        chapter="Laws of Motion",
        class_num=11,
        retrieved_context=context,
    )

    assert isinstance(quiz_set, QuizSet)
    assert len(quiz_set.questions) == 3
    difficulties = [q.difficulty for q in quiz_set.questions]
    assert "Easy" in difficulties
    assert "Medium" in difficulties
    assert "Hard" in difficulties
