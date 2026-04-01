"""Additional unit tests for extraction API route handlers."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import BackgroundTasks, HTTPException

from app.api.extraction import (
    StartRunRequest,
    _resolve_doc_ids,
    delete_run,
    get_run,
    get_run_cost,
    get_run_results,
    get_run_steps,
    list_runs,
    retry_run,
    start_extraction,
)


class TestResolveDocIds:
    def test_raises_when_no_document_ids(self):
        with pytest.raises(HTTPException) as exc:
            _resolve_doc_ids(StartRunRequest())
        assert exc.value.status_code == 422

    def test_raises_when_document_missing(self):
        db = MagicMock()
        db.has_collection.return_value = True
        docs = MagicMock()
        db.collection.return_value = docs
        with (
            patch("app.api.extraction.get_db", return_value=db),
            patch("app.api.extraction.doc_get", return_value=None),
            pytest.raises(HTTPException) as exc,
        ):
            _resolve_doc_ids(StartRunRequest(document_id="d1"))
        assert "not found" in exc.value.detail

    def test_raises_when_document_not_ready(self):
        db = MagicMock()
        db.has_collection.return_value = True
        docs = MagicMock()
        db.collection.return_value = docs
        with (
            patch("app.api.extraction.get_db", return_value=db),
            patch(
                "app.api.extraction.doc_get", return_value={"_key": "d1", "status": "processing"}
            ),
            pytest.raises(HTTPException) as exc,
        ):
            _resolve_doc_ids(StartRunRequest(document_id="d1"))
        assert "not ready" in exc.value.detail

    def test_returns_unique_ready_ids(self):
        db = MagicMock()
        db.has_collection.return_value = True
        docs = MagicMock()
        db.collection.return_value = docs
        with (
            patch("app.api.extraction.get_db", return_value=db),
            patch("app.api.extraction.doc_get", return_value={"_key": "d1", "status": "ready"}),
        ):
            result = _resolve_doc_ids(StartRunRequest(document_id="d1", document_ids=["d1", "d2"]))
        assert result == ["d1", "d2"]


class TestExtractionRoutes:
    @pytest.mark.asyncio
    async def test_start_extraction_creates_run_and_background_task(self):
        body = StartRunRequest(document_id="d1", config={"passes": 2}, target_ontology_id="onto1")
        background_tasks = BackgroundTasks()
        with (
            patch("app.api.extraction._resolve_doc_ids", return_value=["d1"]),
            patch("app.api.extraction.get_db", return_value=MagicMock()),
            patch(
                "app.api.extraction.extraction_service.create_run_record",
                return_value={"_key": "r1", "status": "queued"},
            ) as mock_create,
        ):
            result = await start_extraction(body, background_tasks)
        mock_create.assert_called_once()
        assert result.run_id == "r1"
        assert result.doc_id == "d1"
        assert len(background_tasks.tasks) == 1

    @pytest.mark.asyncio
    async def test_list_runs_enriches_documents_and_counts(self):
        db = MagicMock()
        db.has_collection.return_value = True
        documents = MagicMock()
        db.collection.return_value = documents
        paginated = MagicMock()
        paginated.model_dump.return_value = {
            "data": [
                {
                    "_key": "r1",
                    "doc_ids": ["d1"],
                    "stats": {"errors": []},
                    "started_at": 1,
                    "completed_at": 2,
                }
            ],
            "cursor": None,
            "has_more": False,
            "total_count": 1,
        }
        with (
            patch("app.api.extraction.get_db", return_value=db),
            patch("app.api.extraction.extraction_service.list_runs", return_value=paginated),
            patch(
                "app.api.extraction.doc_get",
                return_value={"_key": "d1", "filename": "doc.md", "chunk_count": 4},
            ),
            patch("app.api.extraction.run_aql", side_effect=[["onto1"], [3], [2]]),
        ):
            result = await list_runs(limit=10)
        run = result["data"][0]
        assert run["document_name"] == "doc.md"
        assert run["chunk_count"] == 4
        assert run["classes_extracted"] == 3
        assert run["properties_extracted"] == 2
        assert run["duration_ms"] == 1000

    @pytest.mark.asyncio
    async def test_get_run_delegates(self):
        expected = {"_key": "r1", "status": "completed"}
        with (
            patch("app.api.extraction.get_db", return_value=MagicMock()),
            patch("app.api.extraction.extraction_service.get_run", return_value=expected),
        ):
            result = await get_run("r1")
        assert result is expected

    @pytest.mark.asyncio
    async def test_delete_run_deletes_run_and_results(self):
        db = MagicMock()
        col = MagicMock()
        db.has_collection.return_value = True
        db.collection.return_value = col
        col.has.side_effect = lambda key: True
        with patch("app.api.extraction.get_db", return_value=db):
            result = await delete_run("r1")
        assert result == {"deleted": True, "run_id": "r1"}
        assert col.delete.call_count == 2

    @pytest.mark.asyncio
    async def test_delete_run_raises_when_missing(self):
        db = MagicMock()
        col = MagicMock()
        db.has_collection.return_value = True
        db.collection.return_value = col
        col.has.return_value = False
        with (
            patch("app.api.extraction.get_db", return_value=db),
            pytest.raises(HTTPException) as exc,
        ):
            await delete_run("r1")
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_get_steps_results_retry_and_cost_delegate(self):
        db = MagicMock()
        with (
            patch("app.api.extraction.get_db", return_value=db),
            patch(
                "app.api.extraction.extraction_service.get_run_steps",
                return_value=[{"step": "extractor"}],
            ),
            patch(
                "app.api.extraction.extraction_service.get_run_results",
                return_value={"classes": []},
            ),
            patch(
                "app.api.extraction.extraction_service.retry_run",
                new=AsyncMock(return_value={"_key": "r2", "status": "queued"}),
            ),
            patch("app.api.extraction.extraction_service.get_run_cost", return_value={"usd": 1.23}),
        ):
            steps = await get_run_steps("r1")
            results = await get_run_results("r1")
            retry = await retry_run("r1")
            cost = await get_run_cost("r1")
        assert steps == {"run_id": "r1", "steps": [{"step": "extractor"}]}
        assert results == {"classes": []}
        assert retry.new_run_id == "r2"
        assert cost == {"usd": 1.23}
