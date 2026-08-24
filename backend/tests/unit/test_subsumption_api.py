"""Subsumption review API — the flagged subClassOf queue (PRD §6.2 FR-2.20).

The judge's central promise is that it flags rather than deletes. These tests
pin the half of that promise the API owns: the flags are reachable, a curator's
ruling is recorded with attribution, and "detach" versions the edge away rather
than destroying it.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.api.ontology import _shared
from app.api.ontology import subsumption as api
from app.db.temporal_constants import NEVER_EXPIRES
from app.main import app

client = TestClient(app)

BASE = "/api/v1/ontology/onto_1/subsumption"


def _live_edge(**over: Any) -> dict[str, Any]:
    edge = {
        "_key": "e1",
        "_from": "ontology_classes/Airbag",
        "_to": "ontology_classes/SRS",
        "ontology_id": "onto_1",
        "expired": NEVER_EXPIRES,
        "subsumption_verdict": {
            "is_a": False,
            "relation": "part-of",
            "reason": "a component of the restraint system",
        },
    }
    edge.update(over)
    return edge


class _Cursor:
    """Stands in for a python-arango ``Cursor``.

    It is iterable and it raises on ``len()``, exactly as the real one does
    (``CursorCountError: cursor count not enabled``). An earlier version of
    these tests returned a plain list here; the endpoint called ``len()`` on
    the cursor and every request 500'd in production while the suite stayed
    green. The mock has to be able to fail the way the real thing fails.
    """

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def __iter__(self) -> Any:
        return iter(self._rows)

    def __len__(self) -> int:
        raise TypeError("cursor count not enabled")


def _db_with_edge(edge: dict[str, Any] | None) -> tuple[MagicMock, MagicMock]:
    db = MagicMock()
    db.has_collection.return_value = True
    col = MagicMock()
    col.get.return_value = edge
    db.collection.return_value = col
    return db, col


class TestFlaggedQueue:
    def test_returns_flagged_edges_with_both_labels(self) -> None:
        rows = [
            {
                "edge_key": "e1",
                "child_key": "Airbag",
                "child_label": "Airbag",
                "parent_key": "SRS",
                "parent_label": "Supplementary Restraint System",
                "relation": "part-of",
                "reason": "a component of the restraint system",
            }
        ]
        db = MagicMock()
        db.has_collection.return_value = True
        with (
            patch.object(_shared, "get_db", return_value=db),
            patch.object(_shared, "run_aql", return_value=_Cursor(rows)),
        ):
            resp = client.get(f"{BASE}/flagged")
        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 1
        # Labels, not keys: "Airbag -> Supplementary Restraint System" is
        # judgeable at a glance; a pair of document keys is not.
        assert body["data"][0]["parent_label"] == "Supplementary Restraint System"

    def test_query_excludes_passed_expired_and_already_ruled_edges(self) -> None:
        """A queue that re-raises settled questions stops being read."""
        db = MagicMock()
        db.has_collection.return_value = True
        with (
            patch.object(_shared, "get_db", return_value=db),
            patch.object(_shared, "run_aql", return_value=_Cursor([])) as aql,
        ):
            client.get(f"{BASE}/flagged")
        query = aql.call_args[0][1]
        assert "e.subsumption_verdict.is_a == false" in query
        assert "e.expired == @never" in query
        assert "e.subsumption_verdict.curator_decision == null" in query

    def test_empty_when_no_subclass_collection_yet(self) -> None:
        db = MagicMock()
        db.has_collection.return_value = False
        with patch.object(_shared, "get_db", return_value=db):
            resp = client.get(f"{BASE}/flagged")
        assert resp.status_code == 200
        assert resp.json() == {"data": [], "count": 0}


class TestResolve:
    def test_keep_leaves_the_edge_live_and_records_who_decided(self) -> None:
        db, col = _db_with_edge(_live_edge())
        with (
            patch.object(_shared, "get_db", return_value=db),
            patch.object(api.temporal_svc, "expire_entity") as expire,
        ):
            resp = client.post(
                f"{BASE}/e1/resolve",
                json={"action": "keep", "curator_id": "arthur", "note": "judge was wrong"},
            )
        assert resp.status_code == 200
        assert resp.json()["status"] == "kept"
        expire.assert_not_called()
        stamped = col.update.call_args[0][0]["subsumption_verdict"]
        assert stamped["curator_decision"]["curator_id"] == "arthur"
        assert stamped["curator_decision"]["note"] == "judge was wrong"
        # The original verdict is preserved, not overwritten -- the audit trail
        # needs to show what the judge said as well as what the curator ruled.
        assert stamped["relation"] == "part-of"

    def test_detach_expires_through_the_temporal_path(self) -> None:
        """Versioned removal, not a destructive delete: the timeline must still
        be able to show the edge as it was."""
        db, col = _db_with_edge(_live_edge())
        with (
            patch.object(_shared, "get_db", return_value=db),
            patch.object(api.temporal_svc, "expire_entity") as expire,
        ):
            resp = client.post(
                f"{BASE}/e1/resolve", json={"action": "detach", "curator_id": "arthur"}
            )
        assert resp.status_code == 200
        assert resp.json()["status"] == "detached"
        expire.assert_called_once()
        assert expire.call_args.kwargs["collection"] == "subclass_of"
        assert expire.call_args.kwargs["key"] == "e1"
        col.delete.assert_not_called()

    def test_unknown_edge_is_404(self) -> None:
        db, _ = _db_with_edge(None)
        with patch.object(_shared, "get_db", return_value=db):
            resp = client.post(
                f"{BASE}/nope/resolve", json={"action": "keep", "curator_id": "arthur"}
            )
        assert resp.status_code == 404

    def test_edge_from_another_ontology_is_rejected(self) -> None:
        db, _ = _db_with_edge(_live_edge(ontology_id="onto_2"))
        with patch.object(_shared, "get_db", return_value=db):
            resp = client.post(
                f"{BASE}/e1/resolve", json={"action": "keep", "curator_id": "arthur"}
            )
        assert resp.status_code == 400

    def test_already_expired_edge_is_rejected(self) -> None:
        db, _ = _db_with_edge(_live_edge(expired=123.0))
        with patch.object(_shared, "get_db", return_value=db):
            resp = client.post(
                f"{BASE}/e1/resolve", json={"action": "detach", "curator_id": "arthur"}
            )
        assert resp.status_code == 400

    def test_unknown_action_is_rejected(self) -> None:
        db, _ = _db_with_edge(_live_edge())
        with patch.object(_shared, "get_db", return_value=db):
            resp = client.post(
                f"{BASE}/e1/resolve", json={"action": "delete", "curator_id": "arthur"}
            )
        assert resp.status_code == 422

    def test_curator_id_is_required(self) -> None:
        """No anonymous rulings: an audit trail without a name is not one."""
        db, _ = _db_with_edge(_live_edge())
        with patch.object(_shared, "get_db", return_value=db):
            resp = client.post(f"{BASE}/e1/resolve", json={"action": "keep"})
        assert resp.status_code == 422


class TestCanvasFlag:
    """FR-2.20: the one bit the canvas renders, on both read paths.

    The canvas loads the effective-graph endpoint, not ``/edges``. A flag
    stamped on only one of them is invisible exactly where a curator is
    looking, so the rule lives in one shared helper and both paths call it.
    """

    def test_rejected_and_unruled_edge_is_flagged(self) -> None:
        from app.services.edge_confidence import mark_subsumption_flag

        edge = {"subsumption_verdict": {"is_a": False, "relation": "part-of"}}
        mark_subsumption_flag(edge)
        assert edge["subsumption_flagged"] is True

    def test_a_curator_ruling_clears_the_flag(self) -> None:
        from app.services.edge_confidence import mark_subsumption_flag

        edge = {
            "subsumption_verdict": {
                "is_a": False,
                "curator_decision": {"action": "keep", "curator_id": "arthur"},
            }
        }
        mark_subsumption_flag(edge)
        assert edge["subsumption_flagged"] is False

    def test_passing_and_unjudged_edges_are_not_flagged(self) -> None:
        """Absence of a verdict is not a failing verdict: every edge extracted
        before the judge existed must not paint the graph with warnings."""
        from app.services.edge_confidence import mark_subsumption_flag

        for verdict in ({"is_a": True}, None, {}, "nonsense"):
            edge: dict[str, Any] = {"subsumption_verdict": verdict}
            mark_subsumption_flag(edge)
            assert edge["subsumption_flagged"] is False, verdict

    def test_both_read_paths_use_the_shared_helper(self) -> None:
        import inspect

        from app.api.ontology import entities_read
        from app.services import ontology_effective

        for module in (entities_read, ontology_effective):
            assert "mark_subsumption_flag(" in inspect.getsource(module), module.__name__

    def test_the_flag_survives_the_canvas_projection(self) -> None:
        from app.services.ontology_projections import summarize_edge

        assert "subsumption_flagged" in summarize_edge({"subsumption_flagged": True})
