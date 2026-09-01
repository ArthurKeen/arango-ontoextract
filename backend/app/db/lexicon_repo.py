"""Persistence for the curated lexicon — label collisions + label decisions.

Backs PRD §6.20 (FR-20.1..FR-20.5). Two concerns:

* **Collisions** (``label_collisions``) — the curator work queue. Keyed
  deterministically on ``(scope, normalized_label)`` so re-detection of an
  unresolved collision refreshes it rather than duplicating it.
* **Decisions** (``label_decisions``) — the curator's answer, joined to concepts
  by ``concept_uri``, NOT by document ``_key``.

The ``concept_uri`` join is the whole reason a decision survives re-extraction.
Extraction derives entity ``_key``s from the LLM's label and re-inserts with
``overwrite=True`` (see ``app.services.extraction``), so it reclaims any key it
has ever used. It never writes to ``label_decisions``, so a decision parked there
cannot be clobbered; read paths merge it back over the extracted label.
"""

from __future__ import annotations

import contextlib
import hashlib
import re
import time
from typing import Any, cast

from arango.database import StandardDatabase

from app.db.client import get_db
from app.db.temporal_constants import NEVER_EXPIRES
from app.db.utils import run_aql
from app.services.temporal import create_version, expire_entity

COLLISIONS = "label_collisions"
DECISIONS = "label_decisions"

#: Schema for the two lexicon collections, as
#: ``(collection, ((index_name, fields, sparse, unique), ...))``.
#:
#: Lives here rather than only in migration 032 so the SAME definition serves
#: both. The migration provisions a database up front; this lets the first
#: write provision one that was never migrated. Scanning WTW Ontology for
#: collisions returned "An unexpected error occurred" for exactly that reason:
#: ``label_collisions`` did not exist, the read path tolerated it and reported
#: "no collisions", and the write path raised a raw 404 from python-arango.
LEXICON_SCHEMA: tuple[tuple[str, tuple[tuple[str, list[str], bool, bool], ...]], ...] = (
    (
        COLLISIONS,
        (
            ("idx_collisions_status", ["status"], False, False),
            ("idx_collisions_label", ["normalized_label"], False, False),
            ("idx_collisions_detected", ["detected_at"], False, False),
        ),
    ),
    (
        DECISIONS,
        (
            ("idx_decisions_ontology_expired", ["ontology_id", "expired"], False, False),
            ("idx_decisions_concept_uri", ["concept_uri", "expired"], False, False),
            ("idx_decisions_collision", ["collision_key"], True, False),
        ),
    ),
)


def ensure_lexicon_collections(db: StandardDatabase) -> None:
    """Create the lexicon collections and their indexes if they are absent.

    Idempotent and cheap once provisioned: a ``has_collection`` probe per
    collection. Called from the write paths so the feature works on a database
    that has not had migration 032 applied, rather than failing with a 404 the
    user cannot act on.
    """
    for name, indexes in LEXICON_SCHEMA:
        if not db.has_collection(name):
            db.create_collection(name)
        col = db.collection(name)
        try:
            # python-arango types indexes() as a sync-vs-async union; in
            # synchronous mode it always returns the list.
            listed = cast("list[dict[str, Any]]", col.indexes() or [])
        except Exception:  # pragma: no cover -- index listing is best-effort
            continue
        existing = {idx.get("name") for idx in listed}
        for idx_name, fields, sparse, unique in indexes:
            if idx_name in existing:
                continue
            # A missing index is a performance problem, not a correctness one;
            # provisioning must not fail because of it.
            with contextlib.suppress(Exception):
                col.add_persistent_index(fields=fields, name=idx_name, sparse=sparse, unique=unique)


COLLISION_STATUSES = ("open", "resolved", "dismissed")
CONCEPT_TYPES = ("class", "datatype_property", "object_property")

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def normalize_label(label: str) -> str:
    """Fold a label to its comparison form.

    ``"Role"``, ``"role"``, ``"  role "`` and ``"ROLE"`` are the same collision;
    so are ``"job_title"`` / ``"job title"`` / ``"jobTitle"``. camelCase is split
    before folding so a camel-cased source column collides with its spaced twin.
    """
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", label or "")
    return _NON_ALNUM.sub(" ", spaced.lower()).strip()


def collision_key(scope: str, normalized: str) -> str:
    """Deterministic, filesystem/URL-safe key for a (scope, label) collision.

    Hashed rather than slugged because a normalized label can contain characters
    (and a length) that ArangoDB keys disallow.
    """
    digest = hashlib.sha256(f"{scope}\x00{normalized}".encode()).hexdigest()[:32]
    return f"{digest}"


# ---------------------------------------------------------------------------
# Collisions (the work queue)
# ---------------------------------------------------------------------------


def upsert_collision(
    db: StandardDatabase | None = None,
    *,
    scope: str,
    label: str,
    occurrences: list[dict[str, Any]],
    source: str = "local",
    detected_at: float | None = None,
) -> dict[str, Any]:
    """Insert or refresh one collision.

    A collision the curator already resolved or dismissed is NOT reopened by
    re-detection — that would drag settled decisions back into the queue every
    time a catalog refreshes, which is exactly the churn this feature exists to
    stop. Its occurrences are still refreshed so the record stays accurate.
    """
    if db is None:
        db = get_db()
    ensure_lexicon_collections(db)
    normalized = normalize_label(label)
    key = collision_key(scope, normalized)
    now = detected_at if detected_at is not None else time.time()
    col = db.collection(COLLISIONS)

    existing = cast("dict[str, Any] | None", col.get(key))
    if existing is None:
        doc = {
            "_key": key,
            "scope": scope,
            "label": label,
            "normalized_label": normalized,
            "occurrences": occurrences,
            "occurrence_count": len(occurrences),
            "status": "open",
            "source": source,
            "detected_at": now,
            "last_seen_at": now,
            "resolved_at": None,
            "resolved_by": None,
        }
        col.insert(doc)
        return doc

    patch = {
        "_key": key,
        "occurrences": occurrences,
        "occurrence_count": len(occurrences),
        "last_seen_at": now,
        "source": source,
    }
    col.update(patch)
    return {**existing, **patch}


def list_collisions(
    db: StandardDatabase | None = None,
    *,
    status: str | None = "open",
    scope: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """The work queue, most-recently-detected first."""
    if db is None:
        db = get_db()
    if not db.has_collection(COLLISIONS):
        return []
    filters = []
    bind: dict[str, Any] = {"offset": offset, "count": limit}
    if status:
        filters.append("c.status == @status")
        bind["status"] = status
    if scope:
        filters.append("c.scope == @scope")
        bind["scope"] = scope
    where = f"FILTER {' AND '.join(filters)}" if filters else ""
    return list(
        run_aql(
            db,
            f"""
            FOR c IN {COLLISIONS}
              {where}
              SORT c.detected_at DESC
              LIMIT @offset, @count
              RETURN c
            """,
            bind_vars=bind,
        )
    )


def get_collision(db: StandardDatabase | None = None, *, key: str) -> dict[str, Any] | None:
    if db is None:
        db = get_db()
    if not db.has_collection(COLLISIONS):
        return None
    doc = cast("dict[str, Any] | None", db.collection(COLLISIONS).get(key))
    return dict(doc) if doc else None


def set_collision_status(
    db: StandardDatabase | None = None,
    *,
    key: str,
    status: str,
    curator_id: str,
    at: float | None = None,
) -> dict[str, Any] | None:
    if status not in COLLISION_STATUSES:
        raise ValueError(f"unknown collision status {status!r} (expected {COLLISION_STATUSES})")
    if db is None:
        db = get_db()
    ensure_lexicon_collections(db)
    col = db.collection(COLLISIONS)
    if col.get(key) is None:
        return None
    col.update(
        {
            "_key": key,
            "status": status,
            "resolved_at": at if at is not None else time.time(),
            "resolved_by": curator_id,
        }
    )
    doc = cast("dict[str, Any] | None", col.get(key))
    return dict(doc) if doc else None


# ---------------------------------------------------------------------------
# Decisions (the durable answer)
# ---------------------------------------------------------------------------


def record_label_decision(
    db: StandardDatabase | None = None,
    *,
    ontology_id: str,
    concept_uri: str,
    concept_type: str,
    label: str,
    curator_id: str,
    description: str | None = None,
    rationale: str | None = None,
    collision_key: str | None = None,
) -> dict[str, Any]:
    """Record (or re-record) the chosen label for one concept.

    Re-deciding expires the prior decision instead of mutating it, so the trail
    of who chose what, and when, stays queryable — the audit trail is as much the
    point as the string.
    """
    if concept_type not in CONCEPT_TYPES:
        raise ValueError(f"unknown concept_type {concept_type!r} (expected {CONCEPT_TYPES})")
    if not concept_uri:
        raise ValueError("concept_uri is required — it is how a decision survives re-extraction")
    if db is None:
        db = get_db()
    ensure_lexicon_collections(db)

    prior = get_live_decision(db, concept_uri=concept_uri)
    if prior is not None:
        expire_entity(db, collection=DECISIONS, key=str(prior["_key"]))

    return create_version(
        db,
        collection=DECISIONS,
        data={
            "ontology_id": ontology_id,
            "concept_uri": concept_uri,
            "concept_type": concept_type,
            "label": label,
            "description": description,
            "rationale": rationale,
            "collision_key": collision_key,
            "decided_by": curator_id,
            "decided_at": time.time(),
            "supersedes": prior.get("_key") if prior else None,
            "version": int(prior.get("version", 1)) + 1 if prior else 1,
        },
        created_by=curator_id,
        change_type="label_decision",
        change_summary=f"Curated label for {concept_uri}: {label!r}",
    )


def get_live_decision(
    db: StandardDatabase | None = None, *, concept_uri: str
) -> dict[str, Any] | None:
    if db is None:
        db = get_db()
    if not db.has_collection(DECISIONS):
        return None
    rows = list(
        run_aql(
            db,
            f"FOR d IN {DECISIONS} FILTER d.concept_uri == @uri AND d.expired == @never "
            f"LIMIT 1 RETURN d",
            bind_vars={"uri": concept_uri, "never": NEVER_EXPIRES},
        )
    )
    return rows[0] if rows else None


def live_decisions_by_uri(
    db: StandardDatabase | None = None,
    *,
    ontology_id: str | None = None,
    existing_collections: set[str] | None = None,
) -> dict[str, dict[str, Any]]:
    """All live decisions as ``{concept_uri: decision}`` — the overlay's input.

    Scoped to one ontology when given. Returns ``{}`` when the collection does
    not exist yet, so every read path degrades to plain extracted labels rather
    than failing on an unmigrated database.

    ``existing_collections`` lets a caller that already snapshotted the database's
    collection names supply them. ``has_collection`` is a full round-trip, and the
    effective-graph path deliberately probes collection metadata exactly once to
    keep remote canvas latency down — it passes its snapshot in rather than
    letting this function add a probe per request.
    """
    if db is None:
        db = get_db()
    if existing_collections is not None:
        if DECISIONS not in existing_collections:
            return {}
    elif not db.has_collection(DECISIONS):
        return {}
    bind: dict[str, Any] = {"never": NEVER_EXPIRES}
    where = "FILTER d.expired == @never"
    if ontology_id is not None:
        where += " AND d.ontology_id == @oid"
        bind["oid"] = ontology_id
    rows = run_aql(
        db,
        f"""
        FOR d IN {DECISIONS}
          {where}
          RETURN {{
            concept_uri: d.concept_uri,
            label: d.label,
            description: d.description,
            decided_by: d.decided_by,
            decided_at: d.decided_at,
            concept_type: d.concept_type
          }}
        """,
        bind_vars=bind,
    )
    return {str(r["concept_uri"]): r for r in rows if r.get("concept_uri")}


def decision_history(
    db: StandardDatabase | None = None, *, concept_uri: str
) -> list[dict[str, Any]]:
    """Every decision ever recorded for a concept, newest first."""
    if db is None:
        db = get_db()
    if not db.has_collection(DECISIONS):
        return []
    return list(
        run_aql(
            db,
            f"FOR d IN {DECISIONS} FILTER d.concept_uri == @uri SORT d.decided_at DESC RETURN d",
            bind_vars={"uri": concept_uri},
        )
    )
