import logging

from fastapi import APIRouter, HTTPException, Query

from app.db import registry_repo
from app.db.client import get_db

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/ontology", tags=["ontology"])


# ---------------------------------------------------------------------------
# Ontology Library endpoints (PRD 7.3)
# ---------------------------------------------------------------------------


@router.get("/library")
async def list_ontology_library(
    cursor: str | None = Query(None, description="Pagination cursor from previous response"),
    limit: int = Query(25, ge=1, le=100, description="Page size"),
) -> dict:
    """List all ontologies in the registry with cursor-based pagination."""
    try:
        entries, next_cursor = registry_repo.list_registry_entries(
            cursor=cursor, limit=limit
        )
        db = get_db()
        has_col = db.has_collection("ontology_registry")
        total_count = db.collection("ontology_registry").count() if has_col else 0
        return {
            "data": entries,
            "cursor": next_cursor,
            "has_more": next_cursor is not None,
            "total_count": total_count,
        }
    except Exception as exc:
        log.exception("Failed to list ontology library")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/library/{ontology_id}")
async def get_ontology_detail(ontology_id: str) -> dict:
    """Get ontology detail including stats (class count, property count)."""
    entry = registry_repo.get_registry_entry(ontology_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Ontology '{ontology_id}' not found")

    class_count = 0
    property_count = 0
    try:
        db = get_db()
        if db.has_collection("ontology_classes"):
            result = list(
                db.aql.execute(
                    "FOR c IN ontology_classes FILTER c.ontology_id == @oid "
                    "COLLECT WITH COUNT INTO cnt RETURN cnt",
                    bind_vars={"oid": ontology_id},
                )
            )
            class_count = result[0] if result else 0
        if db.has_collection("ontology_properties"):
            result = list(
                db.aql.execute(
                    "FOR p IN ontology_properties FILTER p.ontology_id == @oid "
                    "COLLECT WITH COUNT INTO cnt RETURN cnt",
                    bind_vars={"oid": ontology_id},
                )
            )
            property_count = result[0] if result else 0
    except Exception:
        log.warning("Could not fetch graph stats for ontology %s", ontology_id, exc_info=True)

    return {
        **entry,
        "stats": {
            "class_count": class_count,
            "property_count": property_count,
        },
    }


# ---------------------------------------------------------------------------
# Domain / Local / Staging / Import / Export stubs (other subagents own these)
# ---------------------------------------------------------------------------


@router.get("/domain")
async def get_domain_ontology(offset: int = 0, limit: int = 100) -> dict:
    """Get the full domain ontology graph, paginated."""
    # TODO: implement domain graph query
    return {"classes": [], "edges": [], "offset": offset, "limit": limit}


@router.get("/domain/classes")
async def list_domain_classes(offset: int = 0, limit: int = 100) -> dict:
    """List domain ontology classes."""
    # TODO: implement class listing with filters
    return {"classes": [], "offset": offset, "limit": limit}


@router.get("/local/{org_id}")
async def get_local_ontology(org_id: str, offset: int = 0, limit: int = 100) -> dict:
    """Get an organization's local ontology extension."""
    # TODO: implement local ontology query
    return {"org_id": org_id, "classes": [], "edges": [], "offset": offset, "limit": limit}


@router.get("/staging/{run_id}")
async def get_staging(run_id: str) -> dict:
    """Get the staging graph for curation."""
    # TODO: implement staging graph query
    return {"run_id": run_id, "classes": [], "edges": []}


@router.post("/staging/{run_id}/promote")
async def promote_staging(run_id: str) -> dict:
    """Promote approved staging entities to production."""
    # TODO: implement promotion logic
    return {"run_id": run_id, "promoted": 0}


@router.get("/export")
async def export_ontology(format: str = "ttl") -> dict:
    """Export ontology in OWL/TTL/JSON-LD format."""
    # TODO: implement ArangoRDF export
    return {"format": format, "status": "not_implemented"}


@router.post("/import")
async def import_ontology() -> dict:
    """Import an external ontology file."""
    # TODO: implement ArangoRDF import
    return {"status": "not_implemented"}
