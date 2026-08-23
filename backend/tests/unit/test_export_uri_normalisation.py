"""Export must not be taken down by one malformed URI (FR-2.19).

Reported: `GET /ontology/{id}/export?format=turtle` returned a 500. Cause:
`namespace#qualifiedPersonnel Recommended` — a RELATIVE IRI containing a space.
rdflib refuses to serialise it, so ONE bad value out of 6,322 live entities
broke the entire export of a 1688-class ontology.

93% of that corpus carries the `namespace#` placeholder the old extraction
prompt taught the model to emit. Normalising at export means legacy ontologies
serialise correctly without first being migrated.
"""

from __future__ import annotations

import pytest
from rdflib import Graph, URIRef

from app.services.export import _uri
from app.services.ontology_uri import normalize_uri


class TestExportUri:
    def test_the_exact_value_that_broke_the_export_is_serialisable(self) -> None:
        u = _uri("namespace#qualifiedPersonnel Recommended", ontology_id="o1", label="x")
        g = Graph()
        g.add((u, URIRef("http://example.org/p"), URIRef("http://example.org/o")))
        # Would raise before the fix.
        assert "qualifiedPersonnel" in g.serialize(format="turtle")

    def test_a_space_never_survives_into_the_iri(self) -> None:
        assert " " not in str(_uri("namespace#Two Words", ontology_id="o1", label="Two Words"))

    @pytest.mark.parametrize(
        "raw",
        ["namespace#Vehicle", "#Vehicle", "Vehicle", "", "http://example.org/ontology#Vehicle"],
    )
    def test_every_placeholder_shape_becomes_absolute(self, raw: str) -> None:
        assert str(_uri(raw, ontology_id="o1", label="Vehicle")).startswith("http://")

    def test_a_real_iri_passes_through_untouched(self) -> None:
        real = "https://schema.org/Vehicle"
        assert str(_uri(real, ontology_id="o1", label="Vehicle")) == real

    def test_two_ontologies_do_not_collide_after_normalisation(self) -> None:
        a = _uri("namespace#Vehicle", ontology_id="jlr", label="Vehicle")
        b = _uri("namespace#Vehicle", ontology_id="aws", label="Vehicle")
        assert a != b

    def test_matches_the_extraction_time_normaliser(self) -> None:
        # Export and extraction must agree, or a re-extraction would silently
        # change every identity the exported file used.
        raw = "namespace#Vehicle"
        assert str(_uri(raw, ontology_id="o1", label="Vehicle")) == normalize_uri(
            raw, ontology_id="o1", label="Vehicle"
        )

    def test_a_whole_graph_of_placeholder_uris_serialises(self) -> None:
        g = Graph()
        for i in range(50):
            g.add(
                (
                    _uri(f"namespace#Thing {i}", ontology_id="o1", label=f"Thing {i}"),
                    URIRef("http://www.w3.org/1999/02/22-rdf-syntax-ns#type"),
                    URIRef("http://www.w3.org/2002/07/owl#Class"),
                )
            )
        out = g.serialize(format="turtle")
        assert "namespace#" not in out
