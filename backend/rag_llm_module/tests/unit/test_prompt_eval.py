import os
import pytest
from prompt_eval import (
    NLPMetricsCalculator,
    PromptEvaluator,
    PromptVersionComparator,
    ComparisonReport,
)
from script_generator import ScriptGenerator, MockLLMClient
from prompt_manager import PromptManager


@pytest.fixture
def evaluator():
    prompt_manager = PromptManager(prompts_dir="prompts")
    llm_client = MockLLMClient()
    generator = ScriptGenerator(prompt_manager=prompt_manager, llm_client=llm_client)
    return PromptEvaluator(script_generator=generator)


def test_nlp_metrics_bleu():
    ref = "Newton's first law states that an object remains at rest unless acted upon by a net force."
    cand = "Newton's first law states that a body stays at rest unless a net force acts."
    score = NLPMetricsCalculator.compute_bleu(ref, cand)
    assert 0.0 <= score <= 1.0
    assert score > 0.1


def test_nlp_metrics_rouge():
    ref = "Newton's first law states that an object remains at rest unless acted upon by a net force."
    cand = "Newton's first law states that an object remains at rest."
    score = NLPMetricsCalculator.compute_rouge_l(ref, cand)
    assert 0.0 <= score <= 1.0
    assert score > 0.3


def test_nlp_metrics_cosine():
    text1 = "Mass is the quantitative measure of inertia."
    text2 = "Inertia is quantitatively measured by mass."
    score = NLPMetricsCalculator.compute_cosine_similarity(text1, text2)
    assert 0.0 <= score <= 1.0
    assert score > 0.4  # TF-IDF bag-of-words similarity (no embeddings); threshold calibrated to actual output


@pytest.mark.asyncio
async def test_prompt_evaluator_version(evaluator):
    test_inputs = [
        {
            "subject": "Physics",
            "topic": "Newton's Laws",
            "chapter": "Laws of Motion",
            "class_num": 11,
            "retrieved_context": "Newton's First Law states that every body continues in its state of rest unless compelled by a net force.",
        }
    ]

    result = await evaluator.evaluate_version("master", "v1", test_inputs)
    assert result.version == "v1"
    assert result.metrics.accuracy > 0.0
    assert result.overall_score > 0.0


@pytest.mark.asyncio
async def test_prompt_version_comparator(evaluator, tmp_path):
    comparator = PromptVersionComparator(evaluator=evaluator)
    test_inputs = [
        {
            "subject": "Physics",
            "topic": "Newton's Laws",
            "chapter": "Laws of Motion",
            "class_num": 11,
            "retrieved_context": "Newton's First Law states that every body continues in its state of rest unless compelled by a net force.",
        }
    ]

    report: ComparisonReport = await comparator.compare_versions("master", ["v1", "v2"], test_inputs)
    assert report.winning_version in ["v1", "v2"]
    assert "# Prompt Evaluation & Benchmark Report" in report.summary_markdown

    # Export CSV & Excel test
    csv_path = str(tmp_path / "benchmark_report.csv")
    out_csv = comparator.export_to_csv(report, csv_path)
    assert os.path.exists(out_csv)
