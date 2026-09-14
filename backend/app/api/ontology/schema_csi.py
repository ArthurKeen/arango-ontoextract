"""Ontology creation from a CSI v1 document (the portfolio's interchange artifact).

Two routes, mirroring ``schema_relational``:

  * ``POST /schema/csi/preview`` -- validate + summarise, read-only.
  * ``POST /schema/csi/import``  -- CSI -> OWL -> standard ``import_from_file`` pipeline
                                    -> per-class provenance stamping.

The document is posted inline; it is what ``r2g export-csi`` or
``arangodb-schema-analyzer`` wrote, unchanged.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.csi_import import (
    CsiImportConfig,
    import_csi_document,
    preview_csi_document,
)

log = logging.getLogger(__name__)

router = APIRouter()


class CsiPreviewRequest(BaseModel):
    """Body for the preview route: just the document."""

    document: dict[str, Any] = Field(..., description="A CSI v1 document.")


@router.post("/schema/csi/preview")
def preview_csi(body: CsiPreviewRequest) -> dict[str, Any]:
    """Validate a CSI document and summarise what importing it would create.

    Read-only. Returns ``valid: false`` with the structural problems rather than
    erroring, so a curator can see every issue at once.
    """
    return preview_csi_document(body.document)


@router.post("/schema/csi/import")
def import_csi(config: CsiImportConfig) -> dict[str, Any]:
    """Import a CSI document as a new AOE ontology.

    Errors mapped:
      - unreadable document (``ValueError``) -> 400
      - anything else during build/import -> 500
    """
    try:
        return import_csi_document(config)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        log.exception("CSI import failed")
        raise HTTPException(status_code=500, detail=f"CSI import error: {exc}") from exc
