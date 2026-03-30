"""Quality metrics service — computes ontology and extraction quality scores.

Provides structural, confidence, and curation-based quality indicators
for individual ontologies and aggregate summaries (PRD §6.13, §3.2).
"""

from __future__ import annotations

import logging
import sys
from typing import Any

from arango.database import StandardDatabase

log = logging.getLogger(__name__)

NEVER_EXPIRES: int = sys.maxsize


def _has(db: StandardDatabase, name: str) -> bool:
    """Check whether a collection exists, swallowing errors."""
    try:
        return db.has_collection(name)
    except Exception:
        return False


def compute_ontology_quality(
    db: StandardDatabase,
    ontology_id: str,
) -> dict[str, Any]:
    """Compute structural and confidence quality metrics for a single ontology.

    Returns
    -------
    dict with keys:
        avg_confidence, class_count, property_count, completeness,
        orphan_count, has_cycles, classes_without_properties
    """
    class_count = 0
    property_count = 0
    avg_confidence: float | None = None

    if _has(db, "ontology_classes"):
        rows = list(db.aql.execute(
            "FOR c IN ontology_classes "
            "FILTER c.ontology_id == @oid AND c.expired == @never "
            "COLLECT AGGREGATE cnt = COUNT_UNIQUE(c._key), "
            "  avg_conf = AVG(c.confidence) "
            "RETURN { cnt, avg_conf }",
            bind_vars={"oid": ontology_id, "never": NEVER_EXPIRES},
        ))
        if rows:
            class_count = rows[0].get("cnt", 0) or 0
            avg_confidence = rows[0].get("avg_conf")

    if _has(db, "ontology_properties"):
        rows = list(db.aql.execute(
            "FOR p IN ontology_properties "
            "FILTER p.ontology_id == @oid AND p.expired == @never "
            "COLLECT WITH COUNT INTO cnt RETURN cnt",
            bind_vars={"oid": ontology_id, "never": NEVER_EXPIRES},
        ))
        property_count = rows[0] if rows else 0

    classes_with_props = 0
    if class_count > 0 and _has(db, "has_property"):
        rows = list(db.aql.execute(
            "FOR e IN has_property "
            "FILTER e.ontology_id == @oid AND e.expired == @never "
            "COLLECT from_id = e._from "
            "COLLECT WITH COUNT INTO cnt "
            "RETURN cnt",
            bind_vars={"oid": ontology_id, "never": NEVER_EXPIRES},
        ))
        classes_with_props = rows[0] if rows else 0

    completeness = (
        (classes_with_props / class_count * 100) if class_count > 0 else 0.0
    )
    classes_without_properties = max(0, class_count - classes_with_props)

    orphan_count = _count_orphans(db, ontology_id)
    has_cycles = _detect_cycles(db, ontology_id)

    return {
        "ontology_id": ontology_id,
        "avg_confidence": round(avg_confidence, 4) if avg_confidence is not None else None,
        "class_count": class_count,
        "property_count": property_count,
        "completeness": round(completeness, 2),
        "orphan_count": orphan_count,
        "has_cycles": has_cycles,
        "classes_without_properties": classes_without_properties,
    }


def _count_orphans(db: StandardDatabase, ontology_id: str) -> int:
    """Count classes with no subclass_of parent that are not root classes.

    A root class is one where at least one other class is a subclass of it.
    An orphan is a class with no parent AND no children — truly disconnected.
    """
    if not _has(db, "ontology_classes"):
        return 0
    if not _has(db, "subclass_of"):
        rows = list(db.aql.execute(
            "FOR c IN ontology_classes "
            "FILTER c.ontology_id == @oid AND c.expired == @never "
            "COLLECT WITH COUNT INTO cnt RETURN cnt",
            bind_vars={"oid": ontology_id, "never": NEVER_EXPIRES},
        ))
        count = rows[0] if rows else 0
        return count if count > 1 else 0

    rows = list(db.aql.execute(
        "LET all_classes = ("
        "  FOR c IN ontology_classes "
        "  FILTER c.ontology_id == @oid AND c.expired == @never "
        "  RETURN c._id "
        ") "
        "LET children = ("
        "  FOR e IN subclass_of "
        "  FILTER e.ontology_id == @oid AND e.expired == @never "
        "  RETURN DISTINCT e._from "
        ") "
        "LET parents = ("
        "  FOR e IN subclass_of "
        "  FILTER e.ontology_id == @oid AND e.expired == @never "
        "  RETURN DISTINCT e._to "
        ") "
        "LET connected = UNION_DISTINCT(children, parents) "
        "FOR cls_id IN all_classes "
        "  FILTER cls_id NOT IN connected "
        "  COLLECT WITH COUNT INTO cnt "
        "RETURN cnt",
        bind_vars={"oid": ontology_id, "never": NEVER_EXPIRES},
    ))
    return rows[0] if rows else 0


def _detect_cycles(db: StandardDatabase, ontology_id: str) -> bool:
    """Detect cycles in the subclass_of hierarchy via AQL traversal."""
    if not _has(db, "subclass_of") or not _has(db, "ontology_classes"):
        return False

    rows = list(db.aql.execute(
        "FOR c IN ontology_classes "
        "FILTER c.ontology_id == @oid AND c.expired == @never "
        "LIMIT 1 "
        "LET cycle_check = ("
        "  FOR v, e, p IN 1..100 OUTBOUND c subclass_of "
        "    OPTIONS {uniqueEdges: 'path'} "
        "    FILTER e.expired == @never "
        "    FILTER v._id == c._id "
        "    LIMIT 1 "
        "    RETURN true "
        ") "
        "FILTER LENGTH(cycle_check) > 0 "
        "RETURN true",
        bind_vars={"oid": ontology_id, "never": NEVER_EXPIRES},
    ))
    if rows:
        return True

    rows = list(db.aql.execute(
        "FOR c IN ontology_classes "
        "FILTER c.ontology_id == @oid AND c.expired == @never "
        "LET cycle_check = ("
        "  FOR v, e, p IN 1..100 OUTBOUND c subclass_of "
        "    OPTIONS {uniqueEdges: 'path'} "
        "    FILTER e.expired == @never "
        "    FILTER v._id == c._id "
        "    LIMIT 1 "
        "    RETURN true "
        ") "
        "FILTER LENGTH(cycle_check) > 0 "
        "LIMIT 1 "
        "RETURN true",
        bind_vars={"oid": ontology_id, "never": NEVER_EXPIRES},
    ))
    return len(rows) > 0


def compute_extraction_quality(
    db: StandardDatabase,
    ontology_id: str,
) -> dict[str, Any]:
    """Compute extraction-process quality metrics (curation acceptance, time-to-ontology).

    Returns
    -------
    dict with keys: acceptance_rate, time_to_ontology_ms
    """
    acceptance_rate: float | None = None
    if _has(db, "curation_decisions"):
        rows = list(db.aql.execute(
            "FOR d IN curation_decisions "
            "FILTER d.ontology_id == @oid "
            "  OR (HAS(d, 'run_id') AND d.run_id IN ("
            "    FOR r IN extraction_runs "
            "    FILTER HAS(r, 'ontology_id') AND r.ontology_id == @oid "
            "    RETURN r._key"
            "  )) "
            "COLLECT AGGREGATE "
            "  accepted = SUM(d.action == 'approve' ? 1 : 0), "
            "  rejected = SUM(d.action == 'reject' ? 1 : 0), "
            "  edited   = SUM(d.action == 'edit' ? 1 : 0) "
            "RETURN { accepted, rejected, edited }",
            bind_vars={"oid": ontology_id},
        ))
        if rows:
            r = rows[0]
            total = (r.get("accepted") or 0) + (r.get("rejected") or 0) + (r.get("edited") or 0)
            if total > 0:
                acceptance_rate = round((r.get("accepted") or 0) / total, 4)

    time_to_ontology_ms: int | None = None
    if _has(db, "ontology_registry") and _has(db, "extraction_runs"):
        rows = list(db.aql.execute(
            "FOR o IN ontology_registry "
            "FILTER o._key == @oid "
            "LIMIT 1 "
            "LET run_id = o.extraction_run_id "
            "LET run = DOCUMENT(CONCAT('extraction_runs/', run_id)) "
            "LET doc_id = o.source_document_id "
            "LET doc = doc_id ? DOCUMENT(CONCAT('documents/', doc_id)) : null "
            "RETURN { "
            "  completed_at: run.completed_at, "
            "  uploaded_at: doc.uploaded_at "
            "}",
            bind_vars={"oid": ontology_id},
        ))
        if rows and rows[0]:
            completed = rows[0].get("completed_at")
            uploaded = rows[0].get("uploaded_at")
            if completed and uploaded:
                time_to_ontology_ms = int((completed - uploaded) * 1000)

    return {
        "ontology_id": ontology_id,
        "acceptance_rate": acceptance_rate,
        "time_to_ontology_ms": time_to_ontology_ms,
    }


def compute_quality_summary(db: StandardDatabase) -> dict[str, Any]:
    """Aggregate quality metrics across all registered ontologies."""
    ontology_ids: list[str] = []
    if _has(db, "ontology_registry"):
        ontology_ids = list(db.aql.execute(
            "FOR o IN ontology_registry RETURN o._key"
        ))

    if not ontology_ids:
        return {
            "ontology_count": 0,
            "total_classes": 0,
            "total_properties": 0,
            "avg_confidence": None,
            "avg_completeness": 0.0,
            "ontologies_with_cycles": 0,
            "total_orphans": 0,
        }

    total_classes = 0
    total_properties = 0
    all_confidences: list[float] = []
    all_completeness: list[float] = []
    ontologies_with_cycles = 0
    total_orphans = 0

    for oid in ontology_ids:
        try:
            oq = compute_ontology_quality(db, oid)
            total_classes += oq["class_count"]
            total_properties += oq["property_count"]
            if oq["avg_confidence"] is not None:
                all_confidences.append(oq["avg_confidence"])
            all_completeness.append(oq["completeness"])
            if oq["has_cycles"]:
                ontologies_with_cycles += 1
            total_orphans += oq["orphan_count"]
        except Exception:
            log.warning("quality computation failed for ontology %s", oid, exc_info=True)

    avg_confidence = (
        round(sum(all_confidences) / len(all_confidences), 4)
        if all_confidences
        else None
    )
    avg_completeness = (
        round(sum(all_completeness) / len(all_completeness), 2)
        if all_completeness
        else 0.0
    )

    return {
        "ontology_count": len(ontology_ids),
        "total_classes": total_classes,
        "total_properties": total_properties,
        "avg_confidence": avg_confidence,
        "avg_completeness": avg_completeness,
        "ontologies_with_cycles": ontologies_with_cycles,
        "total_orphans": total_orphans,
    }
