"""Curated-lexicon API — collision queue + label decisions (PRD §6.20).

Read/write surface for the workflow that brings a colliding label to a curator
and records what they decided:

* ``GET  /lexicon/collisions``               — the work queue
* ``POST /lexicon/collisions/detect``        — local detection across ontologies
* ``POST /lexicon/collisions/ingest``        — external producer report
* ``POST /lexicon/collisions/{key}/resolve`` — record the decision, close the item
* ``GET  /lexicon/decisions``                — live curated labels
* ``GET  /lexicon/decisions/history``        — every decision for one concept
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.ontology import _shared
from app.db import lexicon_repo
from app.services import label_collisions

router = APIRouter()


class DetectRequest(BaseModel):
    ontology_ids: list[str] = Field(..., description="Ontologies to scan for colliding labels.")
    scope: str | None = Field(
        default=None,
        description="Label for this detection run; defaults to the joined ontology ids.",
    )
    include_stopwords: bool = Field(
        default=False,
        description="Include generic labels (id, name, type, ...) that collide by design.",
    )


class IngestOccurrence(BaseModel):
    concept_uri: str = Field(..., description="Stable concept identity; the decision join key.")
    concept_type: str | None = None
    ontology_id: str | None = None
    label: str | None = None
    description: str | None = None
    source_system: str | None = Field(
        default=None, description="Which system this concept came from."
    )
    sample_values: list[str] = Field(
        default_factory=list,
        description="Example values; often settles the judgement faster than a description.",
    )


class IngestItem(BaseModel):
    label: str
    occurrences: list[IngestOccurrence] = Field(default_factory=list)


class IngestRequest(BaseModel):
    scope: str = Field(..., description="Producer-defined scope, e.g. a catalog or run id.")
    source: str = Field(default="ingest", description="Producing system.")
    items: list[IngestItem] = Field(default_factory=list)


class Resolution(BaseModel):
    concept_uri: str
    label: str = Field(..., description="The curator's chosen label for this concept.")
    concept_type: str = "datatype_property"
    ontology_id: str | None = None
    description: str | None = None
    rationale: str | None = None


class ResolveRequest(BaseModel):
    curator_id: str = Field(..., description="Who is deciding; recorded in the audit trail.")
    resolutions: list[Resolution] = Field(default_factory=list)
    dismiss: bool = Field(
        default=False, description="Close without a decision — the collision is acceptable."
    )


@router.get("/lexicon/collisions")
async def list_collisions(
    status: str | None = Query("open", description="open | resolved | dismissed; omit for all."),
    scope: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """The curator work queue."""
    rows = lexicon_repo.list_collisions(
        _shared.get_db(), status=status, scope=scope, limit=limit, offset=offset
    )
    return {"data": rows, "count": len(rows)}


@router.post("/lexicon/collisions/detect")
async def detect_collisions(body: DetectRequest) -> dict[str, Any]:
    """Detect colliding labels across the given AOE ontologies."""
    return label_collisions.detect_in_ontologies(
        _shared.get_db(),
        ontology_ids=body.ontology_ids,
        scope=body.scope,
        include_stopwords=body.include_stopwords,
    )


@router.post("/lexicon/collisions/ingest")
async def ingest_collisions(body: IngestRequest) -> dict[str, Any]:
    """Accept a collision report from an external producer."""
    return label_collisions.ingest_report(
        _shared.get_db(),
        scope=body.scope,
        items=[item.model_dump() for item in body.items],
        source=body.source,
    )


@router.get("/lexicon/decisions")
async def list_decisions(ontology_id: str | None = Query(None)) -> dict[str, Any]:
    """Live curated labels, as ``{concept_uri: decision}``."""
    decisions = lexicon_repo.live_decisions_by_uri(_shared.get_db(), ontology_id=ontology_id)
    return {"data": decisions, "count": len(decisions)}


@router.get("/lexicon/decisions/history")
async def decision_history(concept_uri: str = Query(...)) -> dict[str, Any]:
    """Every decision recorded for one concept, newest first."""
    rows = lexicon_repo.decision_history(_shared.get_db(), concept_uri=concept_uri)
    return {"concept_uri": concept_uri, "data": rows, "count": len(rows)}


@router.get("/lexicon/collisions/{collision_key}")
async def get_collision(collision_key: str) -> dict[str, Any]:
    doc = lexicon_repo.get_collision(_shared.get_db(), key=collision_key)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"collision '{collision_key}' not found")
    return doc


@router.post("/lexicon/collisions/{collision_key}/resolve")
async def resolve_collision(collision_key: str, body: ResolveRequest) -> dict[str, Any]:
    """Record the curator's decision and close the queue item."""
    try:
        return label_collisions.resolve_collision(
            _shared.get_db(),
            collision_key=collision_key,
            resolutions=[r.model_dump() for r in body.resolutions],
            curator_id=body.curator_id,
            dismiss=body.dismiss,
        )
    except ValueError as exc:
        message = str(exc)
        if "not found" in message:
            raise HTTPException(status_code=404, detail=message) from exc
        raise HTTPException(status_code=422, detail=message) from exc
