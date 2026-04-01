"""Tests for admin API endpoints (admin.py)."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.api.admin import _require_reset_enabled


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
