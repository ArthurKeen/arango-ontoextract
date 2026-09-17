"""Proposed parents must survive materialisation, or be reported when they don't.

Measured on the ICH M11 ontology (2026-09-16): the extractor proposed a parent
for 326 of 363 classes — 90% — and only 50 subclass_of edges were written. The
ontology rendered 86% orphaned and it looked like the model was not thinking
taxonomically. It was; the resolver was discarding its work.

Two defects, compounding:

1. Tier 2 of parent resolution looked a URI FRAGMENT up in ``class_keys``,
   which is keyed by LABEL (its own comment says "really label_to_key").
   Fragments are CamelCase ("TrialIntervention"); labels are not
   ("Trial Intervention"). Measured hit rate on the live ontology: 8 of 363.

2. There was no branch for an unresolved parent at all — control fell off the
   end of the ``if/elif``. No edge, no log, no counter, so the loss was
   indistinguishable from the model never proposing a parent.

The fix routes parents through ``edge_repair.resolve_range_class``, the same
four-tier resolver (uri / fragment / label / miss) relationships already used,
and adds the miss branch.
"""

from __future__ import annotations

from unittest.mock import MagicMock

EDGE_COLLECTIONS = (
    "ontology_classes",
    "ontology_properties",
    "has_property",
    "subclass_of",
    "related_to",
    "extracted_from",
    "has_chunk",
    "produced_by",
)


def _mock_db() -> tuple[MagicMock, dict[str, MagicMock]]:
    db = MagicMock()
    db.has_collection.return_value = True
    cols: dict[str, MagicMock] = {}
    for name in EDGE_COLLECTIONS:
        col = MagicMock()
        col.insert.return_value = {}
        cols[name] = col
    db.collection.side_effect = lambda name: cols.get(name, MagicMock())
    db.aql.execute.return_value = iter([])
    return db, cols


def _materialize(classes: list) -> list[dict]:
    from app.services.extraction import _materialize_to_graph

    db, cols = _mock_db()
    result = MagicMock()
    result.classes = classes
    _materialize_to_graph(
        db, run_id="run_1", document_id="doc_1", ontology_id="onto_1", result=result
    )
    return [call[0][0] for call in cols["subclass_of"].insert.call_args_list]


def _cls(uri: str, label: str, parent_uri: str | None = None):
    from app.models.ontology import ExtractedClass

    return ExtractedClass(
        uri=uri, label=label, description="", parent_uri=parent_uri, confidence=0.9
    )


def test_camelcase_parent_uri_resolves_against_a_spaced_label() -> None:
    """The exact shape that lost 276 edges.

    The parent is emitted as ``#TrialIntervention`` while the parent class was
    stored with label "Trial Intervention". Tier 1 (exact URI) misses because
    the child names a URI the parent does not carry; the fix must fall through
    to fragment/label matching rather than dropping the edge.
    """
    edges = _materialize(
        [
            _cls(
                "http://x#AuxiliaryMedicinalProduct",
                "Auxiliary Medicinal Product",
                parent_uri="http://x#TrialIntervention",
            ),
            _cls("http://x#Trial_Intervention", "Trial Intervention"),
        ]
    )
    assert len(edges) == 1, (
        "a CamelCase parent URI must resolve to a spaced label -- this is the "
        "98%-miss case that flattened the ICH M11 ontology"
    )
    assert edges[0]["_to"].endswith("__Trial_Intervention")


def test_exact_uri_match_still_wins() -> None:
    """Tier 1 must keep working; the fix must not regress the easy case."""
    edges = _materialize(
        [
            _cls("http://x#Airbag", "Airbag", parent_uri="http://x#SRS"),
            _cls("http://x#SRS", "SRS"),
        ]
    )
    assert len(edges) == 1
    assert edges[0]["_to"].endswith("__SRS")


def test_unresolvable_parent_is_reported_not_silently_dropped(caplog) -> None:
    """A parent naming a class that was never extracted must leave a trace."""
    import logging

    with caplog.at_level(logging.WARNING):
        edges = _materialize(
            [_cls("http://x#Orphan", "Orphan", parent_uri="http://x#NeverExtracted")]
        )

    assert edges == [], "an unresolvable parent must not fabricate an edge"
    assert any("unresolved subclass_of parent" in r.message for r in caplog.records), (
        "the miss must be logged -- silence here is what made the 276 lost "
        "edges invisible for months"
    )


def test_self_referential_parent_is_still_skipped() -> None:
    """Pre-existing guard must survive the resolver swap."""
    edges = _materialize([_cls("http://x#Loop", "Loop", parent_uri="http://x#Loop")])
    assert edges == []


def test_proposed_parent_is_persisted_even_when_unresolvable() -> None:
    """The LLM's intent must survive a failed resolution.

    Relationships already persist ``target_class_uri`` so a repair pass can
    recover them. Parents did not, which is why the 276 losses had to be
    inferred from evidence text rather than queried.
    """
    db, cols = _mock_db()
    result = MagicMock()
    result.classes = [_cls("http://x#Orphan", "Orphan", parent_uri="http://x#NeverExtracted")]
    from app.services.extraction import _materialize_to_graph

    _materialize_to_graph(
        db, run_id="run_1", document_id="doc_1", ontology_id="onto_1", result=result
    )
    written = [call[0][0] for call in cols["ontology_classes"].insert.call_args_list]
    orphan = next(d for d in written if d["label"] == "Orphan")
    assert orphan["parent_uri"] == "http://x#NeverExtracted"
    assert orphan["parent_label"], "a humanised parent label must be stored as an anchor"


def test_curie_parent_resolves_into_an_imported_ontology() -> None:
    """The model cites `obo:CTO_0000108`; that class lives in CTO, not here.

    Once the Tier 2 context began emitting citable identifiers the model
    stopped inventing URIs and started correctly naming IMPORTED classes.
    Measured on the Ixekizumab protocol: 442 parents unresolved, 434 of them
    (98%) real CTO identifiers — `Ixekizumab -> obo:CTO_0000108`
    ("investigational molecular entity"), correct and discarded. Resolution
    must reach into the declared base ontologies.
    """
    from unittest.mock import patch

    db, cols = _mock_db()
    result = MagicMock()
    result.classes = [_cls("http://x#Ixekizumab", "Ixekizumab", parent_uri="obo:CTO_0000108")]
    from app.services.extraction import _materialize_to_graph

    with patch(
        "app.services.extraction._imported_class_uri_index",
        return_value={"http://purl.obolibrary.org/obo/CTO_0000108": "ontology_classes/cto_108"},
    ):
        _materialize_to_graph(
            db,
            run_id="run_1",
            document_id="doc_1",
            ontology_id="onto_1",
            result=result,
            base_ontology_ids=["cto"],
        )

    edges = [call[0][0] for call in cols["subclass_of"].insert.call_args_list]
    assert len(edges) == 1, "a CURIE naming an imported class must resolve"
    assert edges[0]["_to"] == "ontology_classes/cto_108"
    assert edges[0]["cross_ontology"] is True


def test_no_base_ontologies_keeps_the_original_path() -> None:
    """A single-ontology extraction must behave exactly as before."""
    db, cols = _mock_db()
    result = MagicMock()
    result.classes = [_cls("http://x#Orphan", "Orphan", parent_uri="obo:CTO_0000108")]
    from app.services.extraction import _materialize_to_graph

    _materialize_to_graph(
        db, run_id="run_1", document_id="doc_1", ontology_id="onto_1", result=result
    )
    assert [c[0][0] for c in cols["subclass_of"].insert.call_args_list] == []
