"""Unit tests for ontology creation and imports CRUD endpoints.

All database operations are mocked via monkeypatching.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

NEVER_EXPIRES = sys.maxsize


def _registry_doc(key: str = "test_ont", name: str = "Test Ontology", **extra):
    return {
        "_key": key,
        "_id": f"ontology_registry/{key}",
        "name": name,
        "label": name,
        "status": "active",
        "uri": f"http://example.org/ontology/{key}#",
        **extra,
    }


@pytest.fixture()
def _mock_db():
    db = MagicMock()
    db.has_collection.return_value = True
    db.aql.execute = MagicMock(side_effect=lambda *a, **kw: iter([]))
    return db


@pytest.fixture()
def client(_mock_db):
    with (
        patch("app.db.client.get_db", return_value=_mock_db),
        patch("app.api.ontology.get_db", return_value=_mock_db),
    ):
        from app.main import app

        yield TestClient(app)


# ── POST /create ──


class TestCreateOntology:
    def test_create_minimal(self, client, _mock_db):
        with patch(
            "app.db.registry_repo.get_registry_entry", return_value=None
        ), patch(
            "app.db.registry_repo.create_registry_entry",
            return_value=_registry_doc(key="ont_abc123", name="My Ontology"),
        ):
            resp = client.post(
                "/api/v1/ontology/create",
                json={"name": "My Ontology"},
            )

        assert resp.status_code == 201
        body = resp.json()
        assert body["ontology_id"] == "ont_abc123"
        assert body["name"] == "My Ontology"
        assert body["imports_created"] == []
        assert body["warnings"] == []

    def test_create_with_custom_id(self, client, _mock_db):
        with patch(
            "app.db.registry_repo.get_registry_entry", return_value=None
        ), patch(
            "app.db.registry_repo.create_registry_entry",
            return_value=_registry_doc(key="custom_id"),
        ):
            resp = client.post(
                "/api/v1/ontology/create",
                json={"name": "Custom", "ontology_id": "custom_id"},
            )

        assert resp.status_code == 201
        assert resp.json()["ontology_id"] == "custom_id"

    def test_create_conflict(self, client, _mock_db):
        with patch(
            "app.db.registry_repo.get_registry_entry",
            return_value=_registry_doc(key="existing"),
        ):
            resp = client.post(
                "/api/v1/ontology/create",
                json={"name": "Dup", "ontology_id": "existing"},
            )

        assert resp.status_code == 409

    def test_create_with_imports(self, client, _mock_db):
        call_count = {"n": 0}

        def mock_get_entry(key, *, db=None):
            if key == "target_ont":
                return _registry_doc(key="target_ont", name="Target")
            if call_count["n"] == 0:
                call_count["n"] += 1
                return None
            return _registry_doc()

        mock_edge = MagicMock(
            return_value={"_key": "e1", "_from": "a", "_to": "b"}
        )

        with patch(
            "app.db.registry_repo.get_registry_entry", side_effect=mock_get_entry
        ), patch(
            "app.db.registry_repo.create_registry_entry",
            return_value=_registry_doc(key="new_ont"),
        ), patch(
            "app.db.ontology_repo.create_edge", mock_edge
        ):
            resp = client.post(
                "/api/v1/ontology/create",
                json={"name": "Composed", "imports": ["target_ont"]},
            )

        assert resp.status_code == 201
        body = resp.json()
        assert len(body["imports_created"]) == 1
        assert body["imports_created"][0]["target"] == "target_ont"

    def test_create_empty_name_rejected(self, client):
        resp = client.post("/api/v1/ontology/create", json={"name": ""})
        assert resp.status_code == 422


# ── GET /{id}/imports ──


class TestListImports:
    def test_list_imports_ok(self, client, _mock_db):
        imports_data = [
            {
                "edge_key": "e1",
                "target_id": "target_ont",
                "target_name": "Target",
                "target_uri": "http://example.org/",
                "import_iri": "http://example.org/",
                "created": 1000.0,
            }
        ]
        _mock_db.aql.execute = MagicMock(return_value=iter(imports_data))

        with patch(
            "app.db.registry_repo.get_registry_entry",
            return_value=_registry_doc(),
        ):
            resp = client.get("/api/v1/ontology/test_ont/imports")

        assert resp.status_code == 200
        body = resp.json()
        assert len(body["imports"]) == 1
        assert body["imports"][0]["target_id"] == "target_ont"

    def test_list_imports_not_found(self, client, _mock_db):
        with patch(
            "app.db.registry_repo.get_registry_entry", return_value=None
        ):
            resp = client.get("/api/v1/ontology/nope/imports")

        assert resp.status_code == 404


# ── POST /{id}/imports ──


class TestAddImport:
    def test_add_import_ok(self, client, _mock_db):
        _mock_db.aql.execute = MagicMock(return_value=iter([]))

        with patch(
            "app.db.registry_repo.get_registry_entry",
            side_effect=lambda k, **kw: _registry_doc(key=k),
        ), patch(
            "app.db.ontology_repo.create_edge",
            return_value={"_key": "edge1", "_from": "a", "_to": "b"},
        ):
            resp = client.post(
                "/api/v1/ontology/src_ont/imports",
                json={"target_ontology_id": "tgt_ont"},
            )

        assert resp.status_code == 201
        body = resp.json()
        assert body["from"] == "src_ont"
        assert body["to"] == "tgt_ont"

    def test_add_import_self_rejected(self, client, _mock_db):
        with patch(
            "app.db.registry_repo.get_registry_entry",
            return_value=_registry_doc(key="same"),
        ):
            resp = client.post(
                "/api/v1/ontology/same/imports",
                json={"target_ontology_id": "same"},
            )

        assert resp.status_code == 400

    def test_add_import_target_not_found(self, client, _mock_db):
        def mock_get(key, **kw):
            if key == "src":
                return _registry_doc(key="src")
            return None

        with patch(
            "app.db.registry_repo.get_registry_entry", side_effect=mock_get
        ):
            resp = client.post(
                "/api/v1/ontology/src/imports",
                json={"target_ontology_id": "missing"},
            )

        assert resp.status_code == 404

    def test_add_import_duplicate_rejected(self, client, _mock_db):
        _mock_db.aql.execute = MagicMock(return_value=iter(["existing_edge"]))

        with patch(
            "app.db.registry_repo.get_registry_entry",
            side_effect=lambda k, **kw: _registry_doc(key=k),
        ):
            resp = client.post(
                "/api/v1/ontology/src/imports",
                json={"target_ontology_id": "tgt"},
            )

        assert resp.status_code == 409


# ── DELETE /{id}/imports/{target_id} ──


class TestRemoveImport:
    def test_remove_import_ok(self, client, _mock_db):
        edge_doc = {"_key": "e1", "_from": "a", "_to": "b", "expired": NEVER_EXPIRES}
        _mock_db.aql.execute = MagicMock(return_value=iter([edge_doc]))
        mock_col = MagicMock()
        _mock_db.collection.return_value = mock_col

        with patch("app.db.registry_repo.get_registry_entry", return_value=_registry_doc()):
            resp = client.delete("/api/v1/ontology/src/imports/tgt")

        assert resp.status_code == 200
        body = resp.json()
        assert body["removed"] == 1
        mock_col.update.assert_called_once()

    def test_remove_import_not_found(self, client, _mock_db):
        _mock_db.aql.execute = MagicMock(return_value=iter([]))

        resp = client.delete("/api/v1/ontology/src/imports/tgt")

        assert resp.status_code == 404
