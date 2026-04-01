"""Quality metrics API endpoints (PRD §6.13, §3.2).

Thin route handlers that delegate to the quality_metrics service.
"""

import logging

from fastapi import APIRouter, HTTPException

from app.db.client import get_db
from app.services.quality_metrics import (
    compute_extraction_quality,
    compute_ontology_quality,
    compute_quality_summary,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/quality", tags=["quality"])


@router.get("/summary")
async def quality_summary() -> dict:
    """Aggregate quality metrics across all registered ontologies."""
    try:
        db = get_db()
        return compute_quality_summary(db)
    except Exception as exc:
        log.exception("Failed to compute quality summary")
        raise HTTPException(status_code=500, detail="Internal server error") from exc


@router.get("/{ontology_id}")
async def quality_for_ontology(ontology_id: str) -> dict:
    """Return structural and extraction quality scores for an ontology."""
    try:
        db = get_db()
        ontology_quality = compute_ontology_quality(db, ontology_id)
        extraction_quality = compute_extraction_quality(db, ontology_id)
        return {
            **ontology_quality,
            **extraction_quality,
        }
    except Exception as exc:
        log.exception("Failed to compute quality for ontology %s", ontology_id)
        raise HTTPException(status_code=500, detail="Internal server error") from exc
