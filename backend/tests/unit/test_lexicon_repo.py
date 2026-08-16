"""Curated-lexicon persistence — collisions + decisions (PRD §6.20)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.db import lexicon_repo as repo

URI = "http://example.org/crm#ContactRole"


class TestNormalizeLabel:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("role", "role"),
            ("Role", "role"),
            ("  ROLE  ", "role"),
            ("job_title", "job title"),
            ("job title", "job title"),
            ("jobTitle", "job title"),
            ("Job-Title", "job title"),
            ("", ""),
        ],
    )
    def test_folds_to_comparison_form(self, raw: str, expected: str) -> None:
        assert repo.normalize_label(raw) == expected

    def test_camel_case_collides_with_its_spaced_twin(self) -> None:
        # A source column `jobTitle` and a curated "Job Title" are the same
        # collision; failing to fold them would file two queue items.
        assert repo.normalize_label("jobTitle") == repo.normalize_label("Job Title")


class TestCollisionKey:
    def test_is_deterministic(self) -> None:
        assert repo.collision_key("s", "role") == repo.collision_key("s", "role")

    def test_differs_by_scope_and_label(self) -> None:
        assert repo.collision_key("a", "role") != repo.collision_key("b", "role")
        assert repo.collision_key("a", "role") != repo.collision_key("a", "owner")

    def test_is_a_valid_arango_key(self) -> None:
        # A normalized label can contain spaces and arbitrary length, neither of
        # which ArangoDB permits in a _key.
        key = repo.collision_key("scope with spaces", "a very long label " * 20)
        assert key.isalnum() and len(key) <= 64


class TestUpsertCollision:
    def _db(self, existing=None):
        db = MagicMock()
        col = MagicMock()
        col.get.return_value = existing
        db.collection.return_value = col
        return db, col

    def test_inserts_a_new_open_collision(self) -> None:
        db, col = self._db(existing=None)
        out = repo.upsert_collision(
            db, scope="s", label="Role", occurrences=[{"concept_uri": URI}], detected_at=5.0
        )
        assert out["status"] == "open"
        assert out["normalized_label"] == "role"
        assert out["occurrence_count"] == 1
        col.insert.assert_called_once()

    def test_re_detection_updates_in_place(self) -> None:
        db, col = self._db(existing={"_key": "k", "status": "open", "detected_at": 1.0})
        repo.upsert_collision(
            db, scope="s", label="Role", occurrences=[{"a": 1}, {"b": 2}], detected_at=9.0
        )
        col.insert.assert_not_called()
        patch_arg = col.update.call_args[0][0]
        assert patch_arg["occurrence_count"] == 2
        assert patch_arg["last_seen_at"] == 9.0

    def test_re_detection_does_not_reopen_a_resolved_collision(self) -> None:
        # Reopening settled decisions on every catalog refresh is exactly the
        # churn this feature exists to stop.
        db, col = self._db(existing={"_key": "k", "status": "resolved"})
        out = repo.upsert_collision(
            db, scope="s", label="Role", occurrences=[{"a": 1}], detected_at=9.0
        )
        assert out["status"] == "resolved"
        assert "status" not in col.update.call_args[0][0]


class TestSetCollisionStatus:
    def test_rejects_an_unknown_status(self) -> None:
        with pytest.raises(ValueError, match="unknown collision status"):
            repo.set_collision_status(MagicMock(), key="k", status="maybe", curator_id="a")

    def test_returns_none_for_a_missing_collision(self) -> None:
        db = MagicMock()
        col = MagicMock()
        col.get.return_value = None
        db.collection.return_value = col
        assert repo.set_collision_status(db, key="nope", status="resolved", curator_id="a") is None


class TestRecordLabelDecision:
    def test_rejects_an_unknown_concept_type(self) -> None:
        with pytest.raises(ValueError, match="unknown concept_type"):
            repo.record_label_decision(
                MagicMock(),
                ontology_id="o",
                concept_uri=URI,
                concept_type="widget",
                label="job title",
                curator_id="arthur",
            )

    def test_requires_a_concept_uri(self) -> None:
        # Without it a decision cannot be rejoined to anything after re-extraction.
        with pytest.raises(ValueError, match="concept_uri is required"):
            repo.record_label_decision(
                MagicMock(),
                ontology_id="o",
                concept_uri="",
                concept_type="class",
                label="x",
                curator_id="arthur",
            )

    def test_first_decision_is_version_1_and_expires_nothing(self) -> None:
        db = MagicMock()
        with (
            patch.object(repo, "get_live_decision", return_value=None),
            patch.object(repo, "expire_entity") as mk_expire,
            patch.object(repo, "create_version", return_value={"_key": "d1"}) as mk_create,
        ):
            repo.record_label_decision(
                db,
                ontology_id="o",
                concept_uri=URI,
                concept_type="datatype_property",
                label="job title",
                curator_id="arthur",
                rationale="Contact.role is a person's job",
            )
        mk_expire.assert_not_called()
        data = mk_create.call_args.kwargs["data"]
        assert data["version"] == 1
        assert data["supersedes"] is None
        assert data["decided_by"] == "arthur"
        assert data["rationale"] == "Contact.role is a person's job"

    def test_re_deciding_expires_the_prior_decision_and_bumps_version(self) -> None:
        # The audit trail is as much the point as the string, so the prior
        # decision is expired rather than overwritten.
        db = MagicMock()
        prior = {"_key": "d1", "version": 1}
        with (
            patch.object(repo, "get_live_decision", return_value=prior),
            patch.object(repo, "expire_entity") as mk_expire,
            patch.object(repo, "create_version", return_value={"_key": "d2"}) as mk_create,
        ):
            repo.record_label_decision(
                db,
                ontology_id="o",
                concept_uri=URI,
                concept_type="datatype_property",
                label="role name",
                curator_id="sam",
            )
        assert mk_expire.call_args.kwargs["key"] == "d1"
        data = mk_create.call_args.kwargs["data"]
        assert data["version"] == 2
        assert data["supersedes"] == "d1"


class TestLiveDecisionsByUri:
    def test_missing_collection_is_empty(self) -> None:
        db = MagicMock()
        db.has_collection.return_value = False
        assert repo.live_decisions_by_uri(db) == {}

    def test_maps_uri_to_decision(self) -> None:
        db = MagicMock()
        db.has_collection.return_value = True
        rows = [{"concept_uri": URI, "label": "job title"}]
        with patch.object(repo, "run_aql", return_value=iter(rows)):
            out = repo.live_decisions_by_uri(db, ontology_id="o1")
        assert out[URI]["label"] == "job title"

    def test_uses_a_supplied_collection_snapshot_instead_of_probing(self) -> None:
        # has_collection is a full round-trip; the effective-graph path probes
        # collection metadata exactly once and passes the snapshot in.
        db = MagicMock()
        with patch.object(repo, "run_aql", return_value=iter([])):
            repo.live_decisions_by_uri(db, existing_collections={"label_decisions"})
        db.has_collection.assert_not_called()

    def test_snapshot_without_the_collection_short_circuits(self) -> None:
        db = MagicMock()
        assert repo.live_decisions_by_uri(db, existing_collections=set()) == {}
        db.has_collection.assert_not_called()
