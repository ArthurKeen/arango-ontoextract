"""Unit tests for labeled-property-graph (LPG) schema extraction (FR-9.14 / FR-9.15).

The regression this pins: a single-collection LPG (one ``Node`` vertex collection
+ one ``relations`` edge collection, with types in a discriminator field) must
extract one class per *type value* — not a single ``Node`` class.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from rdflib import OWL, RDF, RDFS, Graph, Namespace

from app.services.schema_extraction import (
    SchemaExtractionConfig,
    _format_label,
    _lpg_detect_field,
    _lpg_discovery_hint,
    _lpg_extract_schema,
)

NS = Namespace("http://aoe.example.org/schema/FinReflectKgOneShard#")

_FINREFLECT_GRAPHS = [
    {
        "name": "FinReflectKG",
        "edge_definitions": [
            {
                "edge_collection": "relations",
                "from_vertex_collections": ["Node"],
                "to_vertex_collections": ["Node"],
            }
        ],
        "orphan_collections": [],
    }
]
_FINREFLECT_COLLECTIONS = [{"name": "Node", "type": 2}, {"name": "relations", "type": 3}]


def _fake_run_aql(_db, query, bind_vars=None):
    """Dispatch the LPG extractor's AQL by shape."""
    bind_vars = bind_vars or {}
    if "UNSET" in query:  # per-type field sample
        t = bind_vars.get("t")
        return iter(
            {
                "Company": [{"label": "Company", "name": "Acme", "revenue": 1000000}],
                "Filing": [{"label": "Filing", "period": "Q3", "pages": 42}],
            }.get(t, [])
        )
    if "DOCUMENT(e._from)" in query:  # predicate + endpoint sample
        return iter([{"pred": "FILED", "f": "Company", "t": "Filing"}])
    if "COLLECT v = d" in query:  # distinct type-field values
        return iter(["Company", "Filing"])
    return iter([])


def _config(**kw) -> SchemaExtractionConfig:
    base = {
        "target_host": "http://host:8530",
        "target_db": "FinReflectKgOneShard",
        "lpg_mode": True,
        "vertex_type_field": "label",
        "edge_label_field": "rel",
        "graph_names": ["FinReflectKG"],
        "include_loose": False,
    }
    base.update(kw)
    return SchemaExtractionConfig(**base)


class TestFormatLabel:
    def test_formats(self) -> None:
        assert _format_label("financial_metric", "raw") == "financial_metric"
        assert _format_label("financial_metric", "title_case") == "Financial Metric"
        assert _format_label("COMPANY", "title_case") == "Company"
        assert _format_label("hasPart", "snake_case") == "has_part"
        assert _format_label("Has Part", "camel_case") == "hasPart"


class TestDetectField:
    def test_picks_field_with_most_distinct_values(self) -> None:
        db = MagicMock()

        def fake(_db, query, bind_vars=None):
            f = (bind_vars or {}).get("f")
            return iter({"label": ["A", "B", "C"], "type": ["X"]}.get(f, []))

        with patch("app.services.schema_extraction.run_aql", side_effect=fake):
            got = _lpg_detect_field(db, "Node", ("type", "label", "@type"))
        assert got == "label"  # 3 distinct > 1 distinct


class TestLpgExtract:
    def _extract(self, **cfg_kw) -> Graph:
        db = MagicMock()
        db.graphs.return_value = _FINREFLECT_GRAPHS
        db.collections.return_value = _FINREFLECT_COLLECTIONS
        with patch("app.services.schema_extraction.run_aql", side_effect=_fake_run_aql):
            ttl, _ = _lpg_extract_schema(_config(**cfg_kw), db=db)
        g = Graph()
        g.parse(data=ttl, format="turtle")
        return g

    def test_classes_come_from_type_values_not_the_collection(self) -> None:
        g = self._extract()
        classes = set(g.subjects(RDF.type, OWL.Class))
        # the real domain types, one per DISTINCT Node.label value:
        assert NS["Company"] in classes
        assert NS["Filing"] in classes
        # and crucially NOT a single catch-all Node class (the old bug):
        assert NS["Node"] not in classes

    def test_object_property_from_edge_label_with_domain_range(self) -> None:
        g = self._extract()
        assert (NS["FILED"], RDF.type, OWL.ObjectProperty) in g
        assert (NS["FILED"], RDFS.domain, NS["Company"]) in g
        assert (NS["FILED"], RDFS.range, NS["Filing"]) in g
        # the bare edge collection is NOT emitted as a property in LPG mode:
        assert (NS["relations"], RDF.type, OWL.ObjectProperty) not in g

    def test_datatype_properties_scoped_per_type(self) -> None:
        g = self._extract()
        # revenue sampled from Company docs -> domain Company
        assert (NS["Company.revenue"], RDF.type, OWL.DatatypeProperty) in g
        assert (NS["Company.revenue"], RDFS.domain, NS["Company"]) in g
        # period sampled from Filing docs -> domain Filing
        assert (NS["Filing.period"], RDFS.domain, NS["Filing"]) in g

    def test_label_format_applied_to_class_labels(self) -> None:
        g = self._extract(label_format="title_case")
        labels = {str(o) for o in g.objects(NS["Company"], RDFS.label)}
        assert "Company" in labels  # already title; verifies formatting path runs

    def test_no_type_field_falls_back_to_one_class(self) -> None:
        # vertex_type_field set but detection returns nothing -> collection class.
        db = MagicMock()
        db.graphs.return_value = _FINREFLECT_GRAPHS
        db.collections.return_value = _FINREFLECT_COLLECTIONS
        cfg = _config(vertex_type_field=None, edge_label_field=None)
        with patch("app.services.schema_extraction.run_aql", side_effect=lambda *a, **k: iter([])):
            ttl, _ = _lpg_extract_schema(cfg, db=db)
        g = Graph()
        g.parse(data=ttl, format="turtle")
        # no discriminator discoverable -> one class for the collection
        assert (NS["Node"], RDF.type, OWL.Class) in g


class TestDiscoveryHint:
    def test_suggests_lpg_when_categorical_field_present(self) -> None:
        db = MagicMock()

        def fake(_db, query, bind_vars=None):
            f = (bind_vars or {}).get("f")
            # 'label' is categorical on Node; edge 'label' present on relations
            return iter({"label": ["Company", "Filing", "Metric"]}.get(f, []))

        graphs = [
            {
                "name": "FinReflectKG",
                "edge_definitions": [{"edge_collection": "relations"}],
                "vertex_collections": ["Node"],
                "orphan_collections": [],
            }
        ]
        with patch("app.services.schema_extraction.run_aql", side_effect=fake):
            hint = _lpg_discovery_hint(db, graphs, [])
        assert hint["suggested"] is True
        assert hint["vertex_type_field"] == "label"
        assert "Company" in hint["sample_types"]

    def test_not_suggested_when_no_categorical_field(self) -> None:
        db = MagicMock()
        with patch("app.services.schema_extraction.run_aql", side_effect=lambda *a, **k: iter([])):
            hint = _lpg_discovery_hint(db, [], [{"name": "logs", "type": "document"}])
        assert hint["suggested"] is False
        assert hint["vertex_type_field"] is None
