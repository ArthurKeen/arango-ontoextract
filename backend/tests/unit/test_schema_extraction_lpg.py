"""Unit tests for labeled-property-graph (LPG) schema extraction (FR-9.14 / FR-9.15).

The regression this pins: a single-collection LPG (one ``Node`` vertex collection
+ one ``relations`` edge collection, with types in a discriminator field) must
extract one class per *type value* — not a single ``Node`` class.

These fakes mirror the CORRECTED extractor:
  * ``_lpg_field_stats`` issues a ``UNIQUE(present)`` query and returns
    ``{sampled, present, num_distinct}`` (the old ``distinct`` object key was a
    reserved-word AQL syntax error that made every detection silently fail).
  * ``_lpg_distinct_values`` / predicate enumeration are FULL ``COLLECT`` passes.
  * collection ``type`` is the python-arango string ``"document"`` / ``"edge"``
    (``_col_is_edge`` also accepts the legacy int ``2`` / ``3``).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from rdflib import OWL, RDF, RDFS, Graph, Namespace

from app.services.schema_extraction import (
    LPG_TIER1_EDGE_FIELDS,
    LPG_TIER1_TYPE_FIELDS,
    SchemaExtractionConfig,
    _col_is_edge,
    _format_label,
    _lpg_detect_field,
    _lpg_discovery_hint,
    _lpg_extract_schema,
    _lpg_field_stats,
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
# python-arango reports collection type as a STRING; the extractor must classify
# "relations" as an edge collection despite the value not being the int 3.
_FINREFLECT_COLLECTIONS = [
    {"name": "Node", "type": "document"},
    {"name": "relations", "type": "edge"},
]


def _fake_run_aql(_db, query, bind_vars=None):
    """Dispatch the LPG extractor's AQL by query shape + bound collection/field.

    Vertex type field = ``label`` -> {Company, Filing}; edge label field = ``rel``
    -> {FILED}. Keeping the two distinct proves the predicate set is enumerated
    from the edge label field, not accidentally from the vertex type values.
    """
    bind_vars = bind_vars or {}
    col = bind_vars.get("@col")
    f = bind_vars.get("f")
    if "UNSET" in query:  # per-type datatype-property field sample
        t = bind_vars.get("t")
        return iter(
            {
                "Company": [{"label": "Company", "name": "Acme", "revenue": 1000000}],
                "Filing": [{"label": "Filing", "period": "Q3", "pages": 42}],
            }.get(t, [])
        )
    if "COLLECT pred =" in query:  # endpoint aggregation pass
        return iter([{"pred": "FILED", "f": "Company", "t": "Filing", "n": 5}])
    if "COLLECT v = d" in query:  # distinct field values (full COLLECT)
        if col == "relations" or f == "rel":
            return iter(["FILED"])
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


class TestColIsEdge:
    """The bug that reclassified every edge collection as a vertex collection:
    python-arango returns ``type`` as a string, the code compared against int 3."""

    def test_accepts_string_edge(self) -> None:
        assert _col_is_edge("edge") is True

    def test_accepts_legacy_int_edge(self) -> None:
        assert _col_is_edge(3) is True

    def test_rejects_document(self) -> None:
        assert _col_is_edge("document") is False
        assert _col_is_edge(2) is False
        assert _col_is_edge(None) is False


class TestFieldStats:
    """``_lpg_field_stats`` must NOT use the AQL reserved word ``distinct`` as an
    object key (that raised on every call, silently disabling detection)."""

    def test_returns_triple_and_uses_safe_object_key(self) -> None:
        captured: dict[str, str] = {}

        def fake(_db, query, bind_vars=None):
            captured["query"] = query
            return iter([{"sampled": 100, "present": 100, "num_distinct": 3}])

        db = MagicMock()
        with patch("app.services.schema_extraction.run_aql", side_effect=fake):
            got = _lpg_field_stats(db, "Node", "type")
        assert got == (100, 100, 3)
        # No bare ``distinct:`` object key survives (only the safe ``num_distinct``).
        assert "num_distinct" in captured["query"]
        assert "), distinct:" not in captured["query"]
        assert "vals), distinct" not in captured["query"]


class TestDetectField:
    def _fake(self, stats: dict[str, dict[str, int]], values: dict[str, list[str]] | None = None):
        values = values or {}

        def fake(_db, query, bind_vars=None):
            f = (bind_vars or {}).get("f")
            if "UNIQUE(present)" in query:  # _lpg_field_stats
                if f in stats:
                    return iter([stats[f]])
                return iter([{"sampled": 100, "present": 0, "num_distinct": 0}])
            if "COLLECT v = d" in query:  # _lpg_distinct_values (class-like check)
                return iter(values.get(f, []))
            return iter([])

        return fake

    def test_tier1_type_accepted_despite_high_cardinality(self) -> None:
        # THE FinReflectKG fix: a rich graph has MANY entity types. A Tier-1 field
        # named ``type`` must be accepted on coverage alone — a high distinct count
        # must NOT disqualify it (the old cardinality gate collapsed it to one
        # collection-named class).
        db = MagicMock()
        stats = {"type": {"sampled": 300, "present": 300, "num_distinct": 180}}
        with patch("app.services.schema_extraction.run_aql", side_effect=self._fake(stats)):
            got = _lpg_detect_field(db, "Node", ("type",), tier1=LPG_TIER1_TYPE_FIELDS)
        assert got == "type"

    def test_tier2_picks_categorical_over_high_cardinality_identifier(self) -> None:
        # With only Tier-2 candidates, the low-cardinality class-like field wins and
        # the near-unique identifier is rejected.
        db = MagicMock()
        stats = {
            "kind": {"sampled": 100, "present": 100, "num_distinct": 3},
            "name": {"sampled": 100, "present": 100, "num_distinct": 97},
        }
        values = {"kind": ["Company", "Person", "Filing"], "name": ["Acme", "Bob", "Q3"]}
        # 'name' first to prove selection is by shape, not candidate order.
        with patch("app.services.schema_extraction.run_aql", side_effect=self._fake(stats, values)):
            got = _lpg_detect_field(db, "Node", ("name", "kind"))
        assert got == "kind"

    def test_tier2_rejects_free_text_values(self) -> None:
        # Low cardinality but the values contain spaces/dots -> a display label, not
        # a class token -> rejected.
        db = MagicMock()
        stats = {"label": {"sampled": 100, "present": 100, "num_distinct": 3}}
        values = {"label": ["Acme Corp.", "Bob Smith", "Q3 2024"]}
        with patch("app.services.schema_extraction.run_aql", side_effect=self._fake(stats, values)):
            assert _lpg_detect_field(db, "Node", ("label",)) is None

    def test_rejects_identifier_field_entirely(self) -> None:
        db = MagicMock()
        stats = {"name": {"sampled": 100, "present": 100, "num_distinct": 100}}
        with patch("app.services.schema_extraction.run_aql", side_effect=self._fake(stats)):
            assert _lpg_detect_field(db, "Node", ("name",)) is None

    def test_rejects_sparse_field(self) -> None:
        # Present on <60% of docs -> not a reliable discriminator even if Tier-1.
        db = MagicMock()
        stats = {"type": {"sampled": 100, "present": 40, "num_distinct": 3}}
        with patch("app.services.schema_extraction.run_aql", side_effect=self._fake(stats)):
            assert _lpg_detect_field(db, "Node", ("type",), tier1=("type",)) is None


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
        # and the vertex type values did NOT leak in as predicates:
        assert (NS["Company"], RDF.type, OWL.ObjectProperty) not in g

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
    def test_suggests_lpg_with_the_categorical_type_field(self) -> None:
        db = MagicMock()

        def fake(_db, query, bind_vars=None):
            f = (bind_vars or {}).get("f")
            if "UNIQUE(present)" in query:  # _lpg_field_stats
                # 'type' is a Tier-1 discriminator (accepted on coverage).
                if f == "type":
                    return iter([{"sampled": 100, "present": 100, "num_distinct": 8}])
                return iter([{"sampled": 100, "present": 0, "num_distinct": 0}])
            if "COLLECT v = d" in query and f == "type":  # sample_types
                return iter(["ORG", "COMP", "GPE"])
            return iter([])

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
        assert hint["vertex_type_field"] == "type"  # not the high-cardinality name
        assert hint["edge_label_field"] == "type"
        assert hint["sample_types"] == ["COMP", "GPE", "ORG"]  # sorted distinct

    def test_edge_collection_classified_by_string_type(self) -> None:
        # A loose edge collection reported with the STRING type "edge" must be
        # probed as an edge (regression for the int-vs-string classification bug).
        db = MagicMock()
        seen_edge_probe = {"relations": False}

        def fake(_db, query, bind_vars=None):
            f = (bind_vars or {}).get("f")
            col = (bind_vars or {}).get("@col")
            if "UNIQUE(present)" in query:
                if col == "Node" and f == "type":
                    return iter([{"sampled": 100, "present": 100, "num_distinct": 5}])
                if col == "relations" and f == "type":
                    seen_edge_probe["relations"] = True
                    return iter([{"sampled": 100, "present": 100, "num_distinct": 6}])
                return iter([{"sampled": 100, "present": 0, "num_distinct": 0}])
            if "COLLECT v = d" in query and col == "Node":
                return iter(["ORG", "COMP"])
            return iter([])

        loose = [
            {"name": "Node", "type": "document"},
            {"name": "relations", "type": "edge"},
        ]
        with patch("app.services.schema_extraction.run_aql", side_effect=fake):
            hint = _lpg_discovery_hint(db, [], loose)
        assert hint["suggested"] is True
        assert hint["vertex_type_field"] == "type"
        assert hint["edge_label_field"] == "type"
        assert seen_edge_probe["relations"] is True  # edge collection WAS probed

    def test_not_suggested_when_no_categorical_field(self) -> None:
        db = MagicMock()
        with patch("app.services.schema_extraction.run_aql", side_effect=lambda *a, **k: iter([])):
            hint = _lpg_discovery_hint(db, [], [{"name": "logs", "type": "document"}])
        assert hint["suggested"] is False
        assert hint["vertex_type_field"] is None


class TestEndpointTypesFromEdge:
    def test_domain_range_from_edge_endpoint_type_fields_no_document_lookup(self) -> None:
        # Edges carry _fromType/_toType (arango-cypher-py GENERIC_WITH_TYPE); the
        # extractor must use them and NOT issue a DOCUMENT() endpoint lookup.
        db = MagicMock()
        db.graphs.return_value = _FINREFLECT_GRAPHS
        db.collections.return_value = _FINREFLECT_COLLECTIONS
        used_document_lookup = {"flag": False}

        def fake(_db, query, bind_vars=None):
            col = (bind_vars or {}).get("@col")
            if "DOCUMENT(e._from)" in query:
                used_document_lookup["flag"] = True
            if "ATTRIBUTES(e" in query:  # endpoint-type field detection
                return iter([["_from", "_to", "type", "_fromType", "_toType"]])
            if "COLLECT pred =" in query:  # endpoint aggregation
                return iter([{"pred": "FILED", "f": "Company", "t": "Filing", "n": 3}])
            if "COLLECT v = d" in query:  # distinct field values
                if col == "relations":
                    return iter(["FILED"])
                return iter(["Company", "Filing"])
            if "UNSET" in query:
                return iter([])
            return iter([])

        cfg = _config(vertex_type_field="type", edge_label_field="type", sample_fields=False)
        with patch("app.services.schema_extraction.run_aql", side_effect=fake):
            ttl, _ = _lpg_extract_schema(cfg, db=db)
        g = Graph()
        g.parse(data=ttl, format="turtle")

        assert (NS["FILED"], RDFS.domain, NS["Company"]) in g
        assert (NS["FILED"], RDFS.range, NS["Filing"]) in g
        assert used_document_lookup["flag"] is False  # endpoints came from the edge


class TestTier1Constants:
    def test_tier1_subset_of_candidates(self) -> None:
        from app.services.schema_extraction import (
            LPG_EDGE_LABEL_CANDIDATES,
            LPG_VERTEX_TYPE_CANDIDATES,
        )

        assert set(LPG_TIER1_TYPE_FIELDS).issubset(set(LPG_VERTEX_TYPE_CANDIDATES))
        assert set(LPG_TIER1_EDGE_FIELDS).issubset(set(LPG_EDGE_LABEL_CANDIDATES))
        # camelCase entityType (FinReflectKG / arango-cypher-py convention) present:
        assert "entityType" in LPG_VERTEX_TYPE_CANDIDATES
