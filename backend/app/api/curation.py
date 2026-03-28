"""Curation API endpoints — PRD Section 7.4.

All routes delegate to the curation and promotion services.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Query

from app.api.errors import NotFoundError, ValidationError
from app.models.curation import (
    BatchDecisionRequest,
    BatchDecisionResponse,
    CurationDecisionCreate,
    CurationDecisionResponse,
    MergeRequest,
    MergeResponse,
    PromotionReport,
    PromotionRequest,
    PromotionStatusResponse,
)
from app.services import curation as curation_svc
from app.services import promotion as promotion_svc

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/curation", tags=["curation"])


@router.post("/decide", response_model=CurationDecisionResponse)
async def record_decision(body: CurationDecisionCreate) -> dict:
    """Record a single curation decision (approve/reject/edit/merge)."""
    result = curation_svc.record_decision(
        run_id=body.run_id,
        entity_key=body.entity_key,
        entity_type=body.entity_type.value,
        action=body.action.value,
        curator_id=body.curator_id,
        notes=body.notes,
        edited_data=body.edited_data,
    )
    return result


@router.post("/batch", response_model=BatchDecisionResponse)
async def batch_decide(body: BatchDecisionRequest) -> dict:
    """Batch approve/reject/edit multiple entities in one call."""
    decisions = [
        {
            "entity_key": d.entity_key,
            "entity_type": d.entity_type.value,
            "action": d.action.value,
            "curator_id": d.curator_id,
            "notes": d.notes,
            "edited_data": d.edited_data,
        }
        for d in body.decisions
    ]

    result = curation_svc.batch_decide(run_id=body.run_id, decisions=decisions)
    return result


@router.get("/decisions")
async def list_decisions(
    run_id: str | None = Query(None, description="Filter by extraction run ID"),
    status: str | None = Query(None, description="Filter by action (approve|reject|edit|merge)"),
    cursor: str | None = Query(None, description="Pagination cursor"),
    limit: int = Query(25, ge=1, le=100, description="Page size"),
) -> dict:
    """List curation decisions (audit trail), filterable and paginated."""
    return curation_svc.get_decisions(
        run_id=run_id,
        status=status,
        cursor=cursor,
        limit=limit,
    )


@router.get("/decisions/{decision_id}", response_model=CurationDecisionResponse)
async def get_decision(decision_id: str) -> dict:
    """Get a single curation decision by ID."""
    result = curation_svc.get_decision(decision_id=decision_id)
    if result is None:
        raise NotFoundError(
            f"Decision '{decision_id}' not found",
            details={"decision_id": decision_id},
        )
    return result


@router.post("/merge", response_model=MergeResponse)
async def execute_merge(body: MergeRequest) -> dict:
    """Merge multiple entities into one target entity."""
    if body.target_key in body.source_keys:
        raise ValidationError(
            "target_key must not appear in source_keys",
            details={"target_key": body.target_key, "source_keys": body.source_keys},
        )

    result = curation_svc.merge_entities(
        source_keys=body.source_keys,
        target_key=body.target_key,
        merged_data=body.merged_data,
        curator_id=body.curator_id,
        notes=body.notes,
    )
    return result


@router.post("/promote/{run_id}", response_model=PromotionReport)
async def promote_staging(run_id: str, body: PromotionRequest | None = None) -> dict:
    """Promote approved staging entities to production graph."""
    ontology_id = body.ontology_id if body else None
    report = promotion_svc.promote_staging(
        run_id=run_id,
        ontology_id=ontology_id,
    )
    return report


@router.get("/promote/{run_id}/status", response_model=PromotionStatusResponse)
async def get_promotion_status(run_id: str) -> dict:
    """Get the promotion status for a run."""
    report = promotion_svc.get_promotion_status(run_id)
    if report is None:
        return {
            "run_id": run_id,
            "status": "not_started",
            "report": None,
        }
    return {
        "run_id": run_id,
        "status": report.get("status", "completed"),
        "report": report,
    }
