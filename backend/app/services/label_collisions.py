"""Label-collision detection and ingest (PRD §6.20 FR-20.1..FR-20.3).

Two producers feed one queue:

* **Local detection** (``detect_in_ontologies``) — groups live class and property
  labels across a set of AOE ontologies and flags any normalized label carried by
  more than one distinct concept. Needs no external system, so the queue is
  useful the day it ships.
* **Ingest** (``ingest_report``) — accepts a collision report from a producer
  that can see things AOE cannot: the extractor (same-document collisions) and
  the merge layer (cross-source ones). Those producers can supply ``source_system``
  and ``sample_values``, which AOE has no way to synthesise.

Detecting a collision is mechanical; resolving one is a domain judgement. This
module only ever files work — it never picks a label.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from arango.database import StandardDatabase

from app.db import lexicon_repo
from app.db.temporal_constants import NEVER_EXPIRES
from app.db.utils import run_aql

log = logging.getLogger(__name__)

# Labels so generic that flagging them would bury the real signal. These collide
# by design across almost every catalog and carry no disambiguating judgement.
STOPWORD_LABELS = frozenset(
    {"id", "name", "type", "status", "created", "updated", "description", "value", "key"}
)

_CONCEPT_SOURCES: tuple[tuple[str, str], ...] = (
    ("ontology_classes", "class"),
    ("ontology_datatype_properties", "datatype_property"),
    ("ontology_object_properties", "object_property"),
)


def _live_concepts(db: StandardDatabase, ontology_ids: list[str]) -> list[dict[str, Any]]:
    """Every live class/property in the given ontologies, flattened."""
    rows: list[dict[str, Any]] = []
    for collection, concept_type in _CONCEPT_SOURCES:
        if not db.has_collection(collection):
            continue
        found = run_aql(
            db,
            f"""
            FOR c IN {collection}
              FILTER c.ontology_id IN @oids AND c.expired == @never
              RETURN {{
                uri: c.uri,
                label: c.label,
                description: c.description,
                ontology_id: c.ontology_id
              }}
            """,
            bind_vars={"oids": ontology_ids, "never": NEVER_EXPIRES},
        )
        for row in found:
            if not row.get("uri") or not row.get("label"):
                continue
            rows.append({**row, "concept_type": concept_type})
    return rows


def detect_in_ontologies(
    db: StandardDatabase | None = None,
    *,
    ontology_ids: list[str],
    scope: str | None = None,
    include_stopwords: bool = False,
    persist: bool = True,
) -> dict[str, Any]:
    """Flag labels carried by more than one distinct concept.

    Two concepts collide when they share a normalized label but differ by
    ``uri``. Comparing on ``uri`` (not ``_key``) means the same concept seen in
    two ontologies is NOT a collision — that is reuse, which is the point of
    imports — while ``Document.role`` vs ``Contact.role`` is.
    """
    if db is None:
        from app.db.client import get_db

        db = get_db()
    if not ontology_ids:
        return {"scope": scope or "", "collisions": [], "detected": 0, "skipped_stopwords": 0}

    effective_scope = scope or "+".join(sorted(ontology_ids))
    concepts = _live_concepts(db, ontology_ids)

    grouped: dict[str, dict[str, dict[str, Any]]] = {}
    for concept in concepts:
        normalized = lexicon_repo.normalize_label(str(concept["label"]))
        if not normalized:
            continue
        # Dedupe by uri inside a group: the same concept re-extracted into two
        # live rows (the resurrection duplicate) is one occurrence, not a collision.
        grouped.setdefault(normalized, {})[str(concept["uri"])] = concept

    collisions: list[dict[str, Any]] = []
    skipped = 0
    now = time.time()
    for normalized, by_uri in sorted(grouped.items()):
        if len(by_uri) < 2:
            continue
        if normalized in STOPWORD_LABELS and not include_stopwords:
            skipped += 1
            continue
        occurrences = [
            {
                "concept_uri": uri,
                "concept_type": c["concept_type"],
                "ontology_id": c.get("ontology_id"),
                "label": c.get("label"),
                "description": c.get("description") or "",
                "source_system": None,
                "sample_values": [],
            }
            for uri, c in sorted(by_uri.items())
        ]
        record = {
            "scope": effective_scope,
            "label": next(iter(by_uri.values()))["label"],
            "normalized_label": normalized,
            "occurrences": occurrences,
        }
        if persist:
            record = lexicon_repo.upsert_collision(
                db,
                scope=effective_scope,
                label=str(record["label"]),
                occurrences=occurrences,
                source="local",
                detected_at=now,
            )
        collisions.append(record)

    log.info(
        "label collision detection complete",
        extra={
            "scope": effective_scope,
            "collisions": len(collisions),
            "skipped_stopwords": skipped,
        },
    )
    return {
        "scope": effective_scope,
        "collisions": collisions,
        "detected": len(collisions),
        "skipped_stopwords": skipped,
    }


def ingest_report(
    db: StandardDatabase | None = None,
    *,
    scope: str,
    items: list[dict[str, Any]],
    source: str = "ingest",
) -> dict[str, Any]:
    """Accept a collision report from an external producer.

    Each item needs a ``label`` and at least two ``occurrences``; an occurrence
    needs a ``concept_uri``. ``source_system`` and ``sample_values`` are optional
    but are the most useful fields a producer can supply — seeing ``"signal"`` /
    ``"qbr"`` beside ``"champion"`` / ``"exec"`` settles a naming question faster
    than any description.

    Malformed items are skipped and reported rather than failing the batch: a
    producer sending one bad row should not lose the other ninety-nine.
    """
    if db is None:
        from app.db.client import get_db

        db = get_db()

    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    now = time.time()

    for index, item in enumerate(items):
        label = str(item.get("label") or "").strip()
        occurrences = item.get("occurrences") or []
        if not label:
            rejected.append({"index": index, "reason": "missing label"})
            continue
        if not isinstance(occurrences, list) or len(occurrences) < 2:
            rejected.append({"index": index, "reason": "need at least 2 occurrences"})
            continue
        normalized_occurrences: list[dict[str, Any]] = []
        malformed = False
        for occ in occurrences:
            if not isinstance(occ, dict) or not occ.get("concept_uri"):
                malformed = True
                break
            normalized_occurrences.append(
                {
                    "concept_uri": str(occ["concept_uri"]),
                    "concept_type": occ.get("concept_type"),
                    "ontology_id": occ.get("ontology_id"),
                    "label": occ.get("label") or label,
                    "description": occ.get("description") or "",
                    "source_system": occ.get("source_system"),
                    "sample_values": list(occ.get("sample_values") or []),
                }
            )
        if malformed:
            rejected.append({"index": index, "reason": "occurrence missing concept_uri"})
            continue

        accepted.append(
            lexicon_repo.upsert_collision(
                db,
                scope=scope,
                label=label,
                occurrences=normalized_occurrences,
                source=source,
                detected_at=now,
            )
        )

    log.info(
        "label collision report ingested",
        extra={"scope": scope, "accepted": len(accepted), "rejected": len(rejected)},
    )
    return {
        "scope": scope,
        "accepted": len(accepted),
        "rejected": rejected,
        "collisions": accepted,
    }


def resolve_collision(
    db: StandardDatabase | None = None,
    *,
    collision_key: str,
    resolutions: list[dict[str, Any]],
    curator_id: str,
    dismiss: bool = False,
) -> dict[str, Any]:
    """Record the curator's decision for a collision and close it.

    ``resolutions`` is one entry per concept the curator renamed —
    ``{concept_uri, label, concept_type, ontology_id, description?, rationale?}``.
    Renaming only one side of a collision is legitimate and common (often the
    right answer is to leave one alone), so a partial resolution is accepted.

    ``dismiss=True`` closes the item without recording any decision — for
    collisions that are genuinely fine as they are.
    """
    if db is None:
        from app.db.client import get_db

        db = get_db()

    collision = lexicon_repo.get_collision(db, key=collision_key)
    if collision is None:
        raise ValueError(f"collision {collision_key!r} not found")

    if dismiss:
        updated = lexicon_repo.set_collision_status(
            db, key=collision_key, status="dismissed", curator_id=curator_id
        )
        return {"collision": updated, "decisions": []}

    if not resolutions:
        raise ValueError("resolve requires at least one resolution (or dismiss=True)")

    known_uris = {str(o.get("concept_uri")) for o in (collision.get("occurrences") or [])}
    decisions: list[dict[str, Any]] = []
    for resolution in resolutions:
        concept_uri = str(resolution.get("concept_uri") or "")
        if concept_uri not in known_uris:
            # Guards against a stale UI resolving a concept that is not part of
            # this collision, which would park an unreachable decision.
            raise ValueError(
                f"concept_uri {concept_uri!r} is not one of this collision's occurrences"
            )
        decisions.append(
            lexicon_repo.record_label_decision(
                db,
                ontology_id=str(resolution.get("ontology_id") or ""),
                concept_uri=concept_uri,
                concept_type=str(resolution.get("concept_type") or "datatype_property"),
                label=str(resolution["label"]),
                description=resolution.get("description"),
                rationale=resolution.get("rationale"),
                curator_id=curator_id,
                collision_key=collision_key,
            )
        )

    updated = lexicon_repo.set_collision_status(
        db, key=collision_key, status="resolved", curator_id=curator_id
    )
    return {"collision": updated, "decisions": decisions}
