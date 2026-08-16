"""Curated-lexicon API — collision queue + label decisions (PRD §6.20)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from urllib.parse import quote

from fastapi.testclient import TestClient

from app.api.ontology import _shared
from app.db import lexicon_repo
from app.main import app
from app.services import label_collisions

client = TestClient(app)

DOC_ROLE = "http://example.org/crm#DocumentRole"
CONTACT_ROLE = "http://example.org/crm#ContactRole"


class TestListCollisions:
    def test_lists_open_collisions_by_default(self) -> None:
        rows = [{"_key": "c1", "label": "role", "status": "open"}]
        with (
            patch.object(_shared, "get_db", return_value=MagicMock()),
            patch.object(lexicon_repo, "list_collisions", return_value=rows) as mk,
        ):
            resp = client.get("/api/v1/ontology/lexicon/collisions")
        assert resp.status_code == 200
        assert resp.json()["count"] == 1
        assert mk.call_args.kwargs["status"] == "open"

    def test_threads_status_scope_and_paging(self) -> None:
        with (
            patch.object(_shared, "get_db", return_value=MagicMock()),
            patch.object(lexicon_repo, "list_collisions", return_value=[]) as mk,
        ):
            resp = client.get(
                "/api/v1/ontology/lexicon/collisions"
                "?status=resolved&scope=catalog&limit=10&offset=5"
            )
        assert resp.status_code == 200
        assert mk.call_args.kwargs["status"] == "resolved"
        assert mk.call_args.kwargs["scope"] == "catalog"
        assert mk.call_args.kwargs["limit"] == 10
        assert mk.call_args.kwargs["offset"] == 5


class TestGetCollision:
    def test_returns_the_document(self) -> None:
        with (
            patch.object(_shared, "get_db", return_value=MagicMock()),
            patch.object(lexicon_repo, "get_collision", return_value={"_key": "c1"}),
        ):
            resp = client.get("/api/v1/ontology/lexicon/collisions/c1")
        assert resp.status_code == 200
        assert resp.json()["_key"] == "c1"

    def test_missing_is_404(self) -> None:
        with (
            patch.object(_shared, "get_db", return_value=MagicMock()),
            patch.object(lexicon_repo, "get_collision", return_value=None),
        ):
            resp = client.get("/api/v1/ontology/lexicon/collisions/ghost")
        assert resp.status_code == 404


class TestDetect:
    def test_threads_ontology_ids_and_flags(self) -> None:
        with (
            patch.object(_shared, "get_db", return_value=MagicMock()),
            patch.object(
                label_collisions, "detect_in_ontologies", return_value={"detected": 2}
            ) as mk,
        ):
            resp = client.post(
                "/api/v1/ontology/lexicon/collisions/detect",
                json={"ontology_ids": ["o1", "o2"], "include_stopwords": True},
            )
        assert resp.status_code == 200
        assert resp.json()["detected"] == 2
        assert mk.call_args.kwargs["ontology_ids"] == ["o1", "o2"]
        assert mk.call_args.kwargs["include_stopwords"] is True

    def test_ontology_ids_is_required(self) -> None:
        resp = client.post("/api/v1/ontology/lexicon/collisions/detect", json={})
        assert resp.status_code == 422


class TestIngest:
    def test_accepts_a_report_with_source_systems_and_samples(self) -> None:
        with (
            patch.object(_shared, "get_db", return_value=MagicMock()),
            patch.object(
                label_collisions,
                "ingest_report",
                return_value={"accepted": 1, "rejected": [], "collisions": []},
            ) as mk,
        ):
            resp = client.post(
                "/api/v1/ontology/lexicon/collisions/ingest",
                json={
                    "scope": "demo-catalog",
                    "source": "contextual-data-fabric",
                    "items": [
                        {
                            "label": "role",
                            "occurrences": [
                                {
                                    "concept_uri": DOC_ROLE,
                                    "source_system": "docs",
                                    "sample_values": ["signal", "qbr"],
                                },
                                {
                                    "concept_uri": CONTACT_ROLE,
                                    "source_system": "crm",
                                    "sample_values": ["champion", "exec"],
                                },
                            ],
                        }
                    ],
                },
            )
        assert resp.status_code == 200
        assert resp.json()["accepted"] == 1
        item = mk.call_args.kwargs["items"][0]
        assert item["occurrences"][0]["sample_values"] == ["signal", "qbr"]
        assert mk.call_args.kwargs["source"] == "contextual-data-fabric"

    def test_occurrence_without_concept_uri_is_rejected_by_schema(self) -> None:
        resp = client.post(
            "/api/v1/ontology/lexicon/collisions/ingest",
            json={"scope": "s", "items": [{"label": "role", "occurrences": [{"x": 1}]}]},
        )
        assert resp.status_code == 422


class TestResolve:
    def test_records_the_decision(self) -> None:
        with (
            patch.object(_shared, "get_db", return_value=MagicMock()),
            patch.object(
                label_collisions,
                "resolve_collision",
                return_value={"collision": {"status": "resolved"}, "decisions": [{"_key": "d1"}]},
            ) as mk,
        ):
            resp = client.post(
                "/api/v1/ontology/lexicon/collisions/c1/resolve",
                json={
                    "curator_id": "arthur",
                    "resolutions": [
                        {
                            "concept_uri": CONTACT_ROLE,
                            "label": "job title",
                            "concept_type": "datatype_property",
                            "ontology_id": "o1",
                            "rationale": "a person's job, not a document kind",
                        }
                    ],
                },
            )
        assert resp.status_code == 200
        assert resp.json()["collision"]["status"] == "resolved"
        assert mk.call_args.kwargs["curator_id"] == "arthur"
        assert mk.call_args.kwargs["resolutions"][0]["label"] == "job title"

    def test_curator_id_is_required(self) -> None:
        # The audit trail is the feature; an anonymous decision is not one.
        resp = client.post(
            "/api/v1/ontology/lexicon/collisions/c1/resolve",
            json={"resolutions": [{"concept_uri": CONTACT_ROLE, "label": "x"}]},
        )
        assert resp.status_code == 422

    def test_unknown_collision_is_404(self) -> None:
        with (
            patch.object(_shared, "get_db", return_value=MagicMock()),
            patch.object(
                label_collisions,
                "resolve_collision",
                side_effect=ValueError("collision 'ghost' not found"),
            ),
        ):
            resp = client.post(
                "/api/v1/ontology/lexicon/collisions/ghost/resolve",
                json={"curator_id": "arthur", "dismiss": True},
            )
        assert resp.status_code == 404

    def test_invalid_resolution_is_422(self) -> None:
        with (
            patch.object(_shared, "get_db", return_value=MagicMock()),
            patch.object(
                label_collisions,
                "resolve_collision",
                side_effect=ValueError(
                    "concept_uri 'x' is not one of this collision's occurrences"
                ),
            ),
        ):
            resp = client.post(
                "/api/v1/ontology/lexicon/collisions/c1/resolve",
                json={"curator_id": "arthur", "resolutions": [{"concept_uri": "x", "label": "y"}]},
            )
        assert resp.status_code == 422


class TestDecisions:
    def test_lists_live_decisions(self) -> None:
        with (
            patch.object(_shared, "get_db", return_value=MagicMock()),
            patch.object(
                lexicon_repo,
                "live_decisions_by_uri",
                return_value={CONTACT_ROLE: {"label": "job title"}},
            ) as mk,
        ):
            resp = client.get("/api/v1/ontology/lexicon/decisions?ontology_id=o1")
        assert resp.status_code == 200
        assert resp.json()["data"][CONTACT_ROLE]["label"] == "job title"
        assert mk.call_args.kwargs["ontology_id"] == "o1"

    def test_returns_the_full_history_for_one_concept(self) -> None:
        rows = [
            {"label": "job title", "decided_by": "sam", "version": 2},
            {"label": "contact role", "decided_by": "arthur", "version": 1},
        ]
        with (
            patch.object(_shared, "get_db", return_value=MagicMock()),
            patch.object(lexicon_repo, "decision_history", return_value=rows) as mk,
        ):
            resp = client.get(
                "/api/v1/ontology/lexicon/decisions/history"
                f"?concept_uri={quote(CONTACT_ROLE, safe='')}"
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 2
        assert body["data"][0]["version"] == 2
        assert mk.call_args.kwargs["concept_uri"] == CONTACT_ROLE

    def test_history_requires_a_concept_uri(self) -> None:
        resp = client.get("/api/v1/ontology/lexicon/decisions/history")
        assert resp.status_code == 422

    def test_unencoded_fragment_uri_truncates_at_the_hash(self) -> None:
        # Concept URIs are fragment-style (``...#ContactRole``). An un-encoded
        # `#` in a query string is a client-side fragment and never reaches the
        # server, so the lookup silently searches for the namespace instead. Any
        # caller MUST percent-encode; pinned here so the trap is documented.
        with (
            patch.object(_shared, "get_db", return_value=MagicMock()),
            patch.object(lexicon_repo, "decision_history", return_value=[]) as mk,
        ):
            client.get(f"/api/v1/ontology/lexicon/decisions/history?concept_uri={CONTACT_ROLE}")
        assert mk.call_args.kwargs["concept_uri"] == "http://example.org/crm"

    def test_decisions_route_is_not_shadowed_by_the_collision_lookup(self) -> None:
        # /lexicon/decisions must not be captured by /lexicon/collisions/{key}.
        with (
            patch.object(_shared, "get_db", return_value=MagicMock()),
            patch.object(lexicon_repo, "live_decisions_by_uri", return_value={}),
            patch.object(lexicon_repo, "get_collision") as mk_collision,
        ):
            resp = client.get("/api/v1/ontology/lexicon/decisions")
        assert resp.status_code == 200
        mk_collision.assert_not_called()
