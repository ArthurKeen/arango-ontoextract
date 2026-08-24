"""034 — Repair placeholder URIs on existing ontologies (FR-2.19).

The old extraction prompt showed the model ``"uri": "string (namespace#ClassName)"``
as its example, and the model did what it was shown. The result is a corpus where
most stored URIs are RELATIVE references — ``namespace#Vehicle`` — which are not
usable identities:

* they are not valid IRIs, so they cannot be serialised (one value containing a
  space, ``namespace#qualifiedPersonnel Recommended``, took down the whole
  Turtle export until export learned to normalise);
* identical relative references in two different ontologies denote the same
  thing when they should not, which matters because §6.20 joins curated label
  decisions to concepts BY URI.

The prompt is fixed and extraction normalises at write time, but neither helps
data already at rest. This migration repairs it.

REPORT-ONLY BY DEFAULT — unlike migration 033.
    Set ``APPLY=1`` to write. Without it this reports exactly what it would
    change and touches nothing. Rewriting ~4,000 identity fields is not
    something to do as a side effect of running migrations, and the
    user-visible symptom (export) is already fixed elsewhere, so there is no
    pressure to apply it blind.

SCOPE — deliberately narrow.
    Only the ``uri`` field on classes and properties, and only where the value
    is genuinely unusable (relative, or containing characters that cannot be
    serialised). Valid absolute IRIs are left alone even on documentation hosts
    such as ``example.org``: they serialise and round-trip, and silently
    changing an identifier someone chose is worse than the weakness.

    ``target_class_uri`` is NOT rewritten. Those values are LLM-emitted
    resolution hints (``wtw:Employer``, ``WTW:Benefit``) consumed by
    ``edge_repair.resolve_range_class``, whose uri -> fragment -> label tiers
    already treat the label tier as the workhorse. They are resolved at
    extraction time into materialised ``_from``/``_to`` edges, so rewriting
    stored class URIs cannot break an edge that already exists.

IF ``label_decisions`` EXISTS, ITS ``concept_uri`` IS MIGRATED IN LOCKSTEP.
    That collection joins decisions to concepts by URI; rewriting one side only
    would silently orphan every curated label. At the time of writing it does
    not exist in the target database, which makes this the cheapest moment to
    run the repair — the cost of deferring it rises as soon as curation starts.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from arango.database import StandardDatabase

from app.db.temporal_constants import NEVER_EXPIRES
from app.db.utils import run_aql
from app.services.ontology_uri import is_placeholder_uri, normalize_uri

log = logging.getLogger(__name__)

_COLLECTIONS = (
    "ontology_classes",
    "ontology_object_properties",
    "ontology_datatype_properties",
)


def _apply_requested() -> bool:
    return os.getenv("APPLY", "").strip() not in ("", "0", "false", "False")


def up(db: StandardDatabase) -> None:
    apply = _apply_requested()
    grand_total = 0
    samples: list[str] = []

    for coll in _COLLECTIONS:
        if not db.has_collection(coll):
            continue
        rows = list(
            run_aql(
                db,
                f"FOR c IN {coll} FILTER c.expired == @never "
                "RETURN {key: c._key, uri: c.uri, label: c.label, oid: c.ontology_id}",
                bind_vars={"never": NEVER_EXPIRES},
            )
        )
        bad = [r for r in rows if is_placeholder_uri(r.get("uri"))]
        grand_total += len(bad)
        log.warning("034: %s — %d of %d live docs have unusable URIs", coll, len(bad), len(rows))

        if not bad:
            continue
        for r in bad[:3]:
            fixed = normalize_uri(
                r.get("uri"),
                ontology_id=str(r.get("oid") or ""),
                label=str(r.get("label") or ""),
            )
            samples.append(f"{coll}: {r.get('uri')!r} -> {fixed!r}")
        if not apply:
            continue

        col = db.collection(coll)
        for r in bad:
            new = normalize_uri(
                r.get("uri"),
                ontology_id=str(r.get("oid") or ""),
                label=str(r.get("label") or ""),
            )
            try:
                col.update({"_key": r["key"], "uri": new})
            except Exception as exc:  # pragma: no cover — one bad row must not abort
                log.warning("034: could not update %s/%s: %s", coll, r["key"], exc)

    for s in samples[:9]:
        log.warning("034:   %s", s)

    _migrate_decisions(db, apply=apply)

    if apply:
        log.warning("034: rewrote %d URIs.", grand_total)
    else:
        log.warning(
            "034: REPORT ONLY — %d URIs would be rewritten. Set APPLY=1 to write.",
            grand_total,
        )


def _migrate_decisions(db: StandardDatabase, *, apply: bool) -> None:
    """Keep §6.20 label decisions joined to the concepts they describe."""
    if not db.has_collection("label_decisions"):
        log.info("034: label_decisions absent — no curated decisions to re-point")
        return
    rows: list[dict[str, Any]] = list(
        run_aql(
            db,
            "FOR d IN label_decisions RETURN {key: d._key, uri: d.concept_uri, "
            "oid: d.ontology_id, label: d.label}",
        )
    )
    bad = [r for r in rows if is_placeholder_uri(r.get("uri"))]
    log.warning("034: label_decisions — %d of %d reference an unusable URI", len(bad), len(rows))
    if not apply:
        return
    col = db.collection("label_decisions")
    for r in bad:
        col.update(
            {
                "_key": r["key"],
                "concept_uri": normalize_uri(
                    r.get("uri"),
                    ontology_id=str(r.get("oid") or ""),
                    label=str(r.get("label") or ""),
                ),
            }
        )


def down(db: StandardDatabase) -> None:
    """Not reversible.

    The previous values were unusable identities; restoring them would
    reintroduce the export failure. Prior versions remain visible through the
    temporal history of each entity.
    """
    log.info("034: down() is a no-op — the old URIs were not valid identities")
