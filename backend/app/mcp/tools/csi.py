"""MCP tools for importing CSI v1 documents.

Two tools that let an AI agent bring the portfolio's interchange artifact into AOE:

  - preview_csi_document:  validate + summarise (read-only)
  - import_csi_document:   CSI -> OWL -> import as a new ontology

Both delegate to :mod:`app.services.csi_import`. Errors are returned as
``{"error": ...}`` payloads so an agent never sees an unhandled exception, matching
the other tool modules' contract.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from mcp.server.fastmcp import FastMCP

log = logging.getLogger(__name__)


def _parse(document_json: str) -> dict[str, Any]:
    parsed = json.loads(document_json)
    if not isinstance(parsed, dict):
        raise ValueError("document_json must encode a JSON object")
    return parsed


def register_csi_tools(mcp: FastMCP) -> None:
    """Register CSI import tools on the given MCP server."""

    @mcp.tool()
    def preview_csi_document(document_json: str) -> dict[str, Any]:
        """Validate a CSI v1 document and summarise what importing it would create.

        Read-only: nothing is written to AOE. Use before ``import_csi_document``.

        Args:
            document_json: The CSI v1 document as a JSON string (what
                ``r2g export-csi`` or ``arangodb-schema-analyzer`` wrote).
        """
        try:
            from app.services.csi_import import preview_csi_document as _preview

            return _preview(_parse(document_json))
        except Exception as exc:
            log.exception("preview_csi_document failed")
            return {"error": str(exc)}

    @mcp.tool()
    def import_csi_document(
        document_json: str,
        db_label: str | None = None,
        ontology_id: str | None = None,
        ontology_label: str | None = None,
        imports: list[str] | None = None,
    ) -> dict[str, Any]:
        """Import a CSI v1 document as a new AOE ontology.

        Every entity becomes a class, every entity property a datatype property (with
        the physical field it maps to recorded as provenance), every relationship an
        object property; the document's producer and bitemporal stamps are kept.

        Args:
            document_json: The CSI v1 document as a JSON string.
            db_label: Logical source name for the namespace; defaults to the
                document's ``provenance.source.ref``.
            ontology_id: Optional explicit ontology id.
            ontology_label: Optional display label.
            imports: AOE ontology ids to declare as ``owl:imports``.
        """
        try:
            from app.services.csi_import import CsiImportConfig
            from app.services.csi_import import import_csi_document as _import

            config = CsiImportConfig(
                document=_parse(document_json),
                db_label=db_label,
                ontology_id=ontology_id,
                ontology_label=ontology_label,
                imports=imports or [],
            )
            return _import(config)
        except Exception as exc:
            log.exception("import_csi_document failed")
            return {"error": str(exc)}
