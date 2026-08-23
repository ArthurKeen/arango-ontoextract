"""Set actions: bulk reparent and introduce-superclass (FR-7.8.20).

A 667-class extraction is flat, and the single most valuable curation act is
selecting a cluster of siblings and giving them a parent. Doing that one class
at a time is why the taxonomy never gets built.

The property that matters most here is that a partial failure is REPORTED, not
swallowed: a cycle or a missing class must not silently strand the other
nineteen half-moved.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.api.errors import NotFoundError, ValidationError
from app.api.ontology import _shared, mutations
from app.main import app

client = TestClient(app)
URL = "/api/v1/ontology/o1/classes/bulk-reparent"


class TestValidation:
    def test_requires_a_parent(self) -> None:
        with patch.object(_shared, "get_db", return_value=MagicMock()):
            resp = client.post(URL, json={"class_keys": ["a", "b"]})
        assert resp.status_code == 400

    def test_rejects_both_parent_forms(self) -> None:
        with patch.object(_shared, "get_db", return_value=MagicMock()):
            resp = client.post(
                URL,
                json={"class_keys": ["a"], "new_parent_key": "P", "new_parent_label": "P"},
            )
        assert resp.status_code == 400

    def test_requires_at_least_one_class(self) -> None:
        with patch.object(_shared, "get_db", return_value=MagicMock()):
            resp = client.post(URL, json={"class_keys": [], "new_parent_key": "P"})
        assert resp.status_code == 422


class TestExistingParent:
    def test_moves_every_class(self) -> None:
        with (
            patch.object(_shared, "get_db", return_value=MagicMock()),
            patch.object(mutations, "_reparent_one", return_value={"reparented": True}) as mk,
        ):
            resp = client.post(URL, json={"class_keys": ["a", "b", "c"], "new_parent_key": "P"})
        body = resp.json()
        assert body["moved_count"] == 3
        assert body["failed_count"] == 0
        assert body["parent_key"] == "P"
        assert [c.kwargs["class_key"] for c in mk.call_args_list] == ["a", "b", "c"]

    def test_drops_the_parent_from_its_own_selection(self) -> None:
        # Lassoing a cluster often catches the intended parent too; that is not
        # an error, it just must not become its own superclass.
        with (
            patch.object(_shared, "get_db", return_value=MagicMock()),
            patch.object(mutations, "_reparent_one", return_value={}) as mk,
        ):
            body = client.post(
                URL, json={"class_keys": ["a", "P", "b"], "new_parent_key": "P"}
            ).json()
        assert body["moved"] == ["a", "b"]
        assert [c.kwargs["class_key"] for c in mk.call_args_list] == ["a", "b"]


class TestPartialFailure:
    def test_reports_failures_and_keeps_going(self) -> None:
        def side_effect(_db, *, ontology_id, class_key, new_parent_key):
            if class_key == "bad":
                raise ValidationError("would create a subclass_of cycle")
            return {"reparented": True}

        with (
            patch.object(_shared, "get_db", return_value=MagicMock()),
            patch.object(mutations, "_reparent_one", side_effect=side_effect),
        ):
            body = client.post(
                URL, json={"class_keys": ["a", "bad", "c"], "new_parent_key": "P"}
            ).json()
        assert body["moved"] == ["a", "c"]
        assert body["failed_count"] == 1
        assert body["failed"][0]["class_key"] == "bad"
        assert "cycle" in body["failed"][0]["reason"]

    def test_a_missing_class_does_not_abort_the_batch(self) -> None:
        def side_effect(_db, *, ontology_id, class_key, new_parent_key):
            if class_key == "ghost":
                raise NotFoundError("Class 'ghost' not found")
            return {}

        with (
            patch.object(_shared, "get_db", return_value=MagicMock()),
            patch.object(mutations, "_reparent_one", side_effect=side_effect),
        ):
            body = client.post(
                URL, json={"class_keys": ["ghost", "a"], "new_parent_key": "P"}
            ).json()
        assert body["moved"] == ["a"]
        assert body["failed_count"] == 1


class TestIntroduceSuperclass:
    def test_creates_the_parent_then_parents_everything_to_it(self) -> None:
        created = {"_key": "VehicleSystem", "label": "Vehicle System"}

        async def fake_create(_oid, _body):
            return created

        with (
            patch.object(_shared, "get_db", return_value=MagicMock()),
            patch.object(mutations, "create_class", side_effect=fake_create),
            patch.object(mutations, "_reparent_one", return_value={}) as mk,
        ):
            body = client.post(
                URL,
                json={"class_keys": ["a", "b"], "new_parent_label": "Vehicle System"},
            ).json()
        assert body["created_parent"] == created
        assert body["parent_key"] == "VehicleSystem"
        assert body["moved_count"] == 2
        # Everything must be parented to the class just created.
        assert {c.kwargs["new_parent_key"] for c in mk.call_args_list} == {"VehicleSystem"}


class TestUndo:
    """FR-7.8.21 — a structural set action must be reversible in one click."""

    def test_forward_call_returns_each_class_previous_parent(self) -> None:
        def side_effect(_db, *, ontology_id, class_key, new_parent_key):
            return {"expired_parent_ids": [f"ontology_classes/old_{class_key}"]}

        with (
            patch.object(_shared, "get_db", return_value=MagicMock()),
            patch.object(mutations, "_reparent_one", side_effect=side_effect),
        ):
            body = client.post(URL, json={"class_keys": ["a", "b"], "new_parent_key": "P"}).json()
        assert body["undo"] == [
            {"class_key": "a", "previous_parent_key": "old_a"},
            {"class_key": "b", "previous_parent_key": "old_b"},
        ]

    def test_a_class_with_no_previous_parent_records_none(self) -> None:
        # Restoring must be able to say "this had no parent", not guess one.
        with (
            patch.object(_shared, "get_db", return_value=MagicMock()),
            patch.object(mutations, "_reparent_one", return_value={"expired_parent_ids": []}),
        ):
            body = client.post(URL, json={"class_keys": ["a"], "new_parent_key": "P"}).json()
        assert body["undo"] == [{"class_key": "a", "previous_parent_key": None}]

    def test_failed_classes_are_not_in_the_undo_payload(self) -> None:
        # They were never moved, so "restoring" them would be a second edit.
        def side_effect(_db, *, ontology_id, class_key, new_parent_key):
            if class_key == "bad":
                raise ValidationError("cycle")
            return {"expired_parent_ids": ["ontology_classes/old"]}

        with (
            patch.object(_shared, "get_db", return_value=MagicMock()),
            patch.object(mutations, "_reparent_one", side_effect=side_effect),
        ):
            body = client.post(URL, json={"class_keys": ["a", "bad"], "new_parent_key": "P"}).json()
        assert [u["class_key"] for u in body["undo"]] == ["a"]

    def test_undo_restores_each_previous_parent(self) -> None:
        with (
            patch.object(_shared, "get_db", return_value=MagicMock()),
            patch.object(mutations, "_reparent_one", return_value={}) as mk,
        ):
            body = client.post(
                f"{URL}/undo",
                json={
                    "entries": [
                        {"class_key": "a", "previous_parent_key": "old_a"},
                        {"class_key": "b", "previous_parent_key": None},
                    ]
                },
            ).json()
        assert body["restored_count"] == 2
        calls = {c.kwargs["class_key"]: c.kwargs["new_parent_key"] for c in mk.call_args_list}
        assert calls == {"a": "old_a", "b": None}

    def test_undo_reports_partial_failure_rather_than_claiming_success(self) -> None:
        def side_effect(_db, *, ontology_id, class_key, new_parent_key):
            if class_key == "gone":
                raise NotFoundError("Class 'gone' not found")
            return {}

        with (
            patch.object(_shared, "get_db", return_value=MagicMock()),
            patch.object(mutations, "_reparent_one", side_effect=side_effect),
        ):
            body = client.post(
                f"{URL}/undo",
                json={
                    "entries": [
                        {"class_key": "a", "previous_parent_key": "p"},
                        {"class_key": "gone", "previous_parent_key": "p"},
                    ]
                },
            ).json()
        assert body["restored"] == ["a"]
        assert body["failed"][0]["class_key"] == "gone"

    def test_undo_requires_at_least_one_entry(self) -> None:
        with patch.object(_shared, "get_db", return_value=MagicMock()):
            assert client.post(f"{URL}/undo", json={"entries": []}).status_code == 422

    def test_a_forward_then_undo_round_trip_is_symmetric(self) -> None:
        seen: list[tuple[str, str | None]] = []

        def side_effect(_db, *, ontology_id, class_key, new_parent_key):
            seen.append((class_key, new_parent_key))
            return {"expired_parent_ids": ["ontology_classes/orig"]}

        with (
            patch.object(_shared, "get_db", return_value=MagicMock()),
            patch.object(mutations, "_reparent_one", side_effect=side_effect),
        ):
            fwd = client.post(URL, json={"class_keys": ["a"], "new_parent_key": "NEW"}).json()
            client.post(f"{URL}/undo", json={"entries": fwd["undo"]})
        assert seen == [("a", "NEW"), ("a", "orig")]
