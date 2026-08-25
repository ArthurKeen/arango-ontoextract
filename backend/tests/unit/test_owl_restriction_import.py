"""Unit tests for OWL restriction import (Stream 3 PR 2).

Two layers exercised here:

1. ``_extract_owl_restrictions`` -- pure rdflib walking; no DB. Pinned
   against the textbook ``rdfs:subClassOf [a owl:Restriction; ...]``
   pattern and the rarer ``owl:equivalentClass`` attachment.
2. ``_import_owl_restrictions`` -- full materialization with mocked
   ArangoDB. Verifies the row shape matches the PR 1 contract
   (``constraint_type="owl:Restriction"``, ``on_class`` as a full
   document id, ``property_id`` resolved or null, etc.).

We also pin the ``import_owl_to_graph`` integration point so the
returned stats dict carries ``restrictions_imported``.
"""

from __future__ import annotations

import contextlib
from unittest.mock import MagicMock, patch

from rdflib import Graph as RDFGraph

from app.db.temporal_constants import NEVER_EXPIRES
from app.services.arangordf_bridge import (
    _coerce_cardinality_int,
    _extract_owl_restrictions,
    _import_owl_restrictions,
    import_owl_to_graph,
)

# ---------------------------------------------------------------------------
# Fixture builder
# ---------------------------------------------------------------------------


def _parse(ttl: str) -> RDFGraph:
    g = RDFGraph()
    g.parse(data=ttl, format="turtle")
    return g


_PREFIXES = """\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix : <http://example.org/onto#> .
"""


# ---------------------------------------------------------------------------
# _extract_owl_restrictions
# ---------------------------------------------------------------------------


class TestExtractOwlRestrictions:
    def test_subclass_of_min_cardinality(self):
        ttl = (
            _PREFIXES
            + """
            :holder a owl:ObjectProperty .
            :Customer a owl:Class .
            :Account a owl:Class ;
                rdfs:subClassOf [
                    a owl:Restriction ;
                    owl:onProperty :holder ;
                    owl:minCardinality "1"^^xsd:nonNegativeInteger
                ] .
            """
        )

        rows = _extract_owl_restrictions(_parse(ttl))

        assert len(rows) == 1
        row = rows[0]
        assert row["class_uri"] == "http://example.org/onto#Account"
        assert row["property_uri"] == "http://example.org/onto#holder"
        assert row["restriction_type"] == "minCardinality"
        assert row["restriction_value"] == 1
        assert row["attachment"] == "subClassOf"

    def test_min_and_max_emit_two_rows(self):
        ttl = (
            _PREFIXES
            + """
            :holder a owl:ObjectProperty .
            :Account a owl:Class ;
                rdfs:subClassOf [
                    a owl:Restriction ;
                    owl:onProperty :holder ;
                    owl:minCardinality 1
                ] , [
                    a owl:Restriction ;
                    owl:onProperty :holder ;
                    owl:maxCardinality 5
                ] .
            """
        )

        rows = _extract_owl_restrictions(_parse(ttl))

        kinds = sorted(r["restriction_type"] for r in rows)
        assert kinds == ["maxCardinality", "minCardinality"]
        # Both row dicts must reference the SAME (class, property) pair --
        # this is exactly the input shape the rule engine groups on.
        assert {(r["class_uri"], r["property_uri"]) for r in rows} == {
            ("http://example.org/onto#Account", "http://example.org/onto#holder")
        }
        # Bare untyped literal "1" must coerce to int.
        values = sorted(int(r["restriction_value"]) for r in rows)
        assert values == [1, 5]

    def test_exact_cardinality(self):
        ttl = (
            _PREFIXES
            + """
            :id a owl:DatatypeProperty .
            :Customer a owl:Class ;
                rdfs:subClassOf [
                    a owl:Restriction ;
                    owl:onProperty :id ;
                    owl:cardinality 1
                ] .
            """
        )
        rows = _extract_owl_restrictions(_parse(ttl))
        assert len(rows) == 1
        assert rows[0]["restriction_type"] == "cardinality"
        assert rows[0]["restriction_value"] == 1

    def test_all_values_from_carries_target_class_uri(self):
        ttl = (
            _PREFIXES
            + """
            :nationality a owl:ObjectProperty .
            :Country a owl:Class .
            :Person a owl:Class ;
                rdfs:subClassOf [
                    a owl:Restriction ;
                    owl:onProperty :nationality ;
                    owl:allValuesFrom :Country
                ] .
            """
        )
        rows = _extract_owl_restrictions(_parse(ttl))
        assert len(rows) == 1
        assert rows[0]["restriction_type"] == "allValuesFrom"
        assert rows[0]["restriction_value"] == "http://example.org/onto#Country"

    def test_some_values_from_supported(self):
        ttl = (
            _PREFIXES
            + """
            :member a owl:ObjectProperty .
            :Club a owl:Class .
            :Person a owl:Class ;
                rdfs:subClassOf [
                    a owl:Restriction ;
                    owl:onProperty :member ;
                    owl:someValuesFrom :Club
                ] .
            """
        )
        rows = _extract_owl_restrictions(_parse(ttl))
        assert len(rows) == 1
        assert rows[0]["restriction_type"] == "someValuesFrom"
        assert rows[0]["restriction_value"] == "http://example.org/onto#Club"

    def test_has_value_literal(self):
        ttl = (
            _PREFIXES
            + """
            :status a owl:DatatypeProperty .
            :ActiveAccount a owl:Class ;
                rdfs:subClassOf [
                    a owl:Restriction ;
                    owl:onProperty :status ;
                    owl:hasValue "Open"
                ] .
            """
        )
        rows = _extract_owl_restrictions(_parse(ttl))
        assert len(rows) == 1
        assert rows[0]["restriction_type"] == "hasValue"
        assert rows[0]["restriction_value"] == "Open"

    def test_equivalent_class_attachment_also_walked(self):
        """A class *defined by* a restriction uses owl:equivalentClass, not
        rdfs:subClassOf."""
        ttl = (
            _PREFIXES
            + """
            :age a owl:DatatypeProperty .
            :HasAge a owl:Class ;
                owl:equivalentClass [
                    a owl:Restriction ;
                    owl:onProperty :age ;
                    owl:minCardinality 1
                ] .
            """
        )
        rows = _extract_owl_restrictions(_parse(ttl))
        assert len(rows) == 1
        assert rows[0]["attachment"] == "equivalentClass"
        assert rows[0]["restriction_type"] == "minCardinality"

    def test_named_superclass_not_treated_as_restriction(self):
        """``rdfs:subClassOf :Animal`` is just a parent class, not a
        blank-node restriction. Must not produce a constraint row."""
        ttl = (
            _PREFIXES
            + """
            :Animal a owl:Class .
            :Dog a owl:Class ; rdfs:subClassOf :Animal .
            """
        )
        rows = _extract_owl_restrictions(_parse(ttl))
        assert rows == []

    def test_qualified_cardinality_skipped_with_warning(self, caplog):
        """Qualified cardinality requires onClass/onDataRange scope and a
        wider wire shape -- deferred."""
        ttl = (
            _PREFIXES
            + """
            :holder a owl:ObjectProperty .
            :Customer a owl:Class .
            :Account a owl:Class ;
                rdfs:subClassOf [
                    a owl:Restriction ;
                    owl:onProperty :holder ;
                    owl:minQualifiedCardinality 1 ;
                    owl:onClass :Customer
                ] .
            """
        )
        with caplog.at_level("WARNING"):
            rows = _extract_owl_restrictions(_parse(ttl))
        assert rows == []
        assert any("qualified cardinality" in m.lower() for m in caplog.messages)

    def test_missing_on_property_skipped_with_warning(self, caplog):
        ttl = (
            _PREFIXES
            + """
            :Account a owl:Class ;
                rdfs:subClassOf [
                    a owl:Restriction ;
                    owl:minCardinality 1
                ] .
            """
        )
        with caplog.at_level("WARNING"):
            rows = _extract_owl_restrictions(_parse(ttl))
        assert rows == []
        assert any("owl:onProperty" in m for m in caplog.messages)

    def test_unrecognized_predicate_skipped_with_warning(self, caplog):
        """An owl:Restriction with no cardinality / value predicate at
        all -- e.g. only ``owl:onProperty`` -- is malformed."""
        ttl = (
            _PREFIXES
            + """
            :holder a owl:ObjectProperty .
            :Account a owl:Class ;
                rdfs:subClassOf [
                    a owl:Restriction ;
                    owl:onProperty :holder
                ] .
            """
        )
        with caplog.at_level("WARNING"):
            rows = _extract_owl_restrictions(_parse(ttl))
        assert rows == []
        assert any("no recognized restriction predicate" in m for m in caplog.messages)


# ---------------------------------------------------------------------------
# _coerce_cardinality_int
# ---------------------------------------------------------------------------


class TestCoerceCardinalityInt:
    def test_python_int(self):
        assert _coerce_cardinality_int(3) == 3

    def test_python_bool_rejected(self):
        # Python's ``True == 1`` but a literal bool here would mean the
        # rdflib parse picked up an ``xsd:boolean`` -- never a valid
        # cardinality.
        assert _coerce_cardinality_int(True) is None

    def test_typed_literal(self):
        from rdflib import XSD, Literal

        assert _coerce_cardinality_int(Literal("5", datatype=XSD.nonNegativeInteger)) == 5

    def test_untyped_digit_literal(self):
        from rdflib import Literal

        assert _coerce_cardinality_int(Literal("7")) == 7

    def test_non_numeric_literal_rejected(self):
        from rdflib import Literal

        assert _coerce_cardinality_int(Literal("five")) is None

    def test_random_object_rejected(self):
        assert _coerce_cardinality_int(object()) is None


# ---------------------------------------------------------------------------
# _import_owl_restrictions -- full materialization with mocked DB
# ---------------------------------------------------------------------------


def _mock_db_with_constraint_col() -> tuple[MagicMock, MagicMock]:
    """Return ``(db, constraint_col)`` with the constraint collection
    auto-routed and ``has_collection`` True for everything."""
    db = MagicMock()
    db.has_collection.return_value = True
    constraint_col = MagicMock()
    constraint_col.insert.return_value = {"_key": "auto"}

    def collection_router(name):  # type: ignore[no-untyped-def]
        if name == "ontology_constraints":
            return constraint_col
        return MagicMock()

    db.collection.side_effect = collection_router
    return db, constraint_col


class TestImportOwlRestrictions:
    def test_no_restrictions_returns_zero_and_writes_nothing(self):
        db, constraint_col = _mock_db_with_constraint_col()
        rdf_graph = _parse(_PREFIXES + ":Plain a owl:Class .\n")

        written = _import_owl_restrictions(
            db, rdf_graph=rdf_graph, ontology_id="onto_1", now=1000.0
        )

        assert written == 0
        constraint_col.insert.assert_not_called()

    def test_full_row_shape_matches_pr1_contract(self):
        db, constraint_col = _mock_db_with_constraint_col()

        rdf_graph = _parse(
            _PREFIXES
            + """
            :holder a owl:ObjectProperty .
            :Customer a owl:Class .
            :Account a owl:Class ;
                rdfs:subClassOf [
                    a owl:Restriction ;
                    owl:onProperty :holder ;
                    owl:minCardinality 1
                ] .
            """
        )

        # Two AQL passes: class id resolution, then property id resolution.
        responses = [
            iter(
                [
                    {
                        "uri": "http://example.org/onto#Account",
                        "id": "ontology_classes/Account",
                    }
                ]
            ),
            iter(
                [
                    {
                        "uri": "http://example.org/onto#holder",
                        "id": "ontology_object_properties/holder",
                    }
                ]
            ),
            # Datatype-property pass returns nothing (object props ran first).
            iter([]),
        ]

        def fake_run_aql(_db, _query, bind_vars):  # type: ignore[no-untyped-def]
            return responses.pop(0)

        with patch("app.services.arangordf_bridge.run_aql", side_effect=fake_run_aql):
            written = _import_owl_restrictions(
                db,
                rdf_graph=rdf_graph,
                ontology_id="onto_1",
                now=1234.0,
            )

        assert written == 1
        constraint_col.insert.assert_called_once()
        doc = constraint_col.insert.call_args[0][0]

        # PR 1 wire-shape contract -- these field names MUST match
        # ``app.services.extraction._materialize_to_graph``.
        assert doc["constraint_type"] == "owl:Restriction"
        assert doc["on_class"] == "ontology_classes/Account"
        assert doc["property_id"] == "ontology_object_properties/holder"
        assert doc["property_uri"] == "http://example.org/onto#holder"
        assert doc["restriction_type"] == "minCardinality"
        assert doc["restriction_value"] == 1
        assert doc["ontology_id"] == "onto_1"
        assert doc["expired"] == NEVER_EXPIRES
        assert doc["created"] == 1234.0
        # PR 2-specific provenance marker so import rows are
        # distinguishable from extraction rows.
        assert doc["import_source"] == "owl_restriction"
        assert doc["confidence"] == 1.0
        # PR 1 rows have ``extraction_run_id``; import rows must NOT, so
        # the source is unambiguous.
        assert "extraction_run_id" not in doc

    def test_unresolved_class_skipped(self, caplog):
        """A restriction targeting a class that didn't make it into
        ``ontology_classes`` after import is dropped -- the rule engine
        joins on ``on_class``, so an orphan row would never fire."""
        db, constraint_col = _mock_db_with_constraint_col()
        rdf_graph = _parse(
            _PREFIXES
            + """
            :holder a owl:ObjectProperty .
            :Account a owl:Class ;
                rdfs:subClassOf [
                    a owl:Restriction ;
                    owl:onProperty :holder ;
                    owl:minCardinality 1
                ] .
            """
        )

        # Empty class lookup, empty property lookups.
        with (
            patch(
                "app.services.arangordf_bridge.run_aql",
                side_effect=lambda *a, **k: iter([]),
            ),
            caplog.at_level("WARNING"),
        ):
            written = _import_owl_restrictions(
                db, rdf_graph=rdf_graph, ontology_id="onto_1", now=1.0
            )

        assert written == 0
        constraint_col.insert.assert_not_called()
        assert any("not in ontology" in m for m in caplog.messages)

    def test_unresolved_property_persisted_with_null_property_id(self):
        """If the class resolves but the property doesn't, write the row
        with ``property_id=null`` so post-hoc repair can recover the
        link -- mirrors PR 1's resolver-miss path."""
        db, constraint_col = _mock_db_with_constraint_col()
        rdf_graph = _parse(
            _PREFIXES
            + """
            :nonexistent a owl:ObjectProperty .
            :Account a owl:Class ;
                rdfs:subClassOf [
                    a owl:Restriction ;
                    owl:onProperty :nonexistent ;
                    owl:minCardinality 1
                ] .
            """
        )

        responses = [
            iter(
                [
                    {
                        "uri": "http://example.org/onto#Account",
                        "id": "ontology_classes/Account",
                    }
                ]
            ),
            iter([]),  # object property lookup miss
            iter([]),  # datatype property lookup miss
        ]

        def fake_run_aql(_db, _query, bind_vars):  # type: ignore[no-untyped-def]
            return responses.pop(0)

        with patch("app.services.arangordf_bridge.run_aql", side_effect=fake_run_aql):
            written = _import_owl_restrictions(
                db, rdf_graph=rdf_graph, ontology_id="onto_1", now=1.0
            )

        assert written == 1
        doc = constraint_col.insert.call_args[0][0]
        assert doc["property_id"] is None
        assert doc["property_uri"] == "http://example.org/onto#nonexistent"
        assert doc["on_class"] == "ontology_classes/Account"


# ---------------------------------------------------------------------------
# import_owl_to_graph integration -- restrictions_imported in stats
# ---------------------------------------------------------------------------


class TestImportOwlToGraphReturnsRestrictionsCount:
    @patch("app.services.arangordf_bridge._ensure_named_graph")
    @patch("app.services.arangordf_bridge._tag_documents_with_ontology_id")
    @patch("app.services.arangordf_bridge._import_owl_restrictions")
    @patch("app.services.arangordf_bridge._ensure_arango_rdf")
    def test_stats_carries_restrictions_imported(
        self,
        mock_ensure_rdf,
        mock_import_restrictions,
        mock_tag,
        mock_ensure_graph,
    ):
        mock_ensure_rdf.return_value = MagicMock()
        mock_tag.return_value = 0
        mock_import_restrictions.return_value = 3
        db = MagicMock()

        ttl = """
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        <http://x> a owl:Class .
        """

        result = import_owl_to_graph(db, ttl_content=ttl, graph_name="g", ontology_id="onto_1")

        # The restriction hook runs once, with the parsed graph + the
        # active ontology id, and its return count surfaces verbatim in
        # the stats dict.
        mock_import_restrictions.assert_called_once()
        kwargs = mock_import_restrictions.call_args.kwargs
        assert kwargs["ontology_id"] == "onto_1"
        assert "rdf_graph" in kwargs
        assert result["restrictions_imported"] == 3


# ---------------------------------------------------------------------------
# Blank-node classes must never be materialized
# ---------------------------------------------------------------------------


class TestAnonymousClassExpressionsAreSkipped:
    """An ``owl:Restriction`` is a class expression, not a concept.

    Found by importing BFO 2020: 36 named classes came in alongside 48
    anonymous restriction nodes, each materialized as a "class" labelled with
    rdflib's internal hex id. Two thirds of the imported ontology was noise the
    curator would have had to recognise and delete by hand — and on the canvas
    it is indistinguishable from a real concept.
    """

    def _run(self, ttl: str):
        from app.services.arangordf_bridge import _import_with_rdflib_fallback

        db = MagicMock()
        db.has_collection.return_value = True
        created: list[dict] = []

        def _create_class(_db, *, ontology_id, data, created_by):
            created.append(data)
            return {"_id": f"ontology_classes/{len(created)}", "_key": str(len(created))}

        def _create_prop(_db, *, collection=None, ontology_id=None, data=None, created_by=None):
            return {"_id": f"{collection}/x", "_key": "x"}

        # Property/edge writing goes through the mocked db; a failure there
        # does not affect what we assert about classes.
        with (
            patch("app.services.arangordf_bridge.create_class", side_effect=_create_class),
            patch("app.services.arangordf_bridge._ensure_import_collections"),
            contextlib.suppress(Exception),
        ):
            _import_with_rdflib_fallback(db, rdf_graph=_parse(ttl), ontology_id="o1")
        return created

    def test_restriction_nodes_do_not_become_classes(self):
        ttl = (
            _PREFIXES
            + """
        :Tyre a owl:Class ;
            rdfs:subClassOf [ a owl:Restriction ;
                              owl:onProperty :hasPressure ;
                              owl:minCardinality "1"^^xsd:nonNegativeInteger ] .
        :hasPressure a owl:DatatypeProperty .
        """
        )
        labels = [c["label"] for c in self._run(ttl)]
        assert labels == ["Tyre"], f"anonymous restriction leaked in: {labels}"

    def test_named_classes_still_import(self):
        ttl = _PREFIXES + ":Tyre a owl:Class . :Vehicle a owl:Class .\n"
        assert sorted(c["label"] for c in self._run(ttl)) == ["Tyre", "Vehicle"]

    def test_intersection_members_do_not_become_classes(self):
        ttl = (
            _PREFIXES
            + """
        :WinterTyre a owl:Class ;
            owl:equivalentClass [ a owl:Class ;
                                  owl:intersectionOf ( :Tyre [ a owl:Restriction ;
                                        owl:onProperty :hasSeason ;
                                        owl:hasValue :Winter ] ) ] .
        :Tyre a owl:Class .
        :hasSeason a owl:ObjectProperty .
        """
        )
        labels = sorted(c["label"] for c in self._run(ttl))
        assert labels == ["Tyre", "WinterTyre"], f"anonymous nodes leaked in: {labels}"


# ---------------------------------------------------------------------------
# schema.org soft typing (domainIncludes / rangeIncludes)
# ---------------------------------------------------------------------------


class TestSchemaOrgSoftTyping:
    """Some ontologies type properties without rdfs:domain/range.

    SOSA/SSN declares ZERO ``rdfs:domain`` and one ``rdfs:range``; it uses
    ``schema:domainIncludes`` / ``rangeIncludes`` instead, deliberately, so the
    vocabulary can be reused without imposing entailments. Reading only the
    rdfs:* forms left all 36 of its object properties as unconnected vertices
    and made the Sensor/Observation/FeatureOfInterest pattern invisible.

    The two predicates are NOT interchangeable, so every edge records which one
    produced it.
    """

    def _edges(self, ttl: str):
        from app.services.arangordf_bridge import _import_with_rdflib_fallback

        db = MagicMock()
        db.has_collection.return_value = True
        created: list[dict] = []
        counter = {"n": 0}

        def _create_class(_db, *, ontology_id, data, created_by):
            counter["n"] += 1
            return {"_id": f"ontology_classes/{data['uri']}", "_key": str(counter["n"])}

        def _create_property(_db, *, ontology_id, data, created_by, collection):
            return {"_id": f"{collection}/{data['uri']}", "_key": data["uri"]}

        def _create_edge(_db, *, edge_collection, from_id, to_id, data):
            created.append(
                {
                    "col": edge_collection,
                    "from": from_id,
                    "to": to_id,
                    "assertion": data.get("assertion"),
                }
            )
            return {"_id": "e/1"}

        with (
            patch("app.services.arangordf_bridge.create_class", side_effect=_create_class),
            patch("app.services.arangordf_bridge.create_property", side_effect=_create_property),
            patch("app.services.arangordf_bridge.create_edge", side_effect=_create_edge),
            patch("app.services.arangordf_bridge._ensure_import_collections"),
        ):
            _import_with_rdflib_fallback(db, rdf_graph=_parse(ttl), ontology_id="o1")
        return created

    SOSA = (
        _PREFIXES
        + """
    @prefix schema: <http://schema.org/> .
    :Observation a owl:Class .
    :Actuation a owl:Class .
    :FeatureOfInterest a owl:Class .
    :Sample a owl:Class .
    :hasFeatureOfInterest a owl:ObjectProperty ;
        schema:domainIncludes :Observation, :Actuation ;
        schema:rangeIncludes :FeatureOfInterest, :Sample .
    """
    )

    def test_soft_typing_produces_domain_and_range_edges(self):
        edges = self._edges(self.SOSA)
        domains = [e for e in edges if e["col"] == "rdfs_domain"]
        ranges = [e for e in edges if e["col"] == "rdfs_range_class"]

        assert len(domains) == 2, "both domainIncludes values must be edges"
        assert len(ranges) == 2, "both rangeIncludes values must be edges"

    def test_every_edge_records_which_predicate_produced_it(self):
        """rdfs:domain entails; schema:domainIncludes explicitly does not.
        Conflating them would let an export assert something SOSA never said."""
        edges = self._edges(self.SOSA)

        assert {e["assertion"] for e in edges if e["col"] == "rdfs_domain"} == {
            "schema:domainIncludes"
        }
        assert {e["assertion"] for e in edges if e["col"] == "rdfs_range_class"} == {
            "schema:rangeIncludes"
        }

    def test_rdfs_domain_still_wins_and_is_labelled_as_itself(self):
        ttl = (
            _PREFIXES
            + """
        @prefix schema: <http://schema.org/> .
        :Sensor a owl:Class .
        :Observation a owl:Class .
        :Decoy a owl:Class .
        :madeObservation a owl:ObjectProperty ;
            rdfs:domain :Sensor ;
            rdfs:range :Observation ;
            schema:domainIncludes :Decoy .
        """
        )
        edges = self._edges(ttl)
        domains = [e for e in edges if e["col"] == "rdfs_domain"]

        # The hard assertion wins outright; the soft one is a FALLBACK, never a
        # supplement, or the two semantics would be blurred together.
        assert len(domains) == 1
        assert domains[0]["assertion"] == "rdfs:domain"
        assert domains[0]["to"].endswith("Sensor")

    def test_https_schema_namespace_is_read_too(self):
        ttl = (
            _PREFIXES
            + """
        @prefix schema: <https://schema.org/> .
        :A a owl:Class .
        :B a owl:Class .
        :p a owl:ObjectProperty ;
            schema:domainIncludes :A ;
            schema:rangeIncludes :B .
        """
        )
        edges = self._edges(ttl)

        assert len([e for e in edges if e["col"] == "rdfs_domain"]) == 1
        assert len([e for e in edges if e["col"] == "rdfs_range_class"]) == 1

    def test_soft_range_never_reaches_the_property_document(self):
        """Export turns the property's ``range`` field into an rdfs:range
        triple, so a soft value must not be written there."""
        from app.services.arangordf_bridge import _import_with_rdflib_fallback

        db = MagicMock()
        db.has_collection.return_value = True
        props: list[dict] = []

        with (
            patch("app.services.arangordf_bridge.create_class", return_value={"_id": "c/1"}),
            patch(
                "app.services.arangordf_bridge.create_property",
                side_effect=lambda _db, **kw: (
                    props.append(kw["data"]),
                    {"_id": "p/1"},
                )[1],
            ),
            patch("app.services.arangordf_bridge.create_edge", return_value={"_id": "e/1"}),
            patch("app.services.arangordf_bridge._ensure_import_collections"),
        ):
            _import_with_rdflib_fallback(db, rdf_graph=_parse(self.SOSA), ontology_id="o1")

        prop = next(p for p in props if p["uri"].endswith("hasFeatureOfInterest"))
        assert "range" not in prop


class TestInverseOfImport:
    """``owl:inverseOf`` states one fact in two directions.

    SOSA declares 35 such pairs and the importer ignored every one, so
    ``hasFeatureOfInterest`` and ``isFeatureOfInterestOf`` arrived as two
    unrelated properties and the canvas drew both — roughly half of SOSA's
    edges were one relation mirrored.
    """

    def _props(self, ttl: str) -> dict[str, dict]:
        from app.services.arangordf_bridge import _import_with_rdflib_fallback

        db = MagicMock()
        db.has_collection.return_value = True
        out: dict[str, dict] = {}

        def _create_property(_db, *, ontology_id, data, created_by, collection):
            out[data["uri"]] = data
            return {"_id": f"{collection}/{data['uri']}"}

        with (
            patch("app.services.arangordf_bridge.create_class", return_value={"_id": "c/1"}),
            patch("app.services.arangordf_bridge.create_property", side_effect=_create_property),
            patch("app.services.arangordf_bridge.create_edge", return_value={"_id": "e/1"}),
            patch("app.services.arangordf_bridge._ensure_import_collections"),
        ):
            _import_with_rdflib_fallback(db, rdf_graph=_parse(ttl), ontology_id="o1")
        return out

    ONE_WAY = (
        _PREFIXES
        + """
    :hasFeatureOfInterest a owl:ObjectProperty .
    :isFeatureOfInterestOf a owl:ObjectProperty ;
        owl:inverseOf :hasFeatureOfInterest .
    """
    )

    def test_declared_direction_is_recorded(self):
        props = self._props(self.ONE_WAY)

        assert props["http://example.org/onto#isFeatureOfInterestOf"]["inverse_of"] == (
            "http://example.org/onto#hasFeatureOfInterest"
        )

    def test_the_implicit_mirror_is_materialised(self):
        """owl:inverseOf is symmetric, but files state it once. Deriving the
        mirror here means consumers do one lookup instead of each re-deriving
        the symmetry, and half of them forgetting."""
        props = self._props(self.ONE_WAY)

        assert props["http://example.org/onto#hasFeatureOfInterest"]["inverse_of"] == (
            "http://example.org/onto#isFeatureOfInterestOf"
        )

    def test_property_without_an_inverse_has_no_field(self):
        props = self._props(_PREFIXES + ":observes a owl:ObjectProperty .\n")

        assert "inverse_of" not in props["http://example.org/onto#observes"]

    def test_real_sosa_bundle_declares_pairs_symmetrically(self):
        """Guards the bundle as well as the code: if a future refresh of the
        SOSA file drops its inverse axioms, the canvas silently doubles again."""
        import importlib.resources as _resources

        from rdflib import OWL as _OWL

        from app.services.arangordf_bridge import _inverse_index

        raw = _resources.files("app.data.ontologies").joinpath("sosa_ssn.ttl").read_bytes()
        g = _parse(raw.decode("utf-8"))
        index = _inverse_index(g)

        declared = len(list(g.triples((None, _OWL.inverseOf, None))))
        assert declared >= 30, f"SOSA bundle declares only {declared} inverse pairs"
        # Symmetric closure: every partner resolves back to its source.
        assert all(index[partner] == prop for prop, partner in index.items())
