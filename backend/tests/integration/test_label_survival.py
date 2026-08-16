"""Integration: curated labels vs re-extraction, against a real ArangoDB.

This file exists to settle a claim that was previously argued from code reading
alone: that re-extraction does not merely revert a curated label, it RESURRECTS
the expired pre-curation document and leaves two live rows for one concept.

The mechanism depends on ArangoDB's ``insert(overwrite=True)`` replace-by-``_key``
semantics interacting with the temporal ``expired`` sentinel, which is precisely
the kind of thing a mock cannot tell you. Run against a live server::

    docker run -d --name aoe-probe -e ARANGO_NO_AUTH=1 -p 8599:8529 arangodb:3.12
    ARANGO_TEST_HOST=http://localhost:8599 pytest backend/tests/integration/test_label_survival.py

PRD §6.20 FR-20.5.
"""

from __future__ import annotations

from typing import Any

import pytest
from arango.database import StandardDatabase

from app.db.temporal_constants import NEVER_EXPIRES
from app.services import label_overlay
from app.services.temporal import update_entity

PROPS = "ontology_datatype_properties"
ONTOLOGY_ID = "crm"
# The URI is stable across re-extraction; the _key is not. That asymmetry is the
# entire basis of the overlay's join.
CONTACT_ROLE_URI = "http://example.org/crm#ContactRole"
EXTRACTED_KEY = "Contact_role"


def _live(db: StandardDatabase) -> list[dict[str, Any]]:
    return list(
        db.aql.execute(
            f"FOR p IN {PROPS} FILTER p.uri == @uri AND p.expired == @never RETURN p",
            bind_vars={"uri": CONTACT_ROLE_URI, "never": NEVER_EXPIRES},
        )
    )


def _write_as_extraction_does(db: StandardDatabase) -> None:
    """Exactly what ``app.services.extraction`` does for a datatype property.

    ``_key`` is rebuilt from the LLM's label each run and the document is
    re-inserted with ``overwrite=True`` — see extraction.py:1383.
    """
    db.collection(PROPS).insert(
        {
            "_key": EXTRACTED_KEY,
            "uri": CONTACT_ROLE_URI,
            "label": "role",
            "description": "extracted description",
            "ontology_id": ONTOLOGY_ID,
            "created": 1,
            "expired": NEVER_EXPIRES,
        },
        overwrite=True,
    )


@pytest.fixture()
def props_collection(test_db: StandardDatabase):
    if not test_db.has_collection(PROPS):
        test_db.create_collection(PROPS)
    test_db.collection(PROPS).truncate()
    yield test_db.collection(PROPS)
    test_db.collection(PROPS).truncate()


class TestResurrectionOnReExtraction:
    """FR-20.5 — the failure mode the decision store is designed around."""

    def test_curator_edit_moves_the_label_to_a_new_key(
        self, test_db: StandardDatabase, props_collection: Any
    ) -> None:
        _write_as_extraction_does(test_db)

        update_entity(
            test_db,
            collection=PROPS,
            key=EXTRACTED_KEY,
            new_data={"label": "job title"},
            created_by="arthur",
            change_type="edit",
        )

        live = _live(test_db)
        assert len(live) == 1
        assert live[0]["label"] == "job title"
        # The curated row is NOT under the key extraction uses — update_entity
        # expires the original and inserts a fresh, auto-keyed version.
        assert live[0]["_key"] != EXTRACTED_KEY
        original = props_collection.get(EXTRACTED_KEY)
        assert original is not None and original["expired"] != NEVER_EXPIRES

    def test_re_extraction_resurrects_the_expired_row_leaving_two_live(
        self, test_db: StandardDatabase, props_collection: Any
    ) -> None:
        _write_as_extraction_does(test_db)
        update_entity(
            test_db,
            collection=PROPS,
            key=EXTRACTED_KEY,
            new_data={"label": "job title"},
            created_by="arthur",
            change_type="edit",
        )
        assert len(_live(test_db)) == 1

        # Catalog refresh: the LLM still emits "role", so the same _key is
        # rebuilt and overwritten — resetting ``expired`` on the row the curator
        # had retired.
        _write_as_extraction_does(test_db)

        live = _live(test_db)
        assert len(live) == 2, "expected the expired original to be resurrected"
        assert sorted(p["label"] for p in live) == ["job title", "role"]

    def test_overlay_collapses_the_duplicate_to_the_curated_label(
        self, test_db: StandardDatabase, props_collection: Any
    ) -> None:
        _write_as_extraction_does(test_db)
        update_entity(
            test_db,
            collection=PROPS,
            key=EXTRACTED_KEY,
            new_data={"label": "job title"},
            created_by="arthur",
            change_type="edit",
        )
        _write_as_extraction_does(test_db)

        decisions = {
            CONTACT_ROLE_URI: {
                "concept_uri": CONTACT_ROLE_URI,
                "label": "job title",
                "description": None,
                "decided_by": "arthur",
                "decided_at": 1000.0,
            }
        }
        overlaid = label_overlay.apply_to_rows(_live(test_db), decisions)

        # Both live rows share a uri, so both resolve to the curated label: the
        # reader sees one name, not "role" beside "job title".
        assert {p["label"] for p in overlaid} == {"job title"}
        assert {p["extracted_label"] for p in overlaid} == {"role", "job title"}


class TestDecisionSurvivesWithoutTheEntity:
    """The decision store is untouched by anything extraction does."""

    def test_decision_lookup_is_unaffected_by_entity_overwrite(
        self, test_db: StandardDatabase, props_collection: Any
    ) -> None:
        from app.db import lexicon_repo

        for name in (lexicon_repo.DECISIONS,):
            if not test_db.has_collection(name):
                test_db.create_collection(name)
            test_db.collection(name).truncate()

        _write_as_extraction_does(test_db)
        lexicon_repo.record_label_decision(
            test_db,
            ontology_id=ONTOLOGY_ID,
            concept_uri=CONTACT_ROLE_URI,
            concept_type="datatype_property",
            label="job title",
            curator_id="arthur",
        )

        # Re-extraction twice over, which reclaims the entity key each time.
        _write_as_extraction_does(test_db)
        _write_as_extraction_does(test_db)

        decisions = lexicon_repo.live_decisions_by_uri(test_db, ontology_id=ONTOLOGY_ID)
        assert decisions[CONTACT_ROLE_URI]["label"] == "job title"
        assert decisions[CONTACT_ROLE_URI]["decided_by"] == "arthur"
        overlaid = label_overlay.apply_to_rows(_live(test_db), decisions)
        assert {p["label"] for p in overlaid} == {"job title"}

    def test_re_deciding_keeps_the_prior_decision_queryable(
        self, test_db: StandardDatabase
    ) -> None:
        from app.db import lexicon_repo

        if not test_db.has_collection(lexicon_repo.DECISIONS):
            test_db.create_collection(lexicon_repo.DECISIONS)
        test_db.collection(lexicon_repo.DECISIONS).truncate()

        lexicon_repo.record_label_decision(
            test_db,
            ontology_id=ONTOLOGY_ID,
            concept_uri=CONTACT_ROLE_URI,
            concept_type="datatype_property",
            label="contact role",
            curator_id="arthur",
        )
        lexicon_repo.record_label_decision(
            test_db,
            ontology_id=ONTOLOGY_ID,
            concept_uri=CONTACT_ROLE_URI,
            concept_type="datatype_property",
            label="job title",
            curator_id="sam",
        )

        live = lexicon_repo.live_decisions_by_uri(test_db, ontology_id=ONTOLOGY_ID)
        assert live[CONTACT_ROLE_URI]["label"] == "job title"

        history = lexicon_repo.decision_history(test_db, concept_uri=CONTACT_ROLE_URI)
        assert [h["label"] for h in history] == ["job title", "contact role"]
        assert [h["decided_by"] for h in history] == ["sam", "arthur"]
