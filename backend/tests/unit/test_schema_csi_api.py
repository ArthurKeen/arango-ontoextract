"""Unit tests for the CSI import API routes.

Pins the wire contract for:
  * POST /api/v1/ontology/schema/csi/preview
  * POST /api/v1/ontology/schema/csi/import

Patches at the usage site (``app.api.ontology.schema_csi``), per the mock-fidelity rule,
so the routes are exercised end-to-end without a live ArangoDB connection.
"""

from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.services.csi_import import CsiValidationError

ROUTE_MODULE = "app.api.ontology.schema_csi"
client = TestClient(app)


def _doc() -> dict:
    return {
        "csiVersion": "1",
        "conceptualModel": {
            "entities": [{"name": "Account", "properties": [{"name": "id"}]}],
            "relationships": [],
        },
        "arangoPhysicalMapping": {
            "entities": {"Account": {"style": "COLLECTION", "collectionName": "accounts"}}
        },
        "provenance": {
            "producer": "r2g",
            "direction": "forward",
            "source": {"kind": "postgresql", "ref": "crm"},
        },
    }


def test_preview_route_returns_summary_without_database():
    resp = client.post("/api/v1/ontology/schema/csi/preview", json={"document": _doc()})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["valid"] is True
    assert body["entities"] == ["Account"]
    assert body["db_label"] == "crm"


def test_preview_route_reports_problems_as_200_with_valid_false():
    doc = _doc()
    doc["csiVersion"] = "9"
    resp = client.post("/api/v1/ontology/schema/csi/preview", json={"document": doc})
    assert resp.status_code == 200
    assert resp.json()["valid"] is False


def test_import_route_delegates_to_service():
    with patch(f"{ROUTE_MODULE}.import_csi_document") as svc:
        svc.return_value = {"run_id": "abc", "status": "completed", "ontology_id": "csi_crm_abc"}
        resp = client.post(
            "/api/v1/ontology/schema/csi/import", json={"document": _doc(), "db_label": "crm"}
        )
    assert resp.status_code == 200, resp.text
    assert resp.json()["ontology_id"] == "csi_crm_abc"
    config = svc.call_args.args[0]
    assert config.db_label == "crm"
    assert config.document["csiVersion"] == "1"


def test_import_route_maps_unreadable_document_to_400():
    err = CsiValidationError("csiVersion must be '1'")
    with patch(f"{ROUTE_MODULE}.import_csi_document", side_effect=err):
        resp = client.post("/api/v1/ontology/schema/csi/import", json={"document": _doc()})
    assert resp.status_code == 400
    assert "csiVersion" in resp.json()["detail"]


def test_import_route_maps_unexpected_failure_to_500():
    with patch(f"{ROUTE_MODULE}.import_csi_document", side_effect=RuntimeError("arango down")):
        resp = client.post("/api/v1/ontology/schema/csi/import", json={"document": _doc()})
    assert resp.status_code == 500
    assert "arango down" in resp.json()["detail"]


def test_import_route_rejects_missing_document():
    resp = client.post("/api/v1/ontology/schema/csi/import", json={"db_label": "crm"})
    assert resp.status_code == 422
