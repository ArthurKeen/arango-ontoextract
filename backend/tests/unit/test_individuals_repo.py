"""Unit tests for the A-box repo (Stream 21 / AB-PR1)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.db import individuals_repo as repo


class TestCreateIndividual:
    def test_creates_version_and_rdf_type_edge(self) -> None:
        db = MagicMock()
        individual = {"_key": "i1", "_id": "ontology_individuals/i1", "label": "Acme Corp"}
        with (
            patch.object(repo, "create_version", return_value=individual) as mk_ver,
            patch.object(repo, "create_edge") as mk_edge,
        ):
            out = repo.create_individual(
                db,
                ontology_id="ont1",
                class_key="Organization",
                label="Acme Corp",
                provenance=[{"doc_id": "d1", "chunk_id": "c1", "span": [0, 8]}],
            )
        assert out is individual
        # individual persisted to the A-box collection with provenance
        ver_kwargs = mk_ver.call_args.kwargs
        assert ver_kwargs["collection"] == "ontology_individuals"
        assert ver_kwargs["data"]["label"] == "Acme Corp"
        assert ver_kwargs["data"]["provenance"][0]["doc_id"] == "d1"
        # rdf:type edge -> the T-box class
        edge_kwargs = mk_edge.call_args.kwargs
        assert edge_kwargs["edge_collection"] == "rdf_type"
        assert edge_kwargs["from_id"] == "ontology_individuals/i1"
        assert edge_kwargs["to_id"] == "ontology_classes/Organization"


class TestAddAssertion:
    def test_creates_assertion_edge_with_predicate(self) -> None:
        db = MagicMock()
        with patch.object(repo, "create_edge", return_value={"_key": "e1"}) as mk_edge:
            repo.add_assertion(
                db,
                ontology_id="ont1",
                from_individual_id="ontology_individuals/i1",
                to_id="ontology_individuals/i2",
                predicate="employs",
                provenance=[{"doc_id": "d1"}],
            )
        kwargs = mk_edge.call_args.kwargs
        assert kwargs["edge_collection"] == "individual_assertion"
        assert kwargs["data"]["predicate"] == "employs"
        assert kwargs["data"]["ontology_id"] == "ont1"
        assert kwargs["data"]["provenance"] == [{"doc_id": "d1"}]


class TestListWithTypes:
    def test_missing_collection_is_empty(self) -> None:
        db = MagicMock()
        db.has_collection.return_value = False
        assert repo.list_individuals_with_types(db, "ont1") == []

    def test_returns_rows_and_threads_pagination(self) -> None:
        db = MagicMock()
        db.has_collection.return_value = True
        rows = [{"_key": "i1", "label": "Acme", "type_label": "Organization", "type_key": "Org"}]
        with patch.object(repo, "run_aql", return_value=iter(rows)) as raq:
            out = repo.list_individuals_with_types(db, "ont1", limit=25, offset=5)
        assert out == rows
        assert raq.call_args.kwargs["bind_vars"]["count"] == 25
        assert raq.call_args.kwargs["bind_vars"]["offset"] == 5


class TestQueries:
    def test_get_individual_returns_first_or_none(self) -> None:
        db = MagicMock()
        with patch.object(repo, "run_aql", return_value=iter([{"_key": "i1"}])):
            assert repo.get_individual(db, "i1") == {"_key": "i1"}
        with patch.object(repo, "run_aql", return_value=iter([])):
            assert repo.get_individual(db, "missing") is None

    def test_list_individuals_missing_collection_is_empty(self) -> None:
        db = MagicMock()
        db.has_collection.return_value = False
        assert repo.list_individuals(db, "ont1") == []

    def test_list_individuals_threads_pagination(self) -> None:
        db = MagicMock()
        db.has_collection.return_value = True
        with patch.object(repo, "run_aql", return_value=iter([{"_key": "i1"}])) as raq:
            out = repo.list_individuals(db, "ont1", limit=25, offset=50)
        assert out == [{"_key": "i1"}]
        assert raq.call_args.kwargs["bind_vars"]["count"] == 25
        assert raq.call_args.kwargs["bind_vars"]["offset"] == 50


class TestCurateIndividual:
    """FR-18.9 — approve / reject / edit an A-box individual."""

    def _db(self, snapshot: dict | None = None):
        db = MagicMock()
        db.has_collection.return_value = True
        col = MagicMock()
        col.get.return_value = snapshot if snapshot is not None else {"_key": "i1"}
        db.collection.return_value = col
        return db, col

    def test_unknown_action_raises(self) -> None:
        with pytest.raises(ValueError, match="unknown curation action"):
            repo.curate_individual(MagicMock(), key="i1", action="bogus")

    def test_missing_collection_returns_none(self) -> None:
        db = MagicMock()
        db.has_collection.return_value = False
        assert repo.curate_individual(db, key="i1", action="approve") is None

    def test_missing_individual_returns_none(self) -> None:
        db, _col = self._db()
        with patch.object(repo, "get_individual", return_value=None):
            assert repo.curate_individual(db, key="i1", action="approve") is None

    def test_approve_sets_status_and_returns_snapshot(self) -> None:
        db, col = self._db(snapshot={"_key": "i1", "status": "approved"})
        with patch.object(repo, "get_individual", return_value={"_key": "i1", "ontology_id": "o"}):
            out = repo.curate_individual(db, key="i1", action="approve")
        col.update.assert_called_once_with({"_key": "i1", "status": "approved"})
        assert out == {"_key": "i1", "status": "approved"}

    def test_reject_expires_individual_and_its_edges(self) -> None:
        db, col = self._db()
        with (
            patch.object(repo, "get_individual", return_value={"_key": "i1", "ontology_id": "o"}),
            patch.object(repo, "run_aql", side_effect=lambda *a, **k: iter(["e1"])),
            patch.object(repo, "expire_entity") as mk_exp,
        ):
            repo.curate_individual(db, key="i1", action="reject")
        col.update.assert_called_once_with({"_key": "i1", "status": "rejected"})
        expired = {(c.kwargs["collection"], c.kwargs["key"]) for c in mk_exp.call_args_list}
        # individual + its live rdf_type edge + its live assertion edge all expired
        assert ("ontology_individuals", "i1") in expired
        assert ("rdf_type", "e1") in expired
        assert ("individual_assertion", "e1") in expired

    def test_edit_updates_label_only(self) -> None:
        db, col = self._db()
        with patch.object(repo, "get_individual", return_value={"_key": "i1", "ontology_id": "o"}):
            repo.curate_individual(db, key="i1", action="edit", label="Acme, Inc.")
        col.update.assert_called_once_with({"_key": "i1", "label": "Acme, Inc."})

    def test_edit_retype_expires_old_type_edge_and_links_new(self) -> None:
        db, _col = self._db()
        with (
            patch.object(repo, "get_individual", return_value={"_key": "i1", "ontology_id": "o"}),
            patch.object(repo, "run_aql", side_effect=lambda *a, **k: iter(["rt1"])),
            patch.object(repo, "expire_entity") as mk_exp,
            patch.object(repo, "create_edge") as mk_edge,
        ):
            repo.curate_individual(db, key="i1", action="edit", class_key="Company")
        mk_exp.assert_called_once_with(db, collection="rdf_type", key="rt1")
        ek = mk_edge.call_args.kwargs
        assert ek["edge_collection"] == "rdf_type"
        assert ek["from_id"] == "ontology_individuals/i1"
        assert ek["to_id"] == "ontology_classes/Company"
        assert ek["data"]["ontology_id"] == "o"

    def test_edit_without_changes_is_noop_update(self) -> None:
        # No label, no class_key -> nothing to patch, no retype.
        db, col = self._db()
        with patch.object(repo, "get_individual", return_value={"_key": "i1", "ontology_id": "o"}):
            repo.curate_individual(db, key="i1", action="edit")
        col.update.assert_not_called()


class TestCountIndividualsByClass:
    """FR-18.13 — per-class instance counts drive the canvas expand affordance."""

    def test_missing_collections_is_empty(self) -> None:
        db = MagicMock()
        db.has_collection.return_value = False
        assert repo.count_individuals_by_class(db, "ont1") == {}

    def test_maps_class_key_to_count(self) -> None:
        db = MagicMock()
        db.has_collection.return_value = True
        rows = [
            {"class_key": "Organization", "count": 12},
            {"class_key": "Person", "count": 3},
        ]
        with patch.object(repo, "run_aql", return_value=iter(rows)) as raq:
            out = repo.count_individuals_by_class(db, "ont1")
        assert out == {"Organization": 12, "Person": 3}
        assert raq.call_args.kwargs["bind_vars"]["oid"] == "ont1"

    def test_drops_rows_with_no_class_key(self) -> None:
        # A dangling rdf_type edge would otherwise produce a None-keyed bucket.
        db = MagicMock()
        db.has_collection.return_value = True
        rows = [{"class_key": None, "count": 4}, {"class_key": "Person", "count": 1}]
        with patch.object(repo, "run_aql", return_value=iter(rows)):
            assert repo.count_individuals_by_class(db, "ont1") == {"Person": 1}


class TestGetInstanceGraph:
    """FR-18.13 — per-class instance expansion for the canvas."""

    @staticmethod
    def _row(key: str, class_key: str, label: str | None = None) -> dict:
        return {
            "individual": {
                "_key": key,
                "_id": f"ontology_individuals/{key}",
                "label": label or key,
                "uri": None,
                "status": None,
                "provenance": [],
                "ontology_id": "ont1",
            },
            "edge": {
                "_key": f"e-{key}",
                "_from": f"ontology_individuals/{key}",
                "_to": f"ontology_classes/{class_key}",
            },
        }

    def test_no_class_keys_short_circuits(self) -> None:
        db = MagicMock()
        out = repo.get_instance_graph(db, "ont1", class_keys=[])
        assert out == {
            "individuals": [],
            "rdf_type_edges": [],
            "assertions": [],
            "truncated": [],
        }
        db.has_collection.assert_not_called()

    def test_missing_collections_is_empty(self) -> None:
        db = MagicMock()
        db.has_collection.return_value = False
        out = repo.get_instance_graph(db, "ont1", class_keys=["Person"])
        assert out["individuals"] == []

    def test_returns_individuals_edges_and_assertions(self) -> None:
        db = MagicMock()
        db.has_collection.return_value = True
        grouped = [{"class_key": "Person", "rows": [self._row("i1", "Person")]}]
        assertions = [
            {
                "_key": "a1",
                "_from": "ontology_individuals/i1",
                "_to": "ontology_individuals/i1",
                "predicate": "knows",
                "provenance": [],
            }
        ]
        with patch.object(repo, "run_aql", side_effect=[iter(grouped), iter(assertions)]) as raq:
            out = repo.get_instance_graph(db, "ont1", class_keys=["Person"])
        assert [i["_key"] for i in out["individuals"]] == ["i1"]
        assert [e["_key"] for e in out["rdf_type_edges"]] == ["e-i1"]
        assert out["assertions"] == assertions
        # assertion lookup is scoped to the returned individual ids
        assert raq.call_args.kwargs["bind_vars"]["ids"] == ["ontology_individuals/i1"]

    def test_per_class_cap_is_reported_as_truncated(self) -> None:
        db = MagicMock()
        db.has_collection.return_value = True
        grouped = [
            {
                "class_key": "Person",
                "rows": [self._row("i1", "Person"), self._row("i2", "Person")],
            },
            {"class_key": "Org", "rows": [self._row("i3", "Org")]},
        ]
        with patch.object(repo, "run_aql", side_effect=[iter(grouped), iter([])]):
            out = repo.get_instance_graph(
                db, "ont1", class_keys=["Person", "Org"], limit_per_class=2
            )
        assert out["truncated"] == ["Person"]
        assert len(out["individuals"]) == 3

    def test_multi_typed_individual_is_not_duplicated(self) -> None:
        # Same individual typed to two expanded classes must yield ONE node but
        # BOTH rdf_type edges, or the canvas drops a node on id collision.
        db = MagicMock()
        db.has_collection.return_value = True
        grouped = [
            {"class_key": "Person", "rows": [self._row("i1", "Person")]},
            {"class_key": "Agent", "rows": [self._row("i1", "Agent")]},
        ]
        with patch.object(repo, "run_aql", side_effect=[iter(grouped), iter([])]):
            out = repo.get_instance_graph(db, "ont1", class_keys=["Person", "Agent"])
        assert len(out["individuals"]) == 1
        assert {e["_to"] for e in out["rdf_type_edges"]} == {
            "ontology_classes/Person",
            "ontology_classes/Agent",
        }

    def test_skips_assertion_query_when_no_individuals(self) -> None:
        db = MagicMock()
        db.has_collection.return_value = True
        with patch.object(repo, "run_aql", side_effect=[iter([])]) as raq:
            out = repo.get_instance_graph(db, "ont1", class_keys=["Person"])
        assert out["assertions"] == []
        assert raq.call_count == 1
