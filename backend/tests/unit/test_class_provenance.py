"""Class provenance reads the evidence recorded at extraction (FR-4.7).

FR-4.7 requires that clicking a *node* — not only an edge — surfaces
``source_chunk_ids``, quoted ``evidence_text``, spans, confidence and rationale.
The endpoint previously ignored all of it and returned every chunk of every
linked document, which is a search result wearing provenance's clothes. These
tests pin the recorded-evidence path, the pre-evidence fallback, and the
labelling that keeps the two distinguishable.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.api.ontology import _shared, schema_temporal
from app.main import app

client = TestClient(app)

# Patch target for the current-version lookup; spelled out once to keep the
# `with` blocks below inside the line limit.
_GET_CURRENT = (schema_temporal.temporal_svc, "get_current")

CLASS_KEY = "VehicleSecurity"
URL = f"/api/v1/ontology/class/{CLASS_KEY}/provenance"

EVIDENCE = [
    {
        "source_chunk_ids": ["c7", "c9"],
        "source_spans": ["120:184"],
        "evidence_text": "The vehicle security system reports door and window status.",
        "evidence_confidence": 0.82,
        "extraction_rationale": "Names a subsystem and states what it reports.",
    }
]

CHUNKS = [
    {"_key": "c7", "text": "…security…", "chunk_index": 7, "doc_id": "d1", "section_heading": "S"},
    {"_key": "c9", "text": "…locking…", "chunk_index": 9, "doc_id": "d1", "section_heading": "S"},
]


def _class(evidence: list[dict] | None) -> dict:
    return {"_key": CLASS_KEY, "label": "Vehicle Security", "evidence": evidence or []}


class TestRecordedEvidencePath:
    def test_returns_only_the_chunks_the_extractor_used(self) -> None:
        db = MagicMock()
        db.has_collection.return_value = True
        with (
            patch.object(_shared, "get_db", return_value=db),
            patch.object(*_GET_CURRENT, return_value=_class(EVIDENCE)),
            patch.object(_shared, "run_aql", return_value=iter(CHUNKS)) as raq,
        ):
            resp = client.get(URL)
        assert resp.status_code == 200
        body = resp.json()
        assert body["level"] == "evidence"
        assert [c["_key"] for c in body["data"]] == ["c7", "c9"]
        # Looked up BY KEY — not a document-wide sweep.
        assert raq.call_args.kwargs["bind_vars"]["ids"] == ["c7", "c9"]

    def test_surfaces_quote_rationale_and_confidence(self) -> None:
        db = MagicMock()
        db.has_collection.return_value = True
        with (
            patch.object(_shared, "get_db", return_value=db),
            patch.object(*_GET_CURRENT, return_value=_class(EVIDENCE)),
            patch.object(_shared, "run_aql", return_value=iter(CHUNKS)),
        ):
            body = client.get(URL).json()
        ev = body["evidence"][0]
        assert ev["evidence_text"].startswith("The vehicle security system")
        assert ev["extraction_rationale"]
        assert ev["evidence_confidence"] == 0.82
        assert ev["source_spans"] == ["120:184"]

    def test_deduplicates_chunk_ids_across_evidence_items(self) -> None:
        shared = [
            {"source_chunk_ids": ["c7"], "evidence_text": "a"},
            {"source_chunk_ids": ["c7", "c9"], "evidence_text": "b"},
        ]
        db = MagicMock()
        db.has_collection.return_value = True
        with (
            patch.object(_shared, "get_db", return_value=db),
            patch.object(*_GET_CURRENT, return_value=_class(shared)),
            patch.object(_shared, "run_aql", return_value=iter(CHUNKS)) as raq,
        ):
            client.get(URL)
        assert raq.call_args.kwargs["bind_vars"]["ids"] == ["c7", "c9"]


class TestFallback:
    """Pre-evidence classes still get an answer — clearly labelled as a weak one."""

    def test_falls_back_to_linked_documents_and_says_so(self) -> None:
        db = MagicMock()
        db.has_collection.return_value = True
        with (
            patch.object(_shared, "get_db", return_value=db),
            patch.object(*_GET_CURRENT, return_value=_class([])),
            patch.object(_shared, "run_aql", return_value=iter(CHUNKS)),
        ):
            body = client.get(URL).json()
        assert body["level"] == "document"
        assert body["total_count"] == 2

    def test_evidence_present_but_chunks_missing_degrades_to_document(self) -> None:
        # Recorded chunk ids that no longer resolve must not yield an empty
        # "evidence" answer — that would look authoritative and show nothing.
        db = MagicMock()
        db.has_collection.return_value = True
        calls = [iter([]), iter(CHUNKS)]
        with (
            patch.object(_shared, "get_db", return_value=db),
            patch.object(*_GET_CURRENT, return_value=_class(EVIDENCE)),
            patch.object(_shared, "run_aql", side_effect=calls),
        ):
            body = client.get(URL).json()
        assert body["level"] == "document"
        # The recorded evidence is still returned, so the quote survives.
        assert body["evidence"][0]["evidence_text"]

    def test_unknown_class_is_404(self) -> None:
        db = MagicMock()
        with (
            patch.object(_shared, "get_db", return_value=db),
            patch.object(*_GET_CURRENT, return_value=None),
        ):
            assert client.get(URL).status_code == 404

    def test_malformed_evidence_entries_are_skipped(self) -> None:
        db = MagicMock()
        db.has_collection.return_value = True
        with (
            patch.object(_shared, "get_db", return_value=db),
            patch.object(
                *_GET_CURRENT,
                # A non-dict entry must be skipped, not crash the endpoint.
                return_value=_class(["not-a-dict", {"source_chunk_ids": ["c7"]}]),  # type: ignore[list-item]
            ),
            patch.object(_shared, "run_aql", return_value=iter([CHUNKS[0]])),
        ):
            body = client.get(URL).json()
        assert body["level"] == "evidence"
        assert len(body["evidence"]) == 1
