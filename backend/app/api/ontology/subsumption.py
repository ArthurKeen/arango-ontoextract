"""Subsumption review API — the flagged ``subClassOf`` queue (PRD §6.2 FR-2.20).

The judge stamps a verdict on every candidate subclass edge and deliberately
never deletes one, on the grounds that a curator can act on a flagged edge but
cannot act on one that vanished. That promise is only worth anything if the
flags are reachable, which is what this module is for:

* ``GET  /{ontology_id}/subsumption/flagged``        — the review queue
* ``POST /{ontology_id}/subsumption/{key}/resolve``  — keep or detach the edge

Two resolutions, mirroring the only two things a curator can conclude:

``keep``
    The judge was wrong. The edge stays live and is stamped with the curator's
    override so a later scan does not re-raise a question already answered.

``detach``
    The judge was right — this is part-of, or attribute-of, or a document
    about the parent. The edge is expired through the normal temporal path, so
    the removal is versioned and reversible rather than a destructive delete.

Neither resolution creates the *correct* relation in the parent's place. Naming
the relation the two kinds license needs the upper ontology (FR-21.7); until
then the honest outcome of "this is not subsumption" is an unparented class,
which is visible and fixable, rather than a wrong parent that reads as true.
"""

from __future__ import annotations

import time
from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.api.errors import NotFoundError, ValidationError
from app.api.ontology import _shared
from app.db.temporal_constants import NEVER_EXPIRES
from app.db.utils import doc_get
from app.services import temporal as temporal_svc

router = APIRouter()


class ResolveSubsumptionRequest(BaseModel):
    action: Literal["keep", "detach"] = Field(
        ...,
        description=(
            "``keep`` overrides the judge and leaves the edge live; "
            "``detach`` expires it because the relation is not subsumption."
        ),
    )
    curator_id: str = Field(
        ..., description="Who decided. The audit trail is only as good as this value."
    )
    note: str | None = Field(default=None, description="Optional rationale for the decision.")


@router.get("/{ontology_id}/subsumption/flagged")
async def list_flagged_subsumptions(ontology_id: str) -> dict[str, Any]:
    """List live subclass edges the judge rejected and no curator has ruled on.

    Child and parent labels are joined in, because "Airbag → Supplementary
    Restraint System" is judgeable at a glance and a pair of document keys is
    not.
    """
    db = _shared.get_db()
    if not db.has_collection("subclass_of"):
        return {"data": [], "count": 0}

    # ``run_aql`` returns a Cursor, which has no ``len()`` -- materialise it.
    rows = list(
        _shared.run_aql(
            db,
            """
        FOR e IN subclass_of
          FILTER e.ontology_id == @oid
          FILTER e.expired == @never
          FILTER e.subsumption_verdict != null
          FILTER e.subsumption_verdict.is_a == false
          FILTER e.subsumption_verdict.curator_decision == null
          LET child = DOCUMENT(e._from)
          LET parent = DOCUMENT(e._to)
          SORT child.label ASC
          RETURN {
            edge_key: e._key,
            child_key: child._key,
            child_label: child.label,
            parent_key: parent._key,
            parent_label: parent.label,
            relation: e.subsumption_verdict.relation,
            reason: e.subsumption_verdict.reason,
            evidence: e.evidence
          }
        """,
            bind_vars={"oid": ontology_id, "never": NEVER_EXPIRES},
        )
    )
    return {"data": rows, "count": len(rows)}


@router.post("/{ontology_id}/subsumption/{edge_key}/resolve")
async def resolve_flagged_subsumption(
    ontology_id: str,
    edge_key: str,
    body: ResolveSubsumptionRequest,
) -> dict[str, Any]:
    """Record the curator's ruling on one flagged subclass edge."""
    db = _shared.get_db()
    if not db.has_collection("subclass_of"):
        raise NotFoundError("No subclass_of edges exist yet")

    col = db.collection("subclass_of")
    edge = doc_get(col, edge_key)
    if edge is None:
        raise NotFoundError(f"Subclass edge '{edge_key}' not found")
    if edge.get("ontology_id") != ontology_id:
        raise ValidationError("Edge belongs to a different ontology")
    if edge.get("expired") != NEVER_EXPIRES:
        raise ValidationError("Edge is already expired; there is nothing to rule on")

    decision = {
        "action": body.action,
        "curator_id": body.curator_id,
        "note": body.note,
        "decided_at": time.time(),
    }

    if body.action == "detach":
        # Expire through the temporal service so the removal is a new version,
        # not a delete -- the VCR timeline can still show the edge as it was.
        temporal_svc.expire_entity(db, collection="subclass_of", key=edge_key)
        # Stamp the decision on the now-expired version so the audit trail
        # survives on the row a reader will actually find.
        verdict = {**(edge.get("subsumption_verdict") or {}), "curator_decision": decision}
        col.update({"_key": edge_key, "subsumption_verdict": verdict})
        return {"status": "detached", "edge_key": edge_key, "decision": decision}

    verdict = {**(edge.get("subsumption_verdict") or {}), "curator_decision": decision}
    col.update({"_key": edge_key, "subsumption_verdict": verdict})
    return {"status": "kept", "edge_key": edge_key, "decision": decision}
