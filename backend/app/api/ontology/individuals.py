"""A-box individuals read API (Stream 21 / AB-PR6, PRD §6.18 FR-18.11).

Read surface for the assertion graph so the workspace instance lens can list an
ontology's named individuals (with their rdf:type class + span provenance) and
inspect one. Write/curation + RDF export are separate follow-ups.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.ontology import _shared
from app.db import individuals_repo
from app.services import abox_canonicalize, abox_validation, quality_metrics

router = APIRouter()


class CurateIndividualRequest(BaseModel):
    """Curation action on a single A-box individual (FR-18.9)."""

    action: Literal["approve", "reject", "edit"] = Field(
        ...,
        description="approve (endorse), reject (temporal soft-delete), or edit (relabel/retype)",
    )
    label: str | None = Field(default=None, description="New label (edit only).")
    class_key: str | None = Field(
        default=None, description="Re-type the individual to this ontology_classes key (edit only)."
    )


@router.get("/{ontology_id}/individuals/metrics")
async def individuals_metrics(ontology_id: str) -> dict[str, Any]:
    """A-box quality metrics: counts + grounding/typed rates (AB-PR6)."""
    return quality_metrics.compute_abox_metrics(_shared.get_db(), ontology_id)


@router.post("/{ontology_id}/individuals/canonicalize")
async def canonicalize_individuals(
    ontology_id: str,
    min_score: float = Query(0.85, ge=0.0, le=1.0),
    auto_merge: bool = Query(False),
) -> dict[str, Any]:
    """Detect (and optionally auto-merge) duplicate individuals (AB-PR3)."""
    return abox_canonicalize.canonicalize_ontology(
        _shared.get_db(), ontology_id=ontology_id, min_score=min_score, auto_merge=auto_merge
    )


@router.post("/{ontology_id}/individuals/validate")
async def validate_individuals(ontology_id: str) -> dict[str, Any]:
    """Validate the A-box: flag ungrounded / dangling-type / cardinality violations (AB-PR5)."""
    report = abox_validation.validate_abox(_shared.get_db(), ontology_id)
    return report.to_dict()


@router.get("/{ontology_id}/individuals/counts")
async def individuals_counts_by_class(ontology_id: str) -> dict[str, Any]:
    """Live individual count per T-box class key (FR-18.13).

    Lets the canvas show an "Instances (N)" affordance on each class without
    fetching a single individual.
    """
    counts = individuals_repo.count_individuals_by_class(_shared.get_db(), ontology_id)
    return {"ontology_id": ontology_id, "counts": counts, "total": sum(counts.values())}


@router.get("/{ontology_id}/instance-graph")
async def instance_graph(
    ontology_id: str,
    class_keys: list[str] = Query(
        default=[], description="T-box class keys to expand instances for."
    ),
    limit_per_class: int = Query(25, ge=1, le=200),
) -> dict[str, Any]:
    """Individuals for the named classes, with rdf:type + assertion edges (FR-18.13).

    Deliberately a separate endpoint from ``/effective``: instance volume dwarfs
    class volume, so folding it into the canvas T-box projection would regress the
    latency-sensitive path. Expansion is opt-in and capped per class.
    """
    return individuals_repo.get_instance_graph(
        _shared.get_db(),
        ontology_id,
        class_keys=class_keys,
        limit_per_class=limit_per_class,
    )


@router.get("/{ontology_id}/individuals")
async def list_individuals(
    ontology_id: str,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """List the ontology's A-box individuals, each with its type + provenance."""
    rows = individuals_repo.list_individuals_with_types(
        _shared.get_db(), ontology_id, limit=limit, offset=offset
    )
    return {"ontology_id": ontology_id, "data": rows, "count": len(rows)}


@router.get("/individuals/{individual_key}")
async def get_individual(individual_key: str) -> dict[str, Any]:
    """Fetch a single individual (with provenance + history-ready fields)."""
    doc = individuals_repo.get_individual(_shared.get_db(), individual_key)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"individual '{individual_key}' not found")
    return doc


@router.post("/individuals/{individual_key}/curate")
async def curate_individual(individual_key: str, body: CurateIndividualRequest) -> dict[str, Any]:
    """Approve / reject / edit an A-box individual (FR-18.9).

    Reject and re-type are temporal (the prior version stays queryable as-of a
    past time); nothing is hard-deleted.
    """
    try:
        doc = individuals_repo.curate_individual(
            _shared.get_db(),
            key=individual_key,
            action=body.action,
            label=body.label,
            class_key=body.class_key,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if doc is None:
        raise HTTPException(status_code=404, detail=f"individual '{individual_key}' not found")
    return doc
