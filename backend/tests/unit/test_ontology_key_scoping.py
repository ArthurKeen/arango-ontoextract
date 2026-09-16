"""Class storage keys must be scoped to their ontology.

Regression cover for a cross-ontology corruption observed 2026-09-16 while
preparing the clinical-research demo. The ICH M11 protocol template was
extracted twice (a model A/B). Both runs produced a class whose IRI fragment
was ``AdverseEventOfSpecialInterest``; extraction keyed the document on that
fragment alone and inserted with ``overwrite=True``.

The second run therefore took ownership of the first run's class documents,
re-stamping their ``ontology_id``. The first ontology's ``subclass_of`` edges
still pointed at those keys, so the effective graph — which resolves edges
against the classes it delivers — silently dropped them: 14 of 52 hierarchy
edges vanished, and the canvas rendered a near-flat ontology.

``normalize_uri`` already scoped the *IRI* per ontology (FR-2.19). Only the
storage key was left global, which is why the corruption was invisible in
exports and only showed up as missing edges.
"""

from __future__ import annotations

from app.services.ontology_uri import (
    base_namespace,
    class_document_key,
    normalize_uri,
)

ONTO_A = "488207172"
ONTO_B = "488208888"
FRAGMENT = "AdverseEventOfSpecialInterest"
LABEL = "Adverse Event of Special Interest"


def _uri(ontology_id: str) -> str:
    return normalize_uri(f"namespace#{FRAGMENT}", ontology_id=ontology_id, label=LABEL)


def test_same_concept_in_two_ontologies_gets_different_keys() -> None:
    """The exact collision that corrupted the demo ontologies."""
    key_a = class_document_key(ONTO_A, _uri(ONTO_A), label=LABEL)
    key_b = class_document_key(ONTO_B, _uri(ONTO_B), label=LABEL)

    assert key_a != key_b, (
        "two ontologies extracted from the same document must not share a class "
        "_key -- with insert(overwrite=True) the second run silently claims the "
        "first run's documents and orphans its subclass_of edges"
    )
    assert ONTO_A in key_a
    assert ONTO_B in key_b


def test_key_is_stable_for_the_same_concept_and_ontology() -> None:
    """``overwrite=True`` relies on this: re-writes within one run must collide."""
    uri = _uri(ONTO_A)
    assert class_document_key(ONTO_A, uri, label=LABEL) == class_document_key(
        ONTO_A, uri, label=LABEL
    )


def test_key_preserves_the_local_name_for_debuggability() -> None:
    """A hash-only key would work but makes every AQL result unreadable."""
    assert FRAGMENT in class_document_key(ONTO_A, _uri(ONTO_A), label=LABEL)


def test_key_stays_within_arango_limits() -> None:
    """Arango rejects a ``_key`` over 254 bytes, and long class names are real."""
    long_label = "Adverse Event of Special Interest " * 20
    uri = f"{base_namespace(ONTO_A)}{long_label.replace(' ', '')}"
    key = class_document_key(ONTO_A, uri, label=long_label)
    assert len(key.encode("utf-8")) <= 254


def test_long_names_sharing_a_prefix_do_not_collide_after_truncation() -> None:
    """Truncation alone would map these to one key; the digest prevents it."""
    stem = "VeryLongClinicalConceptName" * 12
    uri_1 = f"{base_namespace(ONTO_A)}{stem}Alpha"
    uri_2 = f"{base_namespace(ONTO_A)}{stem}Beta"
    assert class_document_key(ONTO_A, uri_1) != class_document_key(ONTO_A, uri_2)


def test_key_contains_only_characters_arango_accepts() -> None:
    """Extractors emit spaces, slashes and parentheses in local names."""
    messy = "Adverse Event / Special Interest (AESI) #1"
    key = class_document_key("onto with spaces", f"x#{messy}", label=messy)
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-:.@()+,=;$!*'%")
    assert set(key) <= allowed, f"illegal characters in key: {set(key) - allowed}"


def test_ontology_ids_that_prefix_each_other_stay_distinct() -> None:
    """``onto1`` and ``onto11`` must not alias through the separator."""
    uri = f"x#{FRAGMENT}"
    assert class_document_key("onto1", uri, label=LABEL) != class_document_key(
        "onto11", uri, label=LABEL
    )
