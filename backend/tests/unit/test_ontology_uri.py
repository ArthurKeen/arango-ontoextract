"""Ontology IRI normalisation (FR-2.19).

`namespace#Vehicle` reached a 667-class production ontology because the prompt's
JSON schema showed exactly that as the example. The consequences are silent:
invalid RDF on export, and — because §6.20 joins curated label decisions to
concepts by `concept_uri` — two ontologies sharing an identity they should not.
"""

from __future__ import annotations

import pytest

from app.services.ontology_uri import base_namespace, is_placeholder_uri, normalize_uri


@pytest.mark.parametrize(
    "uri",
    [
        "namespace#Vehicle",  # the observed failure
        "#Vehicle",
        "Vehicle",
        "",
        None,
        "http://namespace/ontology#Vehicle",
        "http://example.org/ontology#Vehicle",
        "https://www.example.org/x#Y",
    ],
)
def test_detects_unusable_identities(uri: str | None) -> None:
    assert is_placeholder_uri(uri)


@pytest.mark.parametrize(
    "uri",
    [
        "http://arango-ontoextract.local/ontology/jlr#Vehicle",
        "https://schema.org/Vehicle",
        "http://purl.obolibrary.org/obo/BFO_0000001",
    ],
)
def test_leaves_real_iris_alone(uri: str) -> None:
    assert not is_placeholder_uri(uri)
    assert normalize_uri(uri, ontology_id="jlr", label="Vehicle") == uri


class TestNormalize:
    def test_rebuilds_on_the_ontology_base_keeping_the_local_name(self) -> None:
        out = normalize_uri("namespace#Vehicle", ontology_id="jlr", label="Vehicle")
        assert out == "http://arango-ontoextract.local/ontology/jlr#Vehicle"

    def test_two_ontologies_no_longer_collide(self) -> None:
        # The §6.20 decision store joins on concept_uri, so this is the bug that
        # would have leaked a rename from one ontology into another.
        a = normalize_uri("namespace#Vehicle", ontology_id="jlr", label="Vehicle")
        b = normalize_uri("namespace#Vehicle", ontology_id="aws", label="Vehicle")
        assert a != b

    def test_falls_back_to_the_label_when_there_is_no_local_name(self) -> None:
        out = normalize_uri("", ontology_id="jlr", label="Rear Traffic Monitor")
        assert out.endswith("#RearTrafficMonitor")

    def test_output_is_always_absolute(self) -> None:
        for bad in ("namespace#X", "#X", "X", None, ""):
            assert normalize_uri(bad, ontology_id="o", label="X").startswith("http://")

    def test_ontology_id_is_escaped_into_the_base(self) -> None:
        # An id with a slash must not silently create a different path.
        assert "/" not in base_namespace("a/b").rsplit("/", 1)[-1].rstrip("#")

    def test_unnamed_never_produces_a_bare_base(self) -> None:
        out = normalize_uri(None, ontology_id="o", label="   ")
        assert out.endswith("#Unnamed")
