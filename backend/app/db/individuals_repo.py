"""Persistence for the assertion graph (A-box) — Stream 21 / AB-PR1.

Named individuals (instances) + their type (``rdf_type``) and relationship
assertions (``individual_assertion``), grounded in the extracted/merged T-box.
Individuals are temporal (versioned) like T-box classes; edges use the temporal
edge helper. Span-level ``provenance`` (doc/chunk/char-span) is carried on every
individual and assertion so each fact is traceable (FR-18.5).
"""

from __future__ import annotations

from typing import Any, cast

from arango.database import StandardDatabase

from app.db.client import get_db
from app.db.ontology_repo import create_edge
from app.db.temporal_constants import NEVER_EXPIRES
from app.db.utils import run_aql
from app.services.temporal import create_version, expire_entity

INDIVIDUALS = "ontology_individuals"
RDF_TYPE = "rdf_type"
ASSERTION = "individual_assertion"


def create_individual(
    db: StandardDatabase | None = None,
    *,
    ontology_id: str,
    class_key: str,
    label: str,
    uri: str | None = None,
    provenance: list[dict[str, Any]] | None = None,
    data: dict[str, Any] | None = None,
    created_by: str = "abox",
) -> dict[str, Any]:
    """Create a named individual and its ``rdf_type`` edge to a T-box class.

    Returns the individual document. The individual is a temporal version; the
    type link is a temporal edge to ``ontology_classes/<class_key>``.
    """
    if db is None:
        db = get_db()
    doc = {
        **(data or {}),
        "ontology_id": ontology_id,
        "label": label,
        "uri": uri,
        "provenance": provenance or [],
        "version": 1,
    }
    individual = create_version(
        db,
        collection=INDIVIDUALS,
        data=doc,
        created_by=created_by,
        change_type="initial",
        change_summary=f"Created individual {label}",
    )
    create_edge(
        db,
        edge_collection=RDF_TYPE,
        from_id=str(individual["_id"]),
        to_id=f"ontology_classes/{class_key}",
        data={"ontology_id": ontology_id},
    )
    return individual


def add_assertion(
    db: StandardDatabase | None = None,
    *,
    ontology_id: str,
    from_individual_id: str,
    to_id: str,
    predicate: str,
    provenance: list[dict[str, Any]] | None = None,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Add a relationship assertion edge between individuals (or to a value)."""
    if db is None:
        db = get_db()
    return create_edge(
        db,
        edge_collection=ASSERTION,
        from_id=from_individual_id,
        to_id=to_id,
        data={
            **(data or {}),
            "ontology_id": ontology_id,
            "predicate": predicate,
            "provenance": provenance or [],
        },
    )


def list_individuals_with_types(
    db: StandardDatabase | None,
    ontology_id: str,
    *,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """List live individuals for an ontology, each with its rdf:type class.

    Resolves the ``rdf_type`` edge to the T-box class in one AQL pass so the
    instance-lens UI (AB-PR6) can show ``label`` + type + provenance without a
    per-row follow-up. Returns ``[]`` if the A-box collection is absent.
    """
    if db is None:
        db = get_db()
    if not db.has_collection(INDIVIDUALS):
        return []
    return list(
        run_aql(
            db,
            f"""
            FOR i IN {INDIVIDUALS}
              FILTER i.ontology_id == @oid AND i.expired == @never
              LET t = FIRST(
                FOR e IN {RDF_TYPE}
                  FILTER e._from == i._id AND e.expired == @never
                  FOR c IN ontology_classes FILTER c._id == e._to
                    LIMIT 1 RETURN {{key: c._key, label: c.label}}
              )
              SORT i.label ASC
              LIMIT @offset, @count
              RETURN {{
                _key: i._key,
                label: i.label,
                provenance: i.provenance,
                type_key: t.key,
                type_label: t.label
              }}
            """,
            bind_vars={
                "oid": ontology_id,
                "never": NEVER_EXPIRES,
                "offset": offset,
                "count": limit,
            },
        )
    )


def get_individual(db: StandardDatabase | None, key: str) -> dict[str, Any] | None:
    if db is None:
        db = get_db()
    rows = list(
        run_aql(
            db,
            f"FOR i IN {INDIVIDUALS} FILTER i._key == @key AND i.expired == @never "
            f"LIMIT 1 RETURN i",
            bind_vars={"key": key, "never": NEVER_EXPIRES},
        )
    )
    return rows[0] if rows else None


def list_individuals(
    db: StandardDatabase | None,
    ontology_id: str,
    *,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    if db is None:
        db = get_db()
    if not db.has_collection(INDIVIDUALS):
        return []
    return list(
        run_aql(
            db,
            f"""
            FOR i IN {INDIVIDUALS}
              FILTER i.ontology_id == @oid AND i.expired == @never
              SORT i.label ASC
              LIMIT @offset, @count
              RETURN i
            """,
            bind_vars={
                "oid": ontology_id,
                "never": NEVER_EXPIRES,
                "offset": offset,
                "count": limit,
            },
        )
    )


# ---------------------------------------------------------------------------
# FR-18.13 — A-box canvas rendering (per-class instance expansion)
# ---------------------------------------------------------------------------


def count_individuals_by_class(
    db: StandardDatabase | None,
    ontology_id: str,
) -> dict[str, int]:
    """Live individual count per T-box class key, for an ontology.

    Powers the canvas "Instances (N)" affordance (FR-18.13) so a curator can see
    which classes are worth expanding WITHOUT loading any individual. Returns an
    empty mapping when the A-box collections do not exist yet.
    """
    if db is None:
        db = get_db()
    if not (db.has_collection(INDIVIDUALS) and db.has_collection(RDF_TYPE)):
        return {}
    rows = run_aql(
        db,
        f"""
        FOR e IN {RDF_TYPE}
          FILTER e.expired == @never
          FOR i IN {INDIVIDUALS}
            FILTER i._id == e._from
              AND i.expired == @never
              AND i.ontology_id == @oid
            COLLECT ck = PARSE_IDENTIFIER(e._to).key WITH COUNT INTO n
            RETURN {{class_key: ck, count: n}}
        """,
        bind_vars={"oid": ontology_id, "never": NEVER_EXPIRES},
    )
    return {str(r["class_key"]): int(r["count"]) for r in rows if r.get("class_key")}


def get_instance_graph(
    db: StandardDatabase | None,
    ontology_id: str,
    *,
    class_keys: list[str],
    limit_per_class: int = 25,
) -> dict[str, Any]:
    """Individuals typed to ``class_keys``, plus their type + assertion edges.

    This is a DEDICATED read path, deliberately not folded into the effective-graph
    projection (``ontology_effective``): instance volume dwarfs class volume, and
    the canvas T-box fetch is latency-sensitive (Stream 12 T6). Expansion is
    per-class and capped by ``limit_per_class`` so one document's extraction cannot
    swamp the layout.

    ``assertions`` are restricted to edges whose BOTH endpoints are in the returned
    individual set — a dangling half-edge would render as an arrow into nothing.

    Returns ``{individuals, rdf_type_edges, assertions, truncated}`` where
    ``truncated`` lists the class keys that hit ``limit_per_class``.
    """
    if db is None:
        db = get_db()
    empty: dict[str, Any] = {
        "individuals": [],
        "rdf_type_edges": [],
        "assertions": [],
        "truncated": [],
    }
    if not class_keys:
        return empty
    if not (db.has_collection(INDIVIDUALS) and db.has_collection(RDF_TYPE)):
        return empty

    # Per-class LIMIT must live inside a subquery: a LIMIT in the nested FOR would
    # cap the flattened result set instead of each class's slice.
    grouped = run_aql(
        db,
        f"""
        FOR ck IN @class_keys
          LET rows = (
            FOR e IN {RDF_TYPE}
              FILTER e._to == CONCAT("ontology_classes/", ck)
                AND e.expired == @never
              FOR i IN {INDIVIDUALS}
                FILTER i._id == e._from
                  AND i.expired == @never
                  AND i.ontology_id == @oid
                SORT i.label ASC
                LIMIT @cap
                RETURN {{
                  individual: {{
                    _key: i._key,
                    _id: i._id,
                    label: i.label,
                    uri: i.uri,
                    status: i.status,
                    provenance: i.provenance,
                    ontology_id: i.ontology_id
                  }},
                  edge: {{_key: e._key, _from: e._from, _to: e._to}}
                }}
          )
          RETURN {{class_key: ck, rows: rows}}
        """,
        bind_vars={
            "oid": ontology_id,
            "class_keys": class_keys,
            "never": NEVER_EXPIRES,
            "cap": limit_per_class,
        },
    )

    individuals: list[dict[str, Any]] = []
    rdf_type_edges: list[dict[str, Any]] = []
    truncated: list[str] = []
    seen: set[str] = set()
    for group in grouped:
        rows = group.get("rows") or []
        if len(rows) >= limit_per_class:
            truncated.append(str(group["class_key"]))
        for row in rows:
            ind = row["individual"]
            # An individual with two live rdf_type edges (multi-typing) would
            # otherwise be emitted twice and collide on node id in the canvas.
            if ind["_id"] not in seen:
                seen.add(ind["_id"])
                individuals.append(ind)
            rdf_type_edges.append(row["edge"])

    assertions: list[dict[str, Any]] = []
    if seen and db.has_collection(ASSERTION):
        assertions = list(
            run_aql(
                db,
                f"""
                FOR a IN {ASSERTION}
                  FILTER a.expired == @never
                    AND a._from IN @ids
                    AND a._to IN @ids
                  RETURN {{
                    _key: a._key,
                    _from: a._from,
                    _to: a._to,
                    predicate: a.predicate,
                    provenance: a.provenance
                  }}
                """,
                bind_vars={"ids": sorted(seen), "never": NEVER_EXPIRES},
            )
        )

    return {
        "individuals": individuals,
        "rdf_type_edges": rdf_type_edges,
        "assertions": assertions,
        "truncated": truncated,
    }


# ---------------------------------------------------------------------------
# FR-18.9 — A-box curation write path (approve / reject / edit)
# ---------------------------------------------------------------------------

CURATION_ACTIONS = ("approve", "reject", "edit")


def _live_edge_keys(
    db: StandardDatabase, collection: str, aql_filter: str, ind_id: str
) -> list[str]:
    """Keys of the live (unexpired) edges in ``collection`` matching ``aql_filter``."""
    return [
        str(k)
        for k in run_aql(
            db,
            f"FOR e IN {collection} FILTER {aql_filter} AND e.expired == @never RETURN e._key",
            bind_vars={"id": ind_id, "never": NEVER_EXPIRES},
        )
    ]


def _expire_individual_edges(db: StandardDatabase, ind_id: str) -> int:
    """Temporally expire the ``rdf_type`` + ``individual_assertion`` edges touching
    an individual (used on reject). Returns the number of edges expired."""
    expired = 0
    for coll, aql_filter in (
        (RDF_TYPE, "e._from == @id"),
        (ASSERTION, "(e._from == @id OR e._to == @id)"),
    ):
        if not db.has_collection(coll):
            continue
        for ekey in _live_edge_keys(db, coll, aql_filter, ind_id):
            expire_entity(db, collection=coll, key=ekey)
            expired += 1
    return expired


def _retype_individual(
    db: StandardDatabase, ind_id: str, ontology_id: str | None, class_key: str
) -> None:
    """Expire the individual's current ``rdf_type`` edge(s) and link a fresh one
    to ``ontology_classes/<class_key>`` (used on edit when the type changes)."""
    if db.has_collection(RDF_TYPE):
        for ekey in _live_edge_keys(db, RDF_TYPE, "e._from == @id", ind_id):
            expire_entity(db, collection=RDF_TYPE, key=ekey)
    create_edge(
        db,
        edge_collection=RDF_TYPE,
        from_id=ind_id,
        to_id=f"ontology_classes/{class_key}",
        data={"ontology_id": ontology_id},
    )


def curate_individual(
    db: StandardDatabase | None = None,
    *,
    key: str,
    action: str,
    label: str | None = None,
    class_key: str | None = None,
) -> dict[str, Any] | None:
    """Curate a named individual (FR-18.9): approve / reject / edit.

    * ``approve`` — mark the live individual ``status="approved"`` (a curator
      endorsement; the individual stays in the live A-box).
    * ``reject``  — temporal soft-delete: stamp ``status="rejected"`` then expire
      the individual and its ``rdf_type`` + ``individual_assertion`` edges. The
      fact drops out of the live A-box but remains queryable as-of a prior time
      (nothing is hard-deleted — matches the T-box curation contract).
    * ``edit``    — update the ``label`` and/or re-type: when ``class_key`` is
      given, expire the current ``rdf_type`` edge(s) and add a fresh one to the
      chosen class.

    Returns the individual document after curation (expired snapshot for reject),
    or ``None`` when the individual / A-box collection does not exist.
    """
    if action not in CURATION_ACTIONS:
        raise ValueError(
            f"unknown curation action: {action!r} (expected one of {CURATION_ACTIONS})"
        )
    if db is None:
        db = get_db()
    if not db.has_collection(INDIVIDUALS):
        return None
    doc = get_individual(db, key)
    if doc is None:
        return None
    ind_id = f"{INDIVIDUALS}/{key}"
    col = db.collection(INDIVIDUALS)

    if action == "approve":
        col.update({"_key": key, "status": "approved"})
    elif action == "reject":
        col.update({"_key": key, "status": "rejected"})
        _expire_individual_edges(db, ind_id)
        expire_entity(db, collection=INDIVIDUALS, key=key)
    elif action == "edit":
        patch: dict[str, Any] = {"_key": key}
        if label is not None:
            patch["label"] = label
        if len(patch) > 1:
            col.update(patch)
        if class_key:
            _retype_individual(db, ind_id, doc.get("ontology_id"), class_key)

    # ``col.get`` bypasses the live/expired filter so reject still returns the
    # (now-expired) snapshot rather than an ambiguous None.
    return cast("dict[str, Any] | None", col.get(key))
