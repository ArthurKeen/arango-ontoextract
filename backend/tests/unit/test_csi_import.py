"""Unit tests for app.services.csi_import.

The pure builder needs no database; ``rdflib`` parses the emitted Turtle to assert the
ontology shape and the provenance that keeps CSI correspondences as data. The import
flow is exercised with the database boundary monkeypatched, as the relational tests do.
"""

from __future__ import annotations

import json

import pytest

rdflib = pytest.importorskip("rdflib")
from rdflib import OWL, RDF, RDFS, Graph, Literal, Namespace  # noqa: E402

from app.services import csi_import as ci  # noqa: E402
from app.services.csi_import import (  # noqa: E402
    CsiImportConfig,
    CsiValidationError,
    build_csi_owl,
    import_csi_document,
    preview_csi_document,
    validate_csi_document,
)

NS = Namespace("http://aoe.example.org/schema/crm#")
AOE = Namespace("http://aoe.example.org/vocab#")
XSD = Namespace("http://www.w3.org/2001/XMLSchema#")


def _doc() -> dict:
    """A small forward CSI in the shape r2g/RSA emit, plus a LABEL entity and a
    GENERIC_WITH_TYPE relationship in the shape arangodb-schema-analyzer emits."""
    return {
        "csiVersion": "1",
        "conceptualModel": {
            "entities": [
                {
                    "name": "Account",
                    "labels": ["Account", "Customer"],
                    "properties": [{"name": "id"}, {"name": "accountId"}, {"name": "name"}],
                },
                {
                    "name": "Contact",
                    "labels": ["Contact"],
                    "properties": [
                        {"name": "id"},
                        {"name": "accountId"},
                        {"name": "email", "type": "string"},
                        {"name": "seq", "type": "integer"},
                    ],
                },
                {
                    "name": "Order",
                    "labels": ["Order"],
                    "properties": [{"name": "total", "type": "number"}],
                },
            ],
            "relationships": [
                {"type": "contactsToAccounts", "fromEntity": "Contact", "toEntity": "Account"},
                {"type": "placed", "fromEntity": "Order", "toEntity": "Any"},
            ],
            "joinKeys": [
                {
                    "key": "account_id",
                    "concept": "accountId",
                    "bindings": [
                        {"entity": "Account", "field": "account_id"},
                        {"entity": "Contact", "field": "account_id"},
                    ],
                }
            ],
        },
        "arangoPhysicalMapping": {
            "entities": {
                "Account": {
                    "style": "COLLECTION",
                    "collectionName": "accounts",
                    "properties": {
                        "id": {"field": "id"},
                        "accountId": {"field": "account_id"},
                        "name": {"field": "name"},
                    },
                },
                "Contact": {
                    "style": "COLLECTION",
                    "collectionName": "contacts",
                    "properties": {
                        "accountId": {"field": "account_id"},
                        "email": {"field": "email_addr"},
                    },
                },
                "Order": {
                    "style": "LABEL",
                    "collectionName": "entities",
                    "typeField": "type",
                    "typeValue": "order",
                },
            },
            "relationships": {
                "contactsToAccounts": {
                    "style": "DEDICATED_COLLECTION",
                    "edgeCollectionName": "contacts_to_accounts",
                },
                "placed": {
                    "style": "GENERIC_WITH_TYPE",
                    "edgeCollectionName": "edges",
                    "typeField": "type",
                    "typeValue": "placed",
                },
            },
        },
        "provenance": {
            "producer": "r2g",
            "producerVersion": "0.4.1",
            "direction": "forward",
            "source": {"kind": "postgresql", "ref": "crm", "fingerprint": "sha256:abc"},
            "generatedAt": "2026-09-14T10:00:00+00:00",
            "transactionTime": "2026-09-14T09:59:00+00:00",
            "validTime": {"from": "2026-06-01T00:00:00+00:00"},
            "validTimeSource": "catalog",
            "predecessorFingerprint": "sha256:prev",
        },
    }


def _graph(doc: dict | None = None) -> tuple[Graph, dict[str, str]]:
    ttl, uri_to_collection = build_csi_owl(doc or _doc(), db_label="crm")
    g = Graph()
    g.parse(data=ttl, format="turtle")
    return g, uri_to_collection


# ── Builder: shape ───────────────────────────────────────────────────────────


def test_entities_become_classes_with_collection_provenance():
    g, uri_to_collection = _graph()
    classes = set(g.subjects(RDF.type, OWL.Class))
    assert classes == {NS.Account, NS.Contact, NS.Order}
    assert (NS.Account, RDFS.label, Literal("Account")) in g
    assert (NS.Account, AOE.sourceDb, Literal("crm")) in g
    assert (NS.Account, AOE.sourceCollection, Literal("accounts")) in g
    assert (NS.Account, AOE.csiMappingStyle, Literal("COLLECTION")) in g
    assert (
        NS.Account,
        AOE.csiLabel,
        Literal("Customer"),
    ) in g  # alt label kept, name not duplicated
    assert (NS.Account, AOE.csiLabel, Literal("Account")) not in g
    assert uri_to_collection[str(NS.Account)] == "accounts"


def test_label_style_entity_records_the_analyzers_discriminator_not_a_redetection():
    g, uri_to_collection = _graph()
    assert (NS.Order, AOE.csiMappingStyle, Literal("LABEL")) in g
    assert (NS.Order, AOE.lpgTypeField, Literal("type")) in g
    assert (NS.Order, AOE.lpgTypeValue, Literal("order")) in g
    assert uri_to_collection[str(NS.Order)] == "entities"


def test_properties_become_datatype_properties_with_domain_range_and_field():
    g, _ = _graph()
    email = NS["Contact.email"]
    assert (email, RDF.type, OWL.DatatypeProperty) in g
    assert (email, RDFS.domain, NS.Contact) in g
    assert (email, RDFS.range, XSD.string) in g
    # The property->column correspondence is data, not a naming convention.
    assert (email, AOE.sourceField, Literal("email_addr")) in g
    assert (email, AOE.csiProperty, Literal("email")) in g
    assert (NS["Contact.seq"], RDFS.range, XSD.integer) in g
    assert (NS["Order.total"], RDFS.range, XSD.decimal) in g
    # r2g emits property names only: range defaults to string, and an unmapped field
    # produces no sourceField rather than a guess.
    assert (NS["Account.name"], RDFS.range, XSD.string) in g
    assert (NS["Contact.id"], RDFS.range, XSD.string) in g
    assert not list(g.objects(NS["Contact.id"], AOE.sourceField))


def test_join_keys_mark_bound_properties():
    g, _ = _graph()
    assert (NS["Account.accountId"], AOE.joinKey, Literal("account_id")) in g
    assert (NS["Contact.accountId"], AOE.joinKey, Literal("account_id")) in g
    assert not list(g.objects(NS["Account.name"], AOE.joinKey))


def test_relationships_become_object_properties_with_endpoints_and_edge_provenance():
    g, uri_to_collection = _graph()
    rel = NS.contactsToAccounts
    assert (rel, RDF.type, OWL.ObjectProperty) in g
    assert (rel, RDFS.domain, NS.Contact) in g
    assert (rel, RDFS.range, NS.Account) in g
    assert (rel, AOE.sourceCollection, Literal("contacts_to_accounts")) in g
    assert (rel, AOE.csiMappingStyle, Literal("DEDICATED_COLLECTION")) in g
    assert uri_to_collection[str(rel)] == "contacts_to_accounts"
    # Unresolved endpoint ("Any") asserts no range; GENERIC_WITH_TYPE keeps its label field.
    placed = NS.placed
    assert (placed, RDFS.domain, NS.Order) in g
    assert not list(g.objects(placed, RDFS.range))
    assert (placed, AOE.lpgLabelField, Literal("type")) in g
    assert (placed, AOE.lpgLabelValue, Literal("placed")) in g


def test_document_provenance_and_bitemporal_stamps_land_on_the_ontology_node():
    g, _ = _graph()
    ont = rdflib.URIRef("http://aoe.example.org/schema/crm")
    assert (ont, RDF.type, OWL.Ontology) in g
    assert (ont, AOE.csiProducer, Literal("r2g")) in g
    assert (ont, AOE.csiDirection, Literal("forward")) in g
    assert (ont, AOE.csiSourceKind, Literal("postgresql")) in g
    assert (ont, AOE.csiSourceRef, Literal("crm")) in g
    assert (ont, AOE.csiGeneratedAt, Literal("2026-09-14T10:00:00+00:00")) in g
    assert (ont, AOE.csiTransactionTime, Literal("2026-09-14T09:59:00+00:00")) in g
    assert (ont, AOE.csiValidFrom, Literal("2026-06-01T00:00:00+00:00")) in g
    assert (ont, AOE.csiValidTimeSource, Literal("catalog")) in g
    assert (ont, AOE.csiPredecessorFingerprint, Literal("sha256:prev")) in g


def test_imports_are_declared():
    ttl, _ = build_csi_owl(_doc(), db_label="crm", imports=["base-ont"])
    g = Graph()
    g.parse(data=ttl, format="turtle")
    ont = rdflib.URIRef("http://aoe.example.org/schema/crm")
    assert (ont, OWL.imports, rdflib.URIRef("http://example.org/ontology/base-ont")) in g


def test_builder_is_deterministic():
    a, _ = build_csi_owl(_doc(), db_label="crm")
    b, _ = build_csi_owl(json.loads(json.dumps(_doc())), db_label="crm")
    assert a == b


# ── Validation ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("mutate", "fragment"),
    [
        (lambda d: d.__setitem__("csiVersion", "2"), "csiVersion"),
        (lambda d: d.pop("conceptualModel"), "conceptualModel must be an object"),
        (lambda d: d["conceptualModel"].__setitem__("entities", []), "non-empty array"),
        (lambda d: d["conceptualModel"]["entities"].append({"name": ""}), "entities[3].name"),
        (
            lambda d: d["conceptualModel"]["relationships"].append(
                {"type": "x", "fromEntity": "A"}
            ),
            "toEntity",
        ),
        (lambda d: d.pop("arangoPhysicalMapping"), "arangoPhysicalMapping"),
        (lambda d: d.pop("provenance"), "provenance"),
    ],
)
def test_validation_reports_structural_problems(mutate, fragment):
    doc = _doc()
    mutate(doc)
    problems = validate_csi_document(doc)
    assert any(fragment in p for p in problems), problems
    with pytest.raises(CsiValidationError):
        build_csi_owl(doc, db_label="crm")


def test_validation_rejects_non_object():
    assert validate_csi_document("nope") == ["document must be a JSON object"]


def test_valid_document_has_no_problems():
    assert validate_csi_document(_doc()) == []


# ── Preview ──────────────────────────────────────────────────────────────────


def test_preview_summarises_without_touching_the_database():
    out = preview_csi_document(_doc())
    assert out["valid"] is True
    assert out["db_label"] == "crm"
    assert out["entities"] == ["Account", "Contact", "Order"]
    assert out["entity_count"] == 3
    assert out["property_count"] == 8
    assert out["relationship_count"] == 2
    assert out["join_keys"] == ["accountId"]
    assert out["entity_mapping_styles"] == {"COLLECTION": 2, "LABEL": 1}
    assert out["provenance"]["producer"] == "r2g"
    assert out["provenance"]["valid_time_source"] == "catalog"


def test_preview_returns_problems_instead_of_raising():
    doc = _doc()
    doc.pop("provenance")
    out = preview_csi_document(doc)
    assert out["valid"] is False
    assert any("provenance" in p for p in out["errors"])


# ── Import flow (database boundary monkeypatched) ────────────────────────────


def test_import_flow_builds_imports_and_stamps(monkeypatch):
    calls: dict[str, dict] = {}

    def fake_import_from_file(*, file_content, filename, ontology_id, db, ontology_label):
        calls["import"] = {
            "filename": filename,
            "ontology_id": ontology_id,
            "label": ontology_label,
            "ttl": file_content.decode("utf-8"),
        }
        return {"classes": 3, "properties": 10}

    def fake_stamp(db, *, ontology_id, source_db, source_host, uri_to_collection):
        calls["stamp"] = {
            "ontology_id": ontology_id,
            "source_db": source_db,
            "source_host": source_host,
            "uri_to_collection": uri_to_collection,
        }
        return len(uri_to_collection)

    monkeypatch.setattr(ci, "get_db", lambda: object())
    monkeypatch.setattr(ci, "import_from_file", fake_import_from_file)
    monkeypatch.setattr(ci, "_stamp_per_class_provenance", fake_stamp)

    result = import_csi_document(CsiImportConfig(document=_doc(), source_host="pg.example"))

    assert result["status"] == "completed"
    assert result["ontology_id"].startswith("csi_crm_")
    assert result["import_stats"] == {"classes": 3, "properties": 10}
    assert result["provenance"]["mode"] == "csi"
    assert result["provenance"]["producer"] == "r2g"
    assert result["provenance"]["db_label"] == "crm"
    assert result["provenance"]["valid_time_source"] == "catalog"
    assert calls["import"]["filename"] == "crm_csi.ttl"
    assert calls["import"]["ontology_id"] == result["ontology_id"]
    assert "owl:Class" in calls["import"]["ttl"]
    assert calls["stamp"]["source_db"] == "crm"
    assert calls["stamp"]["source_host"] == "pg.example"
    assert calls["stamp"]["uri_to_collection"][str(NS.Account)] == "accounts"
    assert result["provenance_stamped"] == 5


def test_import_flow_honours_explicit_ids_and_labels(monkeypatch):
    seen: dict[str, str] = {}
    monkeypatch.setattr(ci, "get_db", lambda: object())
    monkeypatch.setattr(
        ci,
        "import_from_file",
        lambda **kw: seen.update(ontology_id=kw["ontology_id"], label=kw["ontology_label"]) or {},
    )
    monkeypatch.setattr(ci, "_stamp_per_class_provenance", lambda *a, **kw: 0)
    result = import_csi_document(
        CsiImportConfig(
            document=_doc(), db_label="gold", ontology_id="ont-1", ontology_label="Gold"
        )
    )
    assert result["ontology_id"] == "ont-1"
    assert seen == {"ontology_id": "ont-1", "label": "Gold"}
    assert result["provenance"]["db_label"] == "gold"


def test_import_flow_rejects_unreadable_document_before_touching_the_database(monkeypatch):
    def boom(*a, **kw):
        raise AssertionError("database must not be touched")

    monkeypatch.setattr(ci, "get_db", boom)
    doc = _doc()
    doc.pop("conceptualModel")
    with pytest.raises(CsiValidationError):
        import_csi_document(CsiImportConfig(document=doc))
