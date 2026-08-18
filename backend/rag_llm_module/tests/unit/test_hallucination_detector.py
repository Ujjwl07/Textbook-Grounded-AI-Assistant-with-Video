"""
Unit tests for hallucination_detector.py.
Covers all major classes: SentenceSegmenter, TFIDFVectorizer,
SemanticSimilarityEngine, all subject-aware checkers, HallucinationClassifier,
HallucinationDetector, ReportSerializer, and the convenience function.
"""

import json
import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from hallucination_detector import (
    Subject,
    HallucinationType,
    RiskLevel,
    SentenceSegmenter,
    TFIDFVectorizer,
    SemanticSimilarityEngine,
    EquationChecker,
    UnitChecker,
    DefinitionChecker,
    ReactionChecker,
    BiologicalTermChecker,
    HallucinationClassifier,
    HallucinationDetector,
    HallucinationReport,
    ReportSerializer,
    detect_hallucinations,
)


# ===========================================================================
# SentenceSegmenter
# ===========================================================================

class TestSentenceSegmenter:
    def test_segments_basic_text(self):
        text = "Newton's first law states inertia. Every object resists change. Mass is key."
        sentences = SentenceSegmenter.segment(text)
        assert len(sentences) >= 2

    def test_empty_string_returns_empty(self):
        assert SentenceSegmenter.segment("") == []

    def test_whitespace_only_returns_empty(self):
        assert SentenceSegmenter.segment("   \n\t  ") == []

    def test_protects_decimal_numbers(self):
        text = "The acceleration is 9.8 m/s squared. It never changes."
        sentences = SentenceSegmenter.segment(text)
        # 9.8 should NOT cause a split
        assert any("9.8" in s for s in sentences)

    def test_filters_very_short_fragments(self):
        text = "Hello. Hi. Newton's first law states that inertia resists changes."
        sentences = SentenceSegmenter.segment(text)
        for s in sentences:
            assert len(s.split()) >= 3


# ===========================================================================
# TFIDFVectorizer
# ===========================================================================

class TestTFIDFVectorizer:
    def test_fit_builds_vocabulary(self):
        v = TFIDFVectorizer()
        v.fit(["inertia is the resistance to change", "mass measures inertia"])
        assert len(v._idf) > 0

    def test_transform_returns_dict(self):
        v = TFIDFVectorizer()
        v.fit(["inertia resists change"])
        vec = v.transform("inertia is the property of mass")
        assert isinstance(vec, dict)

    def test_transform_empty_string(self):
        v = TFIDFVectorizer()
        v.fit(["some text here"])
        assert v.transform("") == {}

    def test_fit_empty_corpus(self):
        v = TFIDFVectorizer()
        v.fit([])  # should not raise
        assert v._idf == {}

    def test_oov_terms_get_smoothed_idf(self):
        v = TFIDFVectorizer()
        v.fit(["physics chemistry biology"])
        vec = v.transform("mathematics trigonometry calculus")
        assert len(vec) > 0


# ===========================================================================
# SemanticSimilarityEngine
# ===========================================================================

class TestSemanticSimilarityEngine:
    def _make_engine(self, corpus):
        vect = TFIDFVectorizer()
        engine = SemanticSimilarityEngine(vect)
        engine.index_context(corpus)
        return engine

    def test_returns_nonzero_for_matching_text(self):
        engine = self._make_engine([
            "Newton's first law states that inertia resists change in motion."
        ])
        score, sent, ev = engine.best_context_match(
            "Newton's first law is about inertia and motion."
        )
        assert score > 0.0

    def test_returns_zero_for_empty_context(self):
        vect = TFIDFVectorizer()
        engine = SemanticSimilarityEngine(vect)
        score, sent, ev = engine.best_context_match("any sentence")
        assert score == 0.0

    def test_returns_higher_score_for_similar_text(self):
        corpus = [
            "Mass is the quantitative measure of inertia.",
            "The sky is completely unrelated text.",
        ]
        engine = self._make_engine(corpus)
        score_relevant, _, _ = engine.best_context_match(
            "Mass quantifies inertia in physics."
        )
        score_irrelevant, _, _ = engine.best_context_match(
            "Elephants are large mammals found in Africa."
        )
        assert score_relevant > score_irrelevant

    def test_score_bounded_01(self):
        engine = self._make_engine(["inertia mass force velocity acceleration"])
        score, _, _ = engine.best_context_match("inertia mass force velocity acceleration")
        assert 0.0 <= score <= 1.0


# ===========================================================================
# EquationChecker
# ===========================================================================

class TestEquationChecker:
    checker = EquationChecker()

    def test_grounded_equation_passes(self):
        sentence = "Newton's second law gives F = ma for force."
        context = "Newton's second law of motion: F = ma, where m is mass and a is acceleration."
        result = self.checker.check(sentence, context)
        assert not result.flagged

    def test_ungrounded_equation_flagged(self):
        sentence = "The energy equation is E = mc^2."
        context = "Inertia is the resistance to change in motion."
        result = self.checker.check(sentence, context)
        assert result.flagged
        assert result.hallucination_type == HallucinationType.WRONG_EQUATION
        assert result.confidence_penalty > 0

    def test_no_equation_returns_clean(self):
        sentence = "Inertia is an important concept in physics."
        context = "Mass is the measure of inertia."
        result = self.checker.check(sentence, context)
        assert not result.flagged
        assert result.confidence_penalty == 0.0


# ===========================================================================
# UnitChecker
# ===========================================================================

class TestUnitChecker:
    checker = UnitChecker()

    def test_grounded_unit_passes(self):
        sentence = "The acceleration due to gravity is 9.8 m/s."
        context = "Standard acceleration due to gravity is 9.8 m/s on Earth's surface."
        result = self.checker.check(sentence, context)
        assert not result.flagged

    def test_ungrounded_unit_flagged(self):
        sentence = "The force is 500 N applied horizontally."
        context = "Objects at rest tend to stay at rest unless a force acts on them."
        result = self.checker.check(sentence, context)
        assert result.flagged
        assert result.hallucination_type == HallucinationType.WRONG_UNIT

    def test_no_units_returns_clean(self):
        sentence = "Inertia is a fundamental property of matter."
        context = "All bodies possess inertia."
        result = self.checker.check(sentence, context)
        assert not result.flagged


# ===========================================================================
# DefinitionChecker
# ===========================================================================

class TestDefinitionChecker:
    checker = DefinitionChecker()

    def test_grounded_definition_passes(self):
        sentence = "Inertia is defined as the resistance of a body to change its state of motion."
        context = "Inertia is the resistance of a body to any change in its state of rest or uniform motion."
        result = self.checker.check(sentence, context)
        assert not result.flagged

    def test_ungrounded_definition_flagged(self):
        sentence = "Momentum is defined as the product of mass and velocity squared."
        context = "Newton's first law states that every object continues in its state of rest."
        result = self.checker.check(sentence, context)
        assert result.flagged
        assert result.hallucination_type == HallucinationType.WRONG_DEFINITION

    def test_non_definitional_sentence_skipped(self):
        sentence = "Remember that mass causes inertia in all objects."
        context = "Mass is the quantitative measure of inertia."
        result = self.checker.check(sentence, context)
        assert not result.flagged


# ===========================================================================
# ReactionChecker
# ===========================================================================

class TestReactionChecker:
    checker = ReactionChecker()

    def test_no_reaction_returns_clean(self):
        sentence = "Inertia is the resistance to change in state of motion."
        context = "Mass measures inertia."
        result = self.checker.check(sentence, context)
        assert not result.flagged

    def test_ungrounded_reaction_flagged(self):
        sentence = "The reaction: Mg + O2 -> MgO occurs rapidly."
        context = "Carbon reacts with oxygen to produce carbon dioxide."
        result = self.checker.check(sentence, context)
        # Mg+O2->MgO is not in context
        assert result.flagged
        assert result.hallucination_type == HallucinationType.WRONG_REACTION


# ===========================================================================
# BiologicalTermChecker
# ===========================================================================

class TestBiologicalTermChecker:
    checker = BiologicalTermChecker()

    def test_grounded_bio_term_passes(self):
        sentence = "Photosynthesis occurs in the chloroplast of plant cells."
        context = "Photosynthesis is the process by which plants convert light energy using chloroplasts."
        result = self.checker.check(sentence, context)
        assert not result.flagged

    def test_ungrounded_scientific_name_flagged(self):
        sentence = "Mangifera indica is commonly found in tropical regions."
        context = "Photosynthesis produces glucose from carbon dioxide and water."
        result = self.checker.check(sentence, context)
        assert result.flagged
        assert result.hallucination_type == HallucinationType.WRONG_BIOLOGICAL_TERM

    def test_ungrounded_process_flagged(self):
        sentence = "Mitosis produces two identical daughter cells."
        context = "Photosynthesis and respiration are primary metabolic processes."
        result = self.checker.check(sentence, context)
        assert result.flagged


# ===========================================================================
# HallucinationClassifier
# ===========================================================================

class TestHallucinationClassifier:
    classifier = HallucinationClassifier()

    def _make_checker_result(self, flagged=False, penalty=0.0, h_type=None):
        from hallucination_detector import SubjectCheckerResult
        return SubjectCheckerResult(
            checker_name="Test",
            flagged=flagged,
            hallucination_type=h_type,
            detail="test",
            confidence_penalty=penalty,
        )

    def test_high_similarity_produces_supported_verdict(self):
        verdict = self.classifier.classify(
            sentence_index=0,
            sentence="Mass is the measure of inertia.",
            similarity_score=0.85,
            best_context_sentence="Mass is the quantitative measure of inertia.",
            evidence_fragments=["mass", "inertia"],
            checker_results=[self._make_checker_result()],
        )
        assert not verdict.is_hallucination
        assert verdict.risk_level == RiskLevel.NONE

    def test_low_similarity_produces_hallucination_verdict(self):
        verdict = self.classifier.classify(
            sentence_index=1,
            sentence="The speed of light in vacuum is 100 m/s.",
            similarity_score=0.05,
            best_context_sentence="Inertia is resistance to motion change.",
            evidence_fragments=[],
            checker_results=[self._make_checker_result()],
        )
        assert verdict.is_hallucination
        assert verdict.risk_level in (RiskLevel.CRITICAL, RiskLevel.HIGH)

    def test_penalty_reduces_support_score(self):
        verdict_no_penalty = self.classifier.classify(
            sentence_index=0,
            sentence="F = ma is Newton's second law.",
            similarity_score=0.60,
            best_context_sentence="Newton second law F=ma",
            evidence_fragments=["newton"],
            checker_results=[self._make_checker_result()],
        )
        verdict_with_penalty = self.classifier.classify(
            sentence_index=0,
            sentence="F = ma is Newton's second law.",
            similarity_score=0.60,
            best_context_sentence="Newton second law F=ma",
            evidence_fragments=["newton"],
            checker_results=[self._make_checker_result(flagged=True, penalty=0.35, h_type=HallucinationType.WRONG_EQUATION)],
        )
        assert verdict_with_penalty.support_score < verdict_no_penalty.support_score

    def test_confidence_is_bounded(self):
        verdict = self.classifier.classify(
            sentence_index=0,
            sentence="Test sentence.",
            similarity_score=0.50,
            best_context_sentence="Test context.",
            evidence_fragments=[],
            checker_results=[],
        )
        assert 0.0 <= verdict.confidence <= 1.0


# ===========================================================================
# HallucinationDetector  (Integration)
# ===========================================================================

NCERT_CONTEXT = """
Newton's First Law of Motion states that every body continues in its state of rest
or of uniform motion in a straight line unless compelled by an external force to
change that state. Inertia is the inherent property of a body to resist any change
in its state of rest or uniform velocity. Mass is the quantitative measure of inertia.
A body with greater mass possesses greater inertia, and requires a larger net force
to produce the same acceleration. Newton's second law: F = ma where F is net force
in Newtons, m is mass in kg, and a is acceleration in m/s squared.
"""

FAITHFUL_SCRIPT = """
HOOK:
Newton's first law states that every body continues in its state of rest or uniform
motion unless compelled by an external force. This is the principle of inertia.
CONCEPT:
Inertia is the inherent property of a body to resist any change in its state.
Mass is the quantitative measure of inertia. Greater mass means greater inertia.
EXAMPLE:
Applying Newton's second law F = ma, a 10 kg object requires more force to accelerate
than a 1 kg object to produce the same acceleration.
MEMORY:
Remember: Mass is the quantitative measure of inertia. Higher mass equals higher inertia.
NEET ALERT:
Newton's first law is often tested with statements about inertia and mass relationship.
"""

HALLUCINATED_SCRIPT = """
HOOK:
Einstein's theory of everything proves that quantum tunneling explains all motion.
CONCEPT:
Inertia is defined as the force applied by photons on dark matter particles.
The speed of light is 50 m/s in standard conditions according to quantum mechanics.
EXAMPLE:
Using the formula E = hf, we see that Planck's constant determines inertia directly.
MEMORY:
Velocity is the quantitative measure of inertia, not mass, according to Einstein.
NEET ALERT:
Momentum quantifies inertia; heavier objects have less inertia according to relativity.
"""


class TestHallucinationDetector:
    def test_faithful_script_high_faithfulness(self):
        detector = HallucinationDetector(subject=Subject.PHYSICS)
        report = detector.detect(
            retrieved_context=NCERT_CONTEXT,
            generated_script=FAITHFUL_SCRIPT,
            topic="Newton's Laws",
        )
        assert report.overall_faithfulness_score > 0.40

    def test_hallucinated_script_lower_faithfulness(self):
        detector_f = HallucinationDetector(subject=Subject.PHYSICS)
        detector_h = HallucinationDetector(subject=Subject.PHYSICS)
        report_f = detector_f.detect(NCERT_CONTEXT, FAITHFUL_SCRIPT, "Newton's Laws")
        report_h = detector_h.detect(NCERT_CONTEXT, HALLUCINATED_SCRIPT, "Newton's Laws")
        assert report_f.overall_faithfulness_score > report_h.overall_faithfulness_score

    def test_report_metadata_populated(self):
        detector = HallucinationDetector(subject=Subject.PHYSICS)
        report = detector.detect(NCERT_CONTEXT, FAITHFUL_SCRIPT, "Newton's Laws")
        assert report.subject == "Physics"
        assert report.topic == "Newton's Laws"
        assert report.report_id
        assert report.detector_version == "1.0.0"
        assert report.detection_latency_sec >= 0.0

    def test_sentence_verdicts_populated(self):
        detector = HallucinationDetector(subject=Subject.PHYSICS)
        report = detector.detect(NCERT_CONTEXT, FAITHFUL_SCRIPT, "Newton's Laws")
        assert len(report.sentence_verdicts) > 0
        for v in report.sentence_verdicts:
            assert 0.0 <= v.support_score <= 1.0
            assert 0.0 <= v.confidence <= 1.0
            assert v.risk_level in list(RiskLevel)

    def test_empty_context_raises_value_error(self):
        detector = HallucinationDetector()
        with pytest.raises(ValueError, match="retrieved_context"):
            detector.detect("", FAITHFUL_SCRIPT)

    def test_empty_script_raises_value_error(self):
        detector = HallucinationDetector()
        with pytest.raises(ValueError, match="generated_script"):
            detector.detect(NCERT_CONTEXT, "")

    def test_biology_subject_uses_bio_checkers(self):
        detector = HallucinationDetector(subject=Subject.BIOLOGY)
        bio_context = (
            "Photosynthesis occurs in the chloroplast. "
            "It converts light energy into chemical energy. "
            "The process involves light-dependent and light-independent reactions."
        )
        bio_script = (
            "Photosynthesis occurs in the chloroplast of plant cells. "
            "It is a process that converts light energy to chemical energy."
        )
        report = detector.detect(bio_context, bio_script, "Photosynthesis")
        assert report.subject == "Biology"
        assert report.overall_faithfulness_score >= 0.0

    def test_chemistry_subject_uses_reaction_checkers(self):
        detector = HallucinationDetector(subject=Subject.CHEMISTRY)
        chem_context = "Hydrogen and oxygen react to form water: 2H2 + O2 -> 2H2O."
        chem_script = "The combustion reaction 2H2 + O2 -> 2H2O produces water."
        report = detector.detect(chem_context, chem_script, "Combustion")
        assert report.subject == "Chemistry"

    def test_word_counts_match_input(self):
        detector = HallucinationDetector()
        report = detector.detect(NCERT_CONTEXT, FAITHFUL_SCRIPT, "Test")
        assert report.context_word_count == len(NCERT_CONTEXT.split())
        assert report.script_word_count == len(FAITHFUL_SCRIPT.split())

    def test_counts_are_consistent(self):
        detector = HallucinationDetector(subject=Subject.PHYSICS)
        report = detector.detect(NCERT_CONTEXT, HALLUCINATED_SCRIPT, "Newton's Laws")
        assert (
            report.supported_sentence_count + report.hallucinated_sentence_count
            == report.script_sentence_count
        )


# ===========================================================================
# HallucinationReport Serialization
# ===========================================================================

class TestHallucinationReportSerialization:
    def _make_report(self):
        detector = HallucinationDetector(subject=Subject.PHYSICS)
        return detector.detect(NCERT_CONTEXT, FAITHFUL_SCRIPT, "Newton's Laws")

    def test_to_json_produces_valid_json(self):
        report = self._make_report()
        json_str = report.to_json()
        parsed = json.loads(json_str)
        assert "report_id" in parsed
        assert "overall_faithfulness_score" in parsed

    def test_to_dict_returns_dict(self):
        report = self._make_report()
        d = report.to_dict()
        assert isinstance(d, dict)
        assert "sentence_verdicts" in d

    def test_report_serializer_to_json(self):
        report = self._make_report()
        json_str = ReportSerializer.to_json(report)
        assert json.loads(json_str)["subject"] == "Physics"

    def test_report_serializer_compact_json(self):
        report = self._make_report()
        compact = ReportSerializer.to_compact_json(report)
        assert "\n" not in compact
        parsed = json.loads(compact)
        assert "report_id" in parsed

    def test_report_serializer_summary(self):
        report = self._make_report()
        summary = ReportSerializer.to_summary(report)
        expected_keys = [
            "report_id", "subject", "topic", "overall_faithfulness_score",
            "hallucination_rate", "supported_sentence_count",
            "hallucinated_sentence_count", "critical_violations",
            "high_violations", "detector_version",
        ]
        for key in expected_keys:
            assert key in summary


# ===========================================================================
# detect_hallucinations convenience function
# ===========================================================================

class TestDetectHallucinationsFunction:
    def test_returns_report_object(self):
        report = detect_hallucinations(
            retrieved_context=NCERT_CONTEXT,
            generated_script=FAITHFUL_SCRIPT,
            subject="Physics",
            topic="Newton's Laws",
        )
        assert isinstance(report, HallucinationReport)

    def test_unknown_subject_defaults_to_general(self):
        report = detect_hallucinations(
            retrieved_context=NCERT_CONTEXT,
            generated_script=FAITHFUL_SCRIPT,
            subject="InvalidSubject",
        )
        assert report.subject == "General"

    def test_custom_threshold_respected(self):
        # Very high threshold -> more hallucinations flagged
        report_strict = detect_hallucinations(
            NCERT_CONTEXT, FAITHFUL_SCRIPT, subject="Physics", hallucination_threshold=0.95
        )
        # Very low threshold -> fewer hallucinations flagged
        report_lenient = detect_hallucinations(
            NCERT_CONTEXT, FAITHFUL_SCRIPT, subject="Physics", hallucination_threshold=0.05
        )
        assert report_strict.hallucinated_sentence_count >= report_lenient.hallucinated_sentence_count

    def test_json_output_parseable(self):
        report = detect_hallucinations(NCERT_CONTEXT, FAITHFUL_SCRIPT, subject="Physics")
        parsed = json.loads(report.to_json())
        assert parsed["overall_faithfulness_score"] >= 0.0
        assert parsed["hallucination_rate"] >= 0.0
