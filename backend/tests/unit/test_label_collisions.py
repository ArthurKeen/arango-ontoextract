"""Label-collision detection, ingest and resolution (PRD §6.20 FR-20.1..FR-20.3)."""

from __future__ import annotations

from typing import ClassVar
from unittest.mock import MagicMock, patch

import pytest

from app.services import label_collisions as svc

DOC_ROLE = "http://example.org/crm#DocumentRole"
CONTACT_ROLE = "http://example.org/crm#ContactRole"


def _db_with_concepts(concepts: list[dict]) -> MagicMock:
    db = MagicMock()
    db.has_collection.return_value = True
    return db


class TestDetectInOntologies:
    def _run(self, concepts: list[dict], **kwargs):
        db = _db_with_concepts(concepts)
        with (
            patch.object(svc, "_live_concepts", return_value=concepts),
            patch.object(svc.lexicon_repo, "upsert_collision", side_effect=lambda _db, **k: k),
        ):
            return svc.detect_in_ontologies(db, ontology_ids=["o1"], **kwargs)

    def test_flags_the_same_label_on_two_distinct_concepts(self) -> None:
        out = self._run(
            [
                {
                    "uri": DOC_ROLE,
                    "label": "role",
                    "description": "kind of document",
                    "ontology_id": "o1",
                    "concept_type": "datatype_property",
                },
                {
                    "uri": CONTACT_ROLE,
                    "label": "Role",
                    "description": "person's job",
                    "ontology_id": "o1",
                    "concept_type": "datatype_property",
                },
            ]
        )
        assert out["detected"] == 1
        occ = out["collisions"][0]["occurrences"]
        assert {o["concept_uri"] for o in occ} == {DOC_ROLE, CONTACT_ROLE}
        # The description travels with each occurrence — it is what a curator
        # reads to make the judgement.
        assert {o["description"] for o in occ} == {"kind of document", "person's job"}

    def test_same_concept_in_two_ontologies_is_reuse_not_collision(self) -> None:
        # Imports are the point of the system; flagging them would bury real signal.
        out = self._run(
            [
                {
                    "uri": CONTACT_ROLE,
                    "label": "role",
                    "description": "",
                    "ontology_id": "o1",
                    "concept_type": "datatype_property",
                },
                {
                    "uri": CONTACT_ROLE,
                    "label": "role",
                    "description": "",
                    "ontology_id": "o2",
                    "concept_type": "datatype_property",
                },
            ]
        )
        assert out["detected"] == 0

    def test_generic_labels_are_skipped_by_default(self) -> None:
        out = self._run(
            [
                {
                    "uri": "u1",
                    "label": "id",
                    "description": "",
                    "ontology_id": "o1",
                    "concept_type": "datatype_property",
                },
                {
                    "uri": "u2",
                    "label": "ID",
                    "description": "",
                    "ontology_id": "o1",
                    "concept_type": "datatype_property",
                },
            ]
        )
        assert out["detected"] == 0
        assert out["skipped_stopwords"] == 1

    def test_generic_labels_can_be_opted_back_in(self) -> None:
        out = self._run(
            [
                {
                    "uri": "u1",
                    "label": "id",
                    "description": "",
                    "ontology_id": "o1",
                    "concept_type": "datatype_property",
                },
                {
                    "uri": "u2",
                    "label": "id",
                    "description": "",
                    "ontology_id": "o1",
                    "concept_type": "datatype_property",
                },
            ],
            include_stopwords=True,
        )
        assert out["detected"] == 1

    def test_no_ontologies_is_a_no_op(self) -> None:
        assert svc.detect_in_ontologies(MagicMock(), ontology_ids=[])["detected"] == 0

    def test_persist_false_skips_writes(self) -> None:
        concepts = [
            {
                "uri": DOC_ROLE,
                "label": "role",
                "description": "",
                "ontology_id": "o1",
                "concept_type": "datatype_property",
            },
            {
                "uri": CONTACT_ROLE,
                "label": "role",
                "description": "",
                "ontology_id": "o1",
                "concept_type": "datatype_property",
            },
        ]
        db = MagicMock()
        with (
            patch.object(svc, "_live_concepts", return_value=concepts),
            patch.object(svc.lexicon_repo, "upsert_collision") as mk,
        ):
            out = svc.detect_in_ontologies(db, ontology_ids=["o1"], persist=False)
        mk.assert_not_called()
        assert out["detected"] == 1


class TestIngestReport:
    def _ingest(self, items):
        db = MagicMock()
        with patch.object(
            svc.lexicon_repo, "upsert_collision", side_effect=lambda _db, **k: k
        ) as mk:
            return svc.ingest_report(db, scope="catalog", items=items), mk

    def test_accepts_a_well_formed_item_with_samples(self) -> None:
        out, _ = self._ingest(
            [
                {
                    "label": "role",
                    "occurrences": [
                        {
                            "concept_uri": DOC_ROLE,
                            "source_system": "docs",
                            "sample_values": ["signal", "qbr"],
                        },
                        {
                            "concept_uri": CONTACT_ROLE,
                            "source_system": "crm",
                            "sample_values": ["champion", "exec"],
                        },
                    ],
                }
            ]
        )
        assert out["accepted"] == 1
        occ = out["collisions"][0]["occurrences"]
        assert occ[0]["sample_values"] == ["signal", "qbr"]
        assert occ[1]["source_system"] == "crm"

    def test_rejects_an_item_with_one_occurrence(self) -> None:
        out, _ = self._ingest([{"label": "role", "occurrences": [{"concept_uri": DOC_ROLE}]}])
        assert out["accepted"] == 0
        assert out["rejected"][0]["reason"] == "need at least 2 occurrences"

    def test_rejects_an_item_with_no_label(self) -> None:
        out, _ = self._ingest([{"label": "  ", "occurrences": [{"a": 1}, {"b": 2}]}])
        assert out["rejected"][0]["reason"] == "missing label"

    def test_rejects_an_occurrence_missing_concept_uri(self) -> None:
        out, _ = self._ingest(
            [{"label": "role", "occurrences": [{"concept_uri": DOC_ROLE}, {"source": "x"}]}]
        )
        assert out["rejected"][0]["reason"] == "occurrence missing concept_uri"

    def test_one_bad_item_does_not_lose_the_good_ones(self) -> None:
        out, _ = self._ingest(
            [
                {"label": "", "occurrences": []},
                {
                    "label": "owner",
                    "occurrences": [{"concept_uri": "u1"}, {"concept_uri": "u2"}],
                },
            ]
        )
        assert out["accepted"] == 1
        assert len(out["rejected"]) == 1


class TestResolveCollision:
    COLLISION: ClassVar[dict] = {
        "_key": "c1",
        "occurrences": [{"concept_uri": DOC_ROLE}, {"concept_uri": CONTACT_ROLE}],
    }

    def test_records_a_decision_per_resolution_and_closes_the_item(self) -> None:
        db = MagicMock()
        with (
            patch.object(svc.lexicon_repo, "get_collision", return_value=self.COLLISION),
            patch.object(
                svc.lexicon_repo, "record_label_decision", side_effect=lambda _db, **k: k
            ) as mk_dec,
            patch.object(
                svc.lexicon_repo, "set_collision_status", return_value={"status": "resolved"}
            ) as mk_status,
        ):
            out = svc.resolve_collision(
                db,
                collision_key="c1",
                curator_id="arthur",
                resolutions=[
                    {
                        "concept_uri": CONTACT_ROLE,
                        "label": "job title",
                        "concept_type": "datatype_property",
                        "ontology_id": "o1",
                    }
                ],
            )
        assert len(out["decisions"]) == 1
        assert mk_dec.call_args.kwargs["label"] == "job title"
        assert mk_dec.call_args.kwargs["collision_key"] == "c1"
        assert mk_status.call_args.kwargs["status"] == "resolved"

    def test_renaming_only_one_side_is_allowed(self) -> None:
        # Often the right answer leaves one concept alone.
        db = MagicMock()
        with (
            patch.object(svc.lexicon_repo, "get_collision", return_value=self.COLLISION),
            patch.object(svc.lexicon_repo, "record_label_decision", side_effect=lambda _db, **k: k),
            patch.object(svc.lexicon_repo, "set_collision_status", return_value={}),
        ):
            out = svc.resolve_collision(
                db,
                collision_key="c1",
                curator_id="arthur",
                resolutions=[{"concept_uri": DOC_ROLE, "label": "document kind"}],
            )
        assert len(out["decisions"]) == 1

    def test_rejects_a_concept_not_in_this_collision(self) -> None:
        # Guards a stale UI from parking an unreachable decision.
        db = MagicMock()
        with (
            patch.object(svc.lexicon_repo, "get_collision", return_value=self.COLLISION),
            pytest.raises(ValueError, match="not one of this collision's occurrences"),
        ):
            svc.resolve_collision(
                db,
                collision_key="c1",
                curator_id="arthur",
                resolutions=[{"concept_uri": "http://other#Thing", "label": "x"}],
            )

    def test_dismiss_closes_without_recording_a_decision(self) -> None:
        db = MagicMock()
        with (
            patch.object(svc.lexicon_repo, "get_collision", return_value=self.COLLISION),
            patch.object(svc.lexicon_repo, "record_label_decision") as mk_dec,
            patch.object(
                svc.lexicon_repo, "set_collision_status", return_value={"status": "dismissed"}
            ) as mk_status,
        ):
            out = svc.resolve_collision(
                db, collision_key="c1", curator_id="arthur", resolutions=[], dismiss=True
            )
        mk_dec.assert_not_called()
        assert mk_status.call_args.kwargs["status"] == "dismissed"
        assert out["decisions"] == []

    def test_resolve_with_nothing_to_do_is_an_error(self) -> None:
        db = MagicMock()
        with (
            patch.object(svc.lexicon_repo, "get_collision", return_value=self.COLLISION),
            pytest.raises(ValueError, match="at least one resolution"),
        ):
            svc.resolve_collision(db, collision_key="c1", curator_id="arthur", resolutions=[])

    def test_unknown_collision_raises(self) -> None:
        db = MagicMock()
        with (
            patch.object(svc.lexicon_repo, "get_collision", return_value=None),
            pytest.raises(ValueError, match="not found"),
        ):
            svc.resolve_collision(db, collision_key="ghost", curator_id="arthur", resolutions=[])
