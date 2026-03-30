"""Unit tests for quality_metrics service — all DB operations mocked."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def _mock_db(aql_results: dict | None = None):
    """Create a mock StandardDatabase with configurable AQL results."""
    db = MagicMock()
    db.has_collection.return_value = True

    _results = aql_results or {}
    call_count = {"n": 0}

    def execute_side_effect(query, bind_vars=None, **kwargs):
        key = call_count["n"]
        call_count["n"] += 1
        if key in _results:
            return iter(_results[key])
        return iter([])

    db.aql.execute.side_effect = execute_side_effect
    return db


class TestComputeOntologyQuality:
    """Tests for compute_ontology_quality."""

    def test_returns_metrics_for_populated_ontology(self):
        from app.services.quality_metrics import compute_ontology_quality

        db = _mock_db({
            0: [{"cnt": 5, "avg_conf": 0.85}],   # class stats
            1: [3],                                 # property count
            2: [4],                                 # classes with props
            3: [],                                  # orphan query (all_classes)
            4: [],                                  # orphan (children)
            5: [],                                  # orphan (parents)
            6: [],                                  # orphan (connected)
        })

        result = compute_ontology_quality(db, "onto_1")

        assert result["ontology_id"] == "onto_1"
        assert result["avg_confidence"] == 0.85
        assert result["class_count"] == 5
        assert result["property_count"] == 3
        assert result["completeness"] == 80.0
        assert result["classes_without_properties"] == 1

    def test_empty_ontology(self):
        from app.services.quality_metrics import compute_ontology_quality

        db = MagicMock()
        db.has_collection.return_value = False

        result = compute_ontology_quality(db, "empty")

        assert result["class_count"] == 0
        assert result["property_count"] == 0
        assert result["avg_confidence"] is None
        assert result["completeness"] == 0.0
        assert result["orphan_count"] == 0
        assert result["has_cycles"] is False

    def test_handles_missing_collections_gracefully(self):
        from app.services.quality_metrics import compute_ontology_quality

        db = MagicMock()
        db.has_collection.side_effect = lambda name: name == "ontology_classes"
        db.aql.execute.return_value = iter([{"cnt": 2, "avg_conf": 0.6}])

        result = compute_ontology_quality(db, "partial")

        assert result["class_count"] == 2
        assert result["property_count"] == 0


class TestComputeExtractionQuality:
    """Tests for compute_extraction_quality."""

    def test_returns_acceptance_rate(self):
        from app.services.quality_metrics import compute_extraction_quality

        db = _mock_db({
            0: [{"accepted": 8, "rejected": 1, "edited": 1}],  # curation_decisions
            1: [{"completed_at": 1000.5, "uploaded_at": 999.0}],  # time_to_ontology
        })

        result = compute_extraction_quality(db, "onto_1")

        assert result["acceptance_rate"] == 0.8
        assert result["time_to_ontology_ms"] == 1500

    def test_null_when_no_decisions(self):
        from app.services.quality_metrics import compute_extraction_quality

        db = _mock_db({
            0: [{"accepted": 0, "rejected": 0, "edited": 0}],
            1: [{}],
        })

        result = compute_extraction_quality(db, "onto_1")

        assert result["acceptance_rate"] is None
        assert result["time_to_ontology_ms"] is None

    def test_missing_curation_collection(self):
        from app.services.quality_metrics import compute_extraction_quality

        db = MagicMock()
        db.has_collection.return_value = False

        result = compute_extraction_quality(db, "onto_1")

        assert result["acceptance_rate"] is None
        assert result["time_to_ontology_ms"] is None


class TestComputeQualitySummary:
    """Tests for compute_quality_summary."""

    @patch("app.services.quality_metrics.compute_ontology_quality")
    def test_aggregates_across_ontologies(self, mock_oq):
        from app.services.quality_metrics import compute_quality_summary

        mock_oq.side_effect = [
            {
                "ontology_id": "a",
                "avg_confidence": 0.8,
                "class_count": 10,
                "property_count": 5,
                "completeness": 80.0,
                "orphan_count": 1,
                "has_cycles": False,
                "classes_without_properties": 2,
            },
            {
                "ontology_id": "b",
                "avg_confidence": 0.6,
                "class_count": 4,
                "property_count": 2,
                "completeness": 50.0,
                "orphan_count": 0,
                "has_cycles": True,
                "classes_without_properties": 2,
            },
        ]

        db = MagicMock()
        db.has_collection.return_value = True
        db.aql.execute.return_value = iter(["a", "b"])

        result = compute_quality_summary(db)

        assert result["ontology_count"] == 2
        assert result["total_classes"] == 14
        assert result["total_properties"] == 7
        assert result["avg_confidence"] == 0.7
        assert result["avg_completeness"] == 65.0
        assert result["ontologies_with_cycles"] == 1
        assert result["total_orphans"] == 1

    def test_empty_summary(self):
        from app.services.quality_metrics import compute_quality_summary

        db = MagicMock()
        db.has_collection.return_value = False

        result = compute_quality_summary(db)

        assert result["ontology_count"] == 0
        assert result["total_classes"] == 0
        assert result["avg_confidence"] is None


class TestCountOrphans:
    """Tests for _count_orphans."""

    def test_all_connected_returns_zero(self):
        from app.services.quality_metrics import _count_orphans

        db = _mock_db({
            0: [0],  # orphan count query returns 0
        })

        assert _count_orphans(db, "onto_1") == 0

    def test_no_subclass_of_collection(self):
        from app.services.quality_metrics import _count_orphans

        db = MagicMock()
        db.has_collection.side_effect = lambda n: n == "ontology_classes"
        db.aql.execute.return_value = iter([3])

        result = _count_orphans(db, "onto_1")

        assert result == 3


class TestDetectCycles:
    """Tests for _detect_cycles."""

    def test_no_cycle(self):
        from app.services.quality_metrics import _detect_cycles

        db = _mock_db({0: [], 1: []})

        assert _detect_cycles(db, "onto_1") is False

    def test_cycle_detected(self):
        from app.services.quality_metrics import _detect_cycles

        db = _mock_db({0: [True]})

        assert _detect_cycles(db, "onto_1") is True

    def test_missing_collections(self):
        from app.services.quality_metrics import _detect_cycles

        db = MagicMock()
        db.has_collection.return_value = False

        assert _detect_cycles(db, "onto_1") is False
