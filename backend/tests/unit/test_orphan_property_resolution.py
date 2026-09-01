"""Curator actions on an orphan object property.

The repair overlay could only APPLY a range the matcher had inferred. When it
inferred nothing — 12 of WTW Ontology's 12 orphans — there was no action at
all, so the same properties reappeared on every scan with no way to record
that a human had looked at them.

Two conclusions a curator actually reaches, and now can act on:

* ``reject`` — it should not exist. ``HRPartner aligns_with_company_vision``
  is an assertion the extractor typed as a relation.
* ``set_range`` — it is real; the matcher just could not find the target.
"""

from __future__ import annotations

from typing import Any, ClassVar
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.api.ontology import _shared
from app.api.ontology import mutations as mut
from app.db.temporal_constants import NEVER_EXPIRES
from app.main import app

client = TestClient(app)
BASE = "/api/v1/ontology/wtw/orphan-properties/p1/resolve"


def _prop(**over: Any) -> dict[str, Any]:
    row = {
        "_key": "p1",
        "_id": "ontology_object_properties/p1",
        "ontology_id": "wtw",
        "label": "aligns with company vision",
        "expired": NEVER_EXPIRES,
        "extraction_run_id": "run_1",
    }
    row.update(over)
    return row


def _db(prop: dict[str, Any] | None, target: dict[str, Any] | None = None) -> MagicMock:
    db = MagicMock()
    db.has_collection.return_value = True
    cols: dict[str, MagicMock] = {}

    def collection(name: str) -> MagicMock:
        col = cols.setdefault(name, MagicMock())
        if name == "ontology_classes":
            col.get.return_value = target
        elif name == "ontology_object_properties":
            col.get.return_value = prop
        else:
            col.get.return_value = None
        return col

    db.collection.side_effect = collection
    return db


class TestReject:
    def test_routes_through_the_normal_curation_path(self) -> None:
        """So it expires temporally and lands in curation_decisions with
        attribution, exactly like rejecting a class — not a bespoke delete."""
        db = _db(_prop())
        with (
            patch.object(_shared, "get_db", return_value=db),
            patch.object(mut.curation_svc, "record_decision", return_value={"_key": "d1"}) as rec,
        ):
            resp = client.post(BASE, json={"action": "reject", "curator_id": "arthur"})

        assert resp.status_code == 200
        assert resp.json()["status"] == "rejected"
        kwargs = rec.call_args.kwargs
        assert kwargs["entity_type"] == "property"
        assert kwargs["action"] == "reject"
        assert kwargs["curator_id"] == "arthur"
        assert kwargs["entity_key"] == "p1"

    def test_curator_id_is_required(self) -> None:
        db = _db(_prop())
        with patch.object(_shared, "get_db", return_value=db):
            resp = client.post(BASE, json={"action": "reject"})
        assert resp.status_code == 422


class TestSetRange:
    TARGET: ClassVar[dict[str, Any]] = {
        "_key": "Vision",
        "_id": "ontology_classes/Vision",
        "ontology_id": "wtw",
    }

    def test_inserts_the_missing_range_edge(self) -> None:
        db = _db(_prop(), self.TARGET)
        with patch.object(_shared, "get_db", return_value=db):
            resp = client.post(
                BASE,
                json={
                    "action": "set_range",
                    "curator_id": "arthur",
                    "range_class_key": "Vision",
                },
            )

        assert resp.status_code == 200
        edge = db.collection("rdfs_range_class").insert.call_args[0][0]
        assert edge["_from"] == "ontology_object_properties/p1"
        assert edge["_to"] == "ontology_classes/Vision"
        assert edge["expired"] == NEVER_EXPIRES

    def test_records_that_a_human_chose_the_range(self) -> None:
        """Distinguishable from a matcher repair and from an extracted edge."""
        db = _db(_prop(), self.TARGET)
        with patch.object(_shared, "get_db", return_value=db):
            client.post(
                BASE,
                json={
                    "action": "set_range",
                    "curator_id": "arthur",
                    "range_class_key": "Vision",
                    "notes": "points at the vision statement",
                },
            )

        meta = db.collection("rdfs_range_class").insert.call_args[0][0]["repair_meta"]
        assert meta["source"] == "curator"
        assert meta["curator_id"] == "arthur"
        assert meta["notes"] == "points at the vision statement"

    def test_range_class_key_is_required(self) -> None:
        db = _db(_prop(), self.TARGET)
        with patch.object(_shared, "get_db", return_value=db):
            resp = client.post(BASE, json={"action": "set_range", "curator_id": "a"})
        assert resp.status_code == 400

    def test_unknown_range_class_is_404(self) -> None:
        db = _db(_prop(), None)
        with patch.object(_shared, "get_db", return_value=db):
            resp = client.post(
                BASE,
                json={"action": "set_range", "curator_id": "a", "range_class_key": "Nope"},
            )
        assert resp.status_code == 404

    def test_range_class_from_another_ontology_is_rejected(self) -> None:
        db = _db(_prop(), {**self.TARGET, "ontology_id": "other"})
        with patch.object(_shared, "get_db", return_value=db):
            resp = client.post(
                BASE,
                json={"action": "set_range", "curator_id": "a", "range_class_key": "Vision"},
            )
        assert resp.status_code == 400


class TestGuards:
    def test_unknown_property_is_404(self) -> None:
        with patch.object(_shared, "get_db", return_value=_db(None)):
            resp = client.post(BASE, json={"action": "reject", "curator_id": "a"})
        assert resp.status_code == 404

    def test_property_from_another_ontology_is_rejected(self) -> None:
        with patch.object(_shared, "get_db", return_value=_db(_prop(ontology_id="other"))):
            resp = client.post(BASE, json={"action": "reject", "curator_id": "a"})
        assert resp.status_code == 400

    def test_already_expired_property_is_rejected(self) -> None:
        with patch.object(_shared, "get_db", return_value=_db(_prop(expired=123.0))):
            resp = client.post(BASE, json={"action": "reject", "curator_id": "a"})
        assert resp.status_code == 400

    def test_unknown_action_is_rejected(self) -> None:
        with patch.object(_shared, "get_db", return_value=_db(_prop())):
            resp = client.post(BASE, json={"action": "delete", "curator_id": "a"})
        assert resp.status_code == 422
