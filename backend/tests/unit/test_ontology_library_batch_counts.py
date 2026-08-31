"""Regression: library edge counts must be ONE AQL round-trip, not O(collections).

python-arango's ``has_collection`` and ``collections`` each issue a full
``GET /_api/collection`` round-trip; on a remote (cloud, WAN) ArangoDB the old
"has_collection + AQL per edge collection" shape made ``/library`` ~10
round-trips and seconds slow. These tests pin the single-round-trip behaviour.
"""

from unittest.mock import MagicMock, patch

from app.api.ontology import _batch_edge_counts_for_ontology_ids


def test_batch_edge_counts_single_combined_query() -> None:
    db = MagicMock()
    # One collections() snapshot; subclass_of + rdfs_domain present, others absent.
    db.collections.return_value = [
        {"name": "subclass_of"},
        {"name": "rdfs_domain"},
        {"name": "ontology_classes"},
    ]

    calls = {"n": 0}

    def fake_run_aql(_db, query, bind_vars=None, **kwargs):
        calls["n"] += 1
        assert bind_vars is not None
        assert "IN @oids" in query
        # All present edge collections are unioned into one query...
        assert "subclass_of" in query
        assert "rdfs_domain" in query
        # ...and absent ones are excluded.
        assert "related_to" not in query
        # Server-side aggregation across collections.
        assert "FLATTEN" in query
        assert "AGGREGATE" in query
        # The DB returns already-summed counts (ont_a's 2 + 1 across collections).
        return iter([{"oid": "ont_a", "cnt": 3}, {"oid": "ont_b", "cnt": 5}])

    with patch("app.api.ontology._shared.run_aql", side_effect=fake_run_aql):
        counts = _batch_edge_counts_for_ontology_ids(db, ["ont_a", "ont_b"])

    assert calls["n"] == 1  # single round-trip regardless of collection count
    assert db.has_collection.call_count == 0  # no per-collection metadata probes
    assert counts["ont_a"] == 3
    assert counts["ont_b"] == 5


def test_batch_edge_counts_uses_caller_supplied_collection_set() -> None:
    """When the caller passes ``existing``, we must NOT re-probe collections()."""
    db = MagicMock()
    with patch("app.api.ontology._shared.run_aql", return_value=iter([{"oid": "o", "cnt": 4}])):
        counts = _batch_edge_counts_for_ontology_ids(db, ["o"], existing={"subclass_of"})
    db.collections.assert_not_called()
    assert counts["o"] == 4


def test_batch_edge_counts_no_edge_collections_returns_zeros() -> None:
    db = MagicMock()
    with patch("app.api.ontology._shared.run_aql") as run_aql_mock:
        counts = _batch_edge_counts_for_ontology_ids(db, ["a", "b"], existing={"ontology_classes"})
    run_aql_mock.assert_not_called()  # nothing to query
    assert counts == {"a": 0, "b": 0}


def test_batch_edge_counts_empty_ids() -> None:
    db = MagicMock()
    assert _batch_edge_counts_for_ontology_ids(db, []) == {}


# ---------------------------------------------------------------------------
# Class counts are DERIVED, never read from the registry
# ---------------------------------------------------------------------------


def test_batch_class_counts_single_query_and_no_metadata_probes() -> None:
    from app.api.ontology import _batch_class_counts_for_ontology_ids

    db = MagicMock()
    calls = {"n": 0}

    def fake_run_aql(_db, query, bind_vars=None, **kwargs):
        calls["n"] += 1
        assert "ontology_classes" in query
        # Live versions only: an expired class is not part of the ontology.
        assert "c.expired == @never" in query
        # Server-side grouping, not a query per ontology.
        assert "COLLECT" in query and "WITH COUNT" in query
        return iter([{"oid": "ont_a", "cnt": 22}, {"oid": "ont_b", "cnt": 516}])

    with patch("app.api.ontology._shared.run_aql", side_effect=fake_run_aql):
        counts = _batch_class_counts_for_ontology_ids(
            db, ["ont_a", "ont_b"], existing={"ontology_classes"}
        )

    assert calls["n"] == 1
    assert db.has_collection.call_count == 0
    assert db.collections.call_count == 0
    assert counts == {"ont_a": 22, "ont_b": 516}


def test_ontology_with_no_classes_counts_zero_not_missing() -> None:
    """An empty ontology is a real state, not an error.

    "Vehicle Ontology" was created through the New Ontology dialog and has
    nothing extracted into it yet. Zero is the honest answer and must reach the
    picker as a number, so the reader can tell "empty" from "unknown".
    """
    from app.api.ontology import _batch_class_counts_for_ontology_ids

    db = MagicMock()
    with patch("app.api.ontology._shared.run_aql", return_value=iter([{"oid": "full", "cnt": 7}])):
        counts = _batch_class_counts_for_ontology_ids(
            db, ["full", "empty"], existing={"ontology_classes"}
        )

    assert counts == {"full": 7, "empty": 0}


def test_counting_failure_does_not_take_down_the_listing() -> None:
    from app.api.ontology import _batch_class_counts_for_ontology_ids

    db = MagicMock()
    with patch("app.api.ontology._shared.run_aql", side_effect=RuntimeError("boom")):
        counts = _batch_class_counts_for_ontology_ids(db, ["a"], existing={"ontology_classes"})

    assert counts == {"a": 0}


def test_missing_classes_collection_is_survivable() -> None:
    from app.api.ontology import _batch_class_counts_for_ontology_ids

    db = MagicMock()
    counts = _batch_class_counts_for_ontology_ids(db, ["a"], existing={"subclass_of"})

    assert counts == {"a": 0}
    db.collections.assert_not_called()


def test_listing_overwrites_the_stored_class_count() -> None:
    """The registry's stored ``class_count`` is the bug being fixed.

    Only the extraction path ever wrote it, so imports left it null and the
    picker rendered "( classes)"; where it WAS written it is a snapshot that
    drifts as curation expires classes (WTW stored 667 against 645 live). The
    listing must therefore replace it, not fall back to it.
    """
    from fastapi.testclient import TestClient

    from app.api.ontology import _shared
    from app.main import app

    stale = [
        {"_key": "wtw", "name": "WTW Ontology", "class_count": 667, "tier": "domain"},
        {"_key": "sosa-ssn", "name": "SOSA/SSN", "class_count": None, "tier": "local"},
    ]
    db = MagicMock()
    db.collections.return_value = [{"name": "ontology_classes"}, {"name": "ontology_registry"}]
    db.collection.return_value.count.return_value = 2

    with (
        patch.object(_shared, "get_db", return_value=db),
        patch.object(_shared.registry_repo, "list_registry_entries", return_value=(stale, None)),
        patch(
            "app.api.ontology.library._batch_edge_counts_for_ontology_ids",
            return_value={"wtw": 0, "sosa-ssn": 0},
        ),
        patch(
            "app.api.ontology.library._batch_class_counts_for_ontology_ids",
            return_value={"wtw": 645, "sosa-ssn": 22},
        ),
    ):
        resp = TestClient(app).get("/api/v1/ontology/library")

    assert resp.status_code == 200
    by_key = {row["_key"]: row for row in resp.json()["data"]}
    assert by_key["wtw"]["class_count"] == 645, "stale stored value must not survive"
    assert by_key["sosa-ssn"]["class_count"] == 22, "null stored value must be replaced"
