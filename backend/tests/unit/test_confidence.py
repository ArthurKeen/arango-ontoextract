"""Unit tests for multi-signal confidence scoring."""

from __future__ import annotations

import pytest

from app.services.confidence import (
    WEIGHT_AGREEMENT,
    WEIGHT_DESCRIPTION,
    WEIGHT_LLM,
    WEIGHT_PROVENANCE,
    WEIGHT_STRUCTURAL,
    _description_score,
    _provenance_score,
    _structural_score,
    compute_class_confidence,
)


class TestStructuralScore:
    def test_all_signals_present(self):
        assert _structural_score(True, True, True) == 1.0

    def test_no_signals(self):
        assert _structural_score(False, False, False) == 0.0

    def test_properties_only(self):
        assert _structural_score(True, False, False) == pytest.approx(0.4)

    def test_parent_and_children_no_properties(self):
        assert _structural_score(False, True, True) == pytest.approx(0.6)


class TestDescriptionScore:
    def test_long_unique_description(self):
        desc = "A comprehensive description of a network firewall class with detailed semantics"
        score = _description_score(desc, [desc, "Something else entirely"])
        assert score > 0.5

    def test_short_description_penalized(self):
        score = _description_score("Short", ["Short", "Other thing"])
        assert score < 0.2

    def test_duplicate_description_loses_uniqueness(self):
        desc = "A reasonably long description that is duplicated across classes"
        score_unique = _description_score(desc, [desc])
        score_dup = _description_score(desc, [desc, desc])
        assert score_dup < score_unique

    def test_empty_description(self):
        score = _description_score("", ["", "Other"])
        assert score == 0.0


class TestProvenanceScore:
    def test_zero_chunks(self):
        assert _provenance_score(0) == 0.0

    def test_one_chunk(self):
        assert _provenance_score(1) == pytest.approx(1 / 3)

    def test_three_or_more_chunks(self):
        assert _provenance_score(3) == 1.0
        assert _provenance_score(10) == 1.0


class TestComputeClassConfidence:
    def test_perfect_signals_yield_high_confidence(self):
        score = compute_class_confidence(
            agreement_ratio=1.0,
            llm_confidence=0.95,
            has_properties=True,
            has_parent=True,
            has_children=True,
            description="A well-documented ontology class covering network infrastructure components in great detail",
            all_descriptions=[
                "A well-documented ontology class covering network infrastructure components in great detail",
                "Another unique class",
            ],
            provenance_count=5,
        )
        assert score >= 0.9

    def test_weak_signals_yield_low_confidence(self):
        score = compute_class_confidence(
            agreement_ratio=0.33,
            llm_confidence=0.3,
            has_properties=False,
            has_parent=False,
            has_children=False,
            description="x",
            all_descriptions=["x", "y"],
            provenance_count=0,
        )
        assert score < 0.2

    def test_mixed_signals_produce_differentiated_score(self):
        score_strong = compute_class_confidence(
            agreement_ratio=1.0,
            llm_confidence=0.9,
            has_properties=True,
            has_parent=True,
            has_children=False,
            description="An important class representing customer entities with full provenance",
            all_descriptions=["An important class representing customer entities with full provenance"],
            provenance_count=3,
        )
        score_weak = compute_class_confidence(
            agreement_ratio=0.67,
            llm_confidence=0.5,
            has_properties=False,
            has_parent=False,
            has_children=False,
            description="Unknown class",
            all_descriptions=["Unknown class"],
            provenance_count=1,
        )
        assert score_strong > score_weak
        assert score_strong != score_weak

    def test_score_is_bounded(self):
        score = compute_class_confidence(
            agreement_ratio=1.0,
            llm_confidence=1.0,
            has_properties=True,
            has_parent=True,
            has_children=True,
            description="x" * 200,
            all_descriptions=["x" * 200],
            provenance_count=100,
        )
        assert 0.0 <= score <= 1.0

    def test_weights_sum_to_one(self):
        total = (
            WEIGHT_AGREEMENT
            + WEIGHT_LLM
            + WEIGHT_STRUCTURAL
            + WEIGHT_DESCRIPTION
            + WEIGHT_PROVENANCE
        )
        assert total == pytest.approx(1.0)

    def test_default_llm_confidence_backward_compat(self):
        """When llm_confidence defaults to 0.5, score still differentiates."""
        score_a = compute_class_confidence(
            agreement_ratio=1.0,
            llm_confidence=0.5,
            has_properties=True,
            has_parent=True,
            has_children=False,
            description="A class with full structure and properties defined in the schema",
            all_descriptions=["A class with full structure and properties defined in the schema"],
            provenance_count=2,
        )
        score_b = compute_class_confidence(
            agreement_ratio=1.0,
            llm_confidence=0.5,
            has_properties=False,
            has_parent=False,
            has_children=False,
            description="tiny",
            all_descriptions=["tiny"],
            provenance_count=0,
        )
        assert score_a > score_b
