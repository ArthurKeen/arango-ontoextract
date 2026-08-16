"""032 — Curated lexicon: label collisions + label decisions (FR-20.1..FR-20.5).

Two collections that together let a curator resolve a colliding attribute/class
label and have that resolution SURVIVE re-extraction:

* ``label_collisions`` -- the work queue. One document per (scope, normalized
  label) so re-detecting an unresolved collision updates it in place instead of
  piling up duplicates. Carries the occurrences (which concept, which ontology,
  which source system, sample values where a producer supplied them).

* ``label_decisions`` -- the curator's decision, keyed by ``concept_uri`` rather
  than by document ``_key``. This is the load-bearing choice: extraction OWNS
  entity ``_key``s (it rebuilds them from the LLM's label and re-inserts with
  ``overwrite=True``), so a decision stored on the entity is reclaimed on the
  next run. Storing it in a collection extraction never writes makes the
  decision durable by construction. Read paths merge it over the extracted label.

``label_decisions`` is temporal (``created`` / ``expired`` = NEVER_EXPIRES) like
the rest of the ontology store, so re-deciding a concept expires the prior
decision rather than erasing it -- the audit trail IS the feature.
"""

from __future__ import annotations

import logging

from arango.database import StandardDatabase
from arango.exceptions import IndexCreateError

log = logging.getLogger(__name__)

_COLLISIONS = "label_collisions"
_DECISIONS = "label_decisions"

# (collection, is_edge, ((index_name, fields, sparse, unique), ...))
_COLLECTIONS = (
    (
        _COLLISIONS,
        False,
        (
            ("idx_collisions_status", ["status"], False, False),
            ("idx_collisions_label", ["normalized_label"], False, False),
            ("idx_collisions_detected", ["detected_at"], False, False),
        ),
    ),
    (
        _DECISIONS,
        False,
        (
            # The overlay's hot lookup: live decisions for one ontology.
            ("idx_decisions_ontology_expired", ["ontology_id", "expired"], False, False),
            # The join key. Not unique: history rows share a concept_uri and are
            # separated by ``expired``.
            ("idx_decisions_concept_uri", ["concept_uri", "expired"], False, False),
            ("idx_decisions_collision", ["collision_key"], True, False),
        ),
    ),
)


def up(db: StandardDatabase) -> None:
    for name, is_edge, indexes in _COLLECTIONS:
        if not db.has_collection(name):
            db.create_collection(name, edge=is_edge)
            log.info("created %s collection %s", "edge" if is_edge else "document", name)
        col = db.collection(name)
        existing = {idx.get("name") for idx in col.indexes()}
        for idx_name, fields, sparse, unique in indexes:
            if idx_name in existing:
                continue
            try:
                col.add_persistent_index(fields=fields, name=idx_name, sparse=sparse, unique=unique)
                log.info("created index %s on %s", idx_name, name)
            except IndexCreateError:
                log.warning("could not create index %s on %s", idx_name, name, exc_info=True)


def down(db: StandardDatabase) -> None:
    for name, _is_edge, _indexes in _COLLECTIONS:
        if db.has_collection(name):
            db.delete_collection(name)
            log.info("dropped collection %s", name)
