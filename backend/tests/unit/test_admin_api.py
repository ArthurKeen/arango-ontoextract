"""Tests for admin API endpoints (admin.py)."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.api.admin import _remove_ontology_graphs, _require_reset_enabled


class TestRequireResetEnabled:
    def test_raises_403_when_not_enabled(self):
        with patch.dict(os.environ, {"ALLOW_SYSTEM_RESET": "false"}):
            with pytest.raises(HTTPException) as exc_info:
                _require_reset_enabled()
            assert exc_info.value.status_code == 403

    def test_raises_403_when_env_missing(self):
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(HTTPException) as exc_info:
                _require_reset_enabled()
            assert exc_info.value.status_code == 403

    def test_passes_when_enabled_true(self):
        with patch.dict(os.environ, {"ALLOW_SYSTEM_RESET": "true"}):
            _require_reset_enabled()  # Should not raise

    def test_passes_when_enabled_1(self):
        with patch.dict(os.environ, {"ALLOW_SYSTEM_RESET": "1"}):
            _require_reset_enabled()  # Should not raise

    def test_passes_when_enabled_yes(self):
        with patch.dict(os.environ, {"ALLOW_SYSTEM_RESET": "yes"}):
            _require_reset_enabled()  # Should not raise


class TestResetEndpoints:
    def test_remove_ontology_graphs_removes_only_prefixed_graphs(self):
        mock_db = MagicMock()
        mock_db.graphs.return_value = [
            {"name": "ontology_customer"},
            {"name": "other_graph"},
            "ontology_supplier",
        ]

        removed = _remove_ontology_graphs(mock_db)

        assert removed == ["ontology_customer", "ontology_supplier"]
        assert mock_db.delete_graph.call_count == 2

    def test_remove_ontology_graphs_handles_graph_listing_error(self):
        mock_db = MagicMock()
        mock_db.graphs.side_effect = RuntimeError("boom")

        removed = _remove_ontology_graphs(mock_db)

        assert removed == []
        mock_db.delete_graph.assert_not_called()

    @pytest.mark.asyncio
    async def test_reset_ontology_truncates_collections(self):
        mock_collection = MagicMock()
        mock_db = MagicMock()
        mock_db.has_collection.return_value = True
        mock_db.collection.return_value = mock_collection

        with (
            patch.dict(os.environ, {"ALLOW_SYSTEM_RESET": "true"}),
            patch("app.api.admin.get_db", return_value=mock_db),
        ):
            from app.api.admin import reset_ontology_data

            result = await reset_ontology_data()

        assert result["reset"] is True
        assert len(result["collections_truncated"]) > 0
        # Should NOT include documents/chunks
        assert "documents" not in result["collections_truncated"]
        assert "chunks" not in result["collections_truncated"]

    @pytest.mark.asyncio
    async def test_full_reset_includes_documents(self):
        mock_collection = MagicMock()
        mock_db = MagicMock()
        mock_db.has_collection.return_value = True
        mock_db.collection.return_value = mock_collection

        with (
            patch.dict(os.environ, {"ALLOW_SYSTEM_RESET": "true"}),
            patch("app.api.admin.get_db", return_value=mock_db),
        ):
            from app.api.admin import reset_all_data

            result = await reset_all_data()

        assert result["reset"] is True
        assert "documents" in result["collections_truncated"]
        assert "chunks" in result["collections_truncated"]

    @pytest.mark.asyncio
    async def test_reset_skips_missing_collections(self):
        mock_db = MagicMock()
        mock_db.has_collection.return_value = False

        with (
            patch.dict(os.environ, {"ALLOW_SYSTEM_RESET": "true"}),
            patch("app.api.admin.get_db", return_value=mock_db),
        ):
            from app.api.admin import reset_ontology_data

            result = await reset_ontology_data()

        assert result["reset"] is True
        assert result["collections_truncated"] == []
        mock_db.collection.assert_not_called()


class TestFeedbackLearningArtifacts:
    @pytest.mark.asyncio
    async def test_feedback_learning_artifacts_delegates_to_service(self):
        payload = {
            "status": "ready",
            "auto_apply": False,
            "summary": {"total_examples": 1},
            "examples": [{"decision_key": "d1"}],
            "regression_candidates": [],
        }

        with (
            patch("app.api.admin.get_db", return_value=MagicMock(name="db")) as mock_get_db,
            patch(
                "app.api.admin.build_feedback_learning_examples",
                return_value=payload,
            ) as mock_build,
        ):
            from app.api.admin import feedback_learning_artifacts

            result = await feedback_learning_artifacts(ontology_id="onto_1", limit=25)

        assert result == payload
        mock_build.assert_called_once_with(
            mock_get_db.return_value,
            ontology_id="onto_1",
            limit=25,
        )

    @pytest.mark.asyncio
    async def test_feedback_learning_artifacts_wraps_service_error(self):
        with (
            patch("app.api.admin.get_db", return_value=MagicMock()),
            patch(
                "app.api.admin.build_feedback_learning_examples",
                side_effect=RuntimeError("boom"),
            ),
        ):
            from app.api.admin import feedback_learning_artifacts

            with pytest.raises(HTTPException) as exc:
                await feedback_learning_artifacts(ontology_id=None, limit=100)

        assert exc.value.status_code == 500
