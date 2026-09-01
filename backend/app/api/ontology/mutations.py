import json
import logging
import re
import time
from typing import Any, Literal

from arango.database import StandardDatabase
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse, Response
from pydantic import BaseModel, Field

from app.api.errors import ConflictError, NotFoundError, ValidationError
from app.api.ontology import _shared
from app.db.temporal_constants import NEVER_EXPIRES
from app.db.utils import doc_get
from app.models.ontology import (
    BulkReparentRequest,
    BulkReparentUndoRequest,
    CreateClassRequest,
    CreateEdgeRequest,
    CreatePropertyRequest,
    ReparentClassRequest,
    UpdateClassRequest,
    UpdateEdgeRequest,
    UpdatePropertyRequest,
)
from app.services import curation as curation_svc
from app.services import export as export_svc
from app.services import temporal as temporal_svc

log = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# CRUD endpoints for ontology classes, properties, and edges (K.3-K.6b)
# ---------------------------------------------------------------------------


def _slugify(text: str) -> str:
    """Convert text to an ArangoDB-safe key slug."""
    return re.sub(r"[^a-zA-Z0-9]+", "_", text.lower()).strip("_")


def _key_from_uri(uri: str) -> str:
    """Extract a document key from the URI fragment (after ``#`` or last ``/``)."""
    fragment = uri.rsplit("#", 1)[-1] if "#" in uri else uri.rsplit("/", 1)[-1]
    return _slugify(fragment)


def _ensure_collection(db: StandardDatabase, name: str, *, edge: bool = False) -> None:
    if not db.has_collection(name):
        db.create_collection(name, edge=edge)


@router.post("/{ontology_id}/classes", status_code=201)
async def create_class(ontology_id: str, body: CreateClassRequest) -> dict[str, Any]:
    """Create a new ontology class (K.3)."""
    db = _shared.get_db()
    _ensure_collection(db, "ontology_classes")

    slug = _slugify(body.label)
    uri = body.uri or f"http://example.org/ontology/{ontology_id}#{slug}"
    key = _key_from_uri(uri)

    existing = list(
        _shared.run_aql(
            db,
            "FOR c IN ontology_classes "
            "FILTER c.ontology_id == @oid AND c.uri == @uri AND c.expired == @never "
            "LIMIT 1 RETURN c._key",
            bind_vars={"oid": ontology_id, "uri": uri, "never": NEVER_EXPIRES},
        )
    )
    if existing:
        raise ConflictError(f"Class with URI '{uri}' already exists")

    data: dict[str, Any] = {
        "_key": key,
        "uri": uri,
        "label": body.label,
        "description": body.description or "",
        "rdf_type": body.rdf_type,
        "source_type": "manual",
        "confidence": 1.0,
        "status": "approved",
    }

    try:
        cls_doc = _shared.ontology_repo.create_class(
            db, ontology_id=ontology_id, data=data, created_by="manual"
        )
    except Exception as exc:
        if "unique constraint" in str(exc).lower() or "1210" in str(exc):
            data["_key"] = f"{key}_{int(time.time()) % 100000}"
            cls_doc = _shared.ontology_repo.create_class(
                db, ontology_id=ontology_id, data=data, created_by="manual"
            )
        else:
            log.exception("Failed to create class")
            raise

    if body.parent_class_key:
        parent = _shared.ontology_repo.get_class(db, key=body.parent_class_key)
        if parent is None:
            raise NotFoundError(f"Parent class '{body.parent_class_key}' not found")
        if parent.get("ontology_id") != ontology_id:
            raise ValidationError("Parent class belongs to a different ontology")
        _ensure_collection(db, "subclass_of", edge=True)
        _shared.ontology_repo.create_edge(
            db,
            edge_collection="subclass_of",
            from_id=cls_doc["_id"],
            to_id=parent["_id"],
            data={
                "ontology_id": ontology_id,
                "label": f"{body.label} subClassOf {parent.get('label', '')}",
            },
        )

    return cls_doc


@router.post("/{ontology_id}/properties", status_code=201)
async def create_property(ontology_id: str, body: CreatePropertyRequest) -> dict[str, Any]:
    """Create a new ontology property with PGT-aligned edges (K.4 / ADR-006)."""
    db = _shared.get_db()
    _ensure_collection(db, "ontology_classes")

    is_object = body.property_type == "object"
    target_col = "ontology_object_properties" if is_object else "ontology_datatype_properties"
    _ensure_collection(db, target_col)
    _ensure_collection(db, "rdfs_domain", edge=True)
    if is_object:
        _ensure_collection(db, "rdfs_range_class", edge=True)

    domain_cls = _shared.ontology_repo.get_class(db, key=body.domain_class_key)
    if domain_cls is None:
        raise NotFoundError(f"Domain class '{body.domain_class_key}' not found")
    if domain_cls.get("ontology_id") != ontology_id:
        raise ValidationError("Domain class belongs to a different ontology")

    slug = _slugify(body.label)
    prop_key = f"{body.domain_class_key}_{slug}"
    uri = body.uri or f"http://example.org/ontology/{ontology_id}#{prop_key}"

    data: dict[str, Any] = {
        "_key": prop_key,
        "uri": uri,
        "label": body.label,
        "description": body.description or "",
        "range": body.range,
        "property_type": body.property_type,
        "rdf_type": "owl:ObjectProperty" if is_object else "owl:DatatypeProperty",
        "source_type": "manual",
        "confidence": 1.0,
        "status": "approved",
    }
    if not is_object:
        data["range_datatype"] = body.range

    try:
        prop_doc = _shared.ontology_repo.create_property(
            db,
            ontology_id=ontology_id,
            data=data,
            created_by="manual",
            collection=target_col,
        )
    except Exception as exc:
        if "unique constraint" in str(exc).lower() or "1210" in str(exc):
            data["_key"] = f"{prop_key}_{int(time.time()) % 100000}"
            prop_doc = _shared.ontology_repo.create_property(
                db,
                ontology_id=ontology_id,
                data=data,
                created_by="manual",
                collection=target_col,
            )
        else:
            log.exception("Failed to create property")
            raise

    _shared.ontology_repo.create_edge(
        db,
        edge_collection="rdfs_domain",
        from_id=prop_doc["_id"],
        to_id=domain_cls["_id"],
        data={"ontology_id": ontology_id},
    )

    if is_object and body.range:
        range_cls = _shared.ontology_repo.get_class(db, key=body.range)
        if range_cls:
            _shared.ontology_repo.create_edge(
                db,
                edge_collection="rdfs_range_class",
                from_id=prop_doc["_id"],
                to_id=range_cls["_id"],
                data={"ontology_id": ontology_id},
            )

    return prop_doc


@router.post("/{ontology_id}/edges", status_code=201)
async def create_or_update_edge(ontology_id: str, body: CreateEdgeRequest) -> dict[str, Any]:
    """Create an edge between two classes, or update if one already exists (K.5)."""
    db = _shared.get_db()
    _ensure_collection(db, "ontology_classes")

    from_cls = _shared.ontology_repo.get_class(db, key=body.from_key)
    if from_cls is None:
        raise NotFoundError(f"Source class '{body.from_key}' not found")
    if from_cls.get("ontology_id") != ontology_id:
        raise ValidationError("Source class belongs to a different ontology")

    to_cls = _shared.ontology_repo.get_class(db, key=body.to_key)
    if to_cls is None:
        raise NotFoundError(f"Target class '{body.to_key}' not found")
    if to_cls.get("ontology_id") != ontology_id:
        raise ValidationError("Target class belongs to a different ontology")

    _ensure_collection(db, body.edge_type, edge=True)

    existing_edges = list(
        _shared.run_aql(
            db,
            "FOR e IN @@col "
            "FILTER e._from == @from_id AND e._to == @to_id "
            "AND e.expired == @never RETURN e",
            bind_vars={
                "@col": body.edge_type,
                "from_id": from_cls["_id"],
                "to_id": to_cls["_id"],
                "never": NEVER_EXPIRES,
            },
        )
    )
    for old_edge in existing_edges:
        temporal_svc.expire_entity(db, collection=body.edge_type, key=old_edge["_key"])

    edge_data: dict[str, Any] = {"ontology_id": ontology_id}
    if body.label:
        edge_data["label"] = body.label

    edge_doc = _shared.ontology_repo.create_edge(
        db,
        edge_collection=body.edge_type,
        from_id=from_cls["_id"],
        to_id=to_cls["_id"],
        data=edge_data,
    )

    return edge_doc


@router.put("/{ontology_id}/edges/{edge_key}")
async def update_edge_endpoint(
    ontology_id: str,
    edge_key: str,
    body: UpdateEdgeRequest,
) -> dict[str, Any]:
    """Update curation status (or other fields) on a versioned ontology edge."""
    db = _shared.get_db()
    resolved = _shared.ontology_repo.resolve_ontology_edge(db, edge_key=edge_key)
    if resolved is None:
        raise NotFoundError(f"Edge '{edge_key}' not found")
    _col, doc = resolved
    if doc.get("ontology_id") != ontology_id:
        raise ValidationError("Edge belongs to a different ontology")

    try:
        return _shared.ontology_repo.update_edge(
            db,
            edge_key=edge_key,
            data={"status": body.status},
            created_by="workspace",
            change_summary=f"Edge {edge_key} status → {body.status}",
        )
    except ValueError as exc:
        raise NotFoundError(str(exc)) from exc


@router.put("/{ontology_id}/classes/{class_key}")
async def update_class_endpoint(
    ontology_id: str,
    class_key: str,
    body: UpdateClassRequest,
) -> dict[str, Any]:
    """Update an ontology class — expire old version, create new (K.6)."""
    db = _shared.get_db()

    cls = _shared.ontology_repo.get_class(db, key=class_key)
    if cls is None:
        raise NotFoundError(f"Class '{class_key}' not found")
    if cls.get("ontology_id") != ontology_id:
        raise ValidationError("Class belongs to a different ontology")

    update_data = {
        k: v
        for k, v in {
            "label": body.label,
            "description": body.description,
            "uri": body.uri,
            "status": body.status,
        }.items()
        if v is not None
    }
    if not update_data:
        raise ValidationError("No fields to update")

    try:
        updated = _shared.ontology_repo.update_class(
            db,
            key=class_key,
            data=update_data,
            created_by="manual",
            change_summary=f"Updated class {class_key}: {', '.join(update_data.keys())}",
        )
    except ValueError as exc:
        raise NotFoundError(str(exc)) from exc

    return updated


def _reparent_one(
    db: Any,
    *,
    ontology_id: str,
    class_key: str,
    new_parent_key: str | None,
) -> dict[str, Any]:
    """Move one class to a new parent. Shared by the single and bulk endpoints.

    Extracted rather than duplicated so the bulk path cannot drift from the
    cycle guard and the expire-old-parents semantics that make the single path
    safe (FR-4.12, FR-7.8.20).
    """
    body = ReparentClassRequest(new_parent_key=new_parent_key)
    return _reparent_impl(db, ontology_id=ontology_id, class_key=class_key, body=body)


@router.post("/{ontology_id}/classes/{class_key}/reparent")
async def reparent_class_endpoint(
    ontology_id: str,
    class_key: str,
    body: ReparentClassRequest,
) -> dict[str, Any]:
    """Atomically move a class to a new parent (CQ.5 / FR-4.12).

    Expires the class's current live ``subclass_of`` edge(s) and, when a new
    parent is given, creates a fresh ``subclass_of`` edge. Posting a bare
    ``subclass_of`` edge (the previous mechanism) only expired an edge with the
    *same* ``_from`` AND ``_to``, so moving a child from parent A to B left the
    old ``child→A`` edge live — silent multiple inheritance. This endpoint
    removes the old parent link and rejects cycles.
    """
    return _reparent_impl(_shared.get_db(), ontology_id=ontology_id, class_key=class_key, body=body)


def _reparent_impl(
    db: Any,
    *,
    ontology_id: str,
    class_key: str,
    body: ReparentClassRequest,
) -> dict[str, Any]:
    child = _shared.ontology_repo.get_class(db, key=class_key)
    if child is None:
        raise NotFoundError(f"Class '{class_key}' not found")
    if child.get("ontology_id") != ontology_id:
        raise ValidationError("Class belongs to a different ontology")

    new_parent_id: str | None = None
    if body.new_parent_key is not None:
        if body.new_parent_key == class_key:
            raise ValidationError("A class cannot be its own superclass")
        parent = _shared.ontology_repo.get_class(db, key=body.new_parent_key)
        if parent is None:
            raise NotFoundError(f"Parent class '{body.new_parent_key}' not found")
        if parent.get("ontology_id") != ontology_id:
            raise ValidationError("Parent class belongs to a different ontology")
        new_parent_id = parent["_id"]

        # Cycle guard: the proposed parent must not already be a descendant of
        # the child (i.e. child must not be reachable by walking OUTBOUND
        # subclass_of from the new parent), else child→newParent→…→child.
        if db.has_collection("subclass_of"):
            reaches_child = list(
                _shared.run_aql(
                    db,
                    "FOR v, e IN 1..100 OUTBOUND @start subclass_of "
                    "  FILTER e.expired == @never "
                    "  FILTER v._id == @child_id "
                    "  LIMIT 1 RETURN 1",
                    bind_vars={
                        "start": new_parent_id,
                        "never": NEVER_EXPIRES,
                        "child_id": child["_id"],
                    },
                )
            )
            if reaches_child:
                raise ValidationError(
                    "Reparenting would create a subclass_of cycle "
                    f"('{body.new_parent_key}' is already a descendant of '{class_key}')"
                )

    # Expire every live subclass_of edge out of the child (its current parents).
    expired_parents: list[str] = []
    if db.has_collection("subclass_of"):
        current = list(
            _shared.run_aql(
                db,
                "FOR e IN subclass_of "
                "  FILTER e._from == @child_id AND e.expired == @never RETURN e",
                bind_vars={"child_id": child["_id"], "never": NEVER_EXPIRES},
            )
        )
        for old_edge in current:
            temporal_svc.expire_entity(db, collection="subclass_of", key=old_edge["_key"])
            expired_parents.append(str(old_edge.get("_to")))

    new_edge: dict[str, Any] | None = None
    if new_parent_id is not None:
        _ensure_collection(db, "subclass_of", edge=True)
        new_edge = _shared.ontology_repo.create_edge(
            db,
            edge_collection="subclass_of",
            from_id=child["_id"],
            to_id=new_parent_id,
            data={
                "ontology_id": ontology_id,
                "label": f"{child.get('label') or class_key} subClassOf {body.new_parent_key}",
            },
        )

    log.info(
        "reparented class",
        extra={
            "ontology_id": ontology_id,
            "class_key": class_key,
            "new_parent_key": body.new_parent_key,
            "expired_parents": len(expired_parents),
        },
    )
    return {
        "reparented": True,
        "class_key": class_key,
        "new_parent_key": body.new_parent_key,
        "expired_parent_ids": expired_parents,
        "new_edge": new_edge,
    }


@router.put("/{ontology_id}/properties/{prop_key}")
async def update_property_endpoint(
    ontology_id: str, prop_key: str, body: UpdatePropertyRequest
) -> dict[str, Any]:
    """Update an ontology property — expire old version, create new (K.6)."""
    db = _shared.get_db()

    prop = _shared.ontology_repo.get_property(db, key=prop_key)
    if prop is None:
        raise NotFoundError(f"Property '{prop_key}' not found")
    if prop.get("ontology_id") != ontology_id:
        raise ValidationError("Property belongs to a different ontology")

    update_data = {
        k: v
        for k, v in {
            "label": body.label,
            "description": body.description,
            "uri": body.uri,
            "range": body.range,
        }.items()
        if v is not None
    }
    if not update_data:
        raise ValidationError("No fields to update")

    try:
        updated = _shared.ontology_repo.update_property(
            db,
            key=prop_key,
            data=update_data,
            created_by="manual",
            change_summary=f"Updated property {prop_key}: {', '.join(update_data.keys())}",
        )
    except ValueError as exc:
        raise NotFoundError(str(exc)) from exc

    return updated


@router.delete("/{ontology_id}/classes/{class_key}")
async def delete_class_endpoint(ontology_id: str, class_key: str) -> dict[str, Any]:
    """Soft-delete a class and all connected edges (K.6b)."""
    db = _shared.get_db()

    cls = _shared.ontology_repo.get_class(db, key=class_key)
    if cls is None:
        raise NotFoundError(f"Class '{class_key}' not found")
    if cls.get("ontology_id") != ontology_id:
        raise ValidationError("Class belongs to a different ontology")

    try:
        expired_cls = _shared.ontology_repo.expire_class_cascade(db, key=class_key)
    except ValueError as exc:
        raise NotFoundError(str(exc)) from exc

    return {"deleted": True, "class_key": class_key, "expired_class": expired_cls}


# ---------------------------------------------------------------------------
# Export / Import
# ---------------------------------------------------------------------------


@router.get("/{ontology_id}/export")
async def export_ontology_endpoint(
    ontology_id: str,
    format: str = Query(
        "turtle",
        description=(
            "Export format. ``turtle`` (default) emits OWL 2 Turtle with "
            "``owl:Restriction`` blank nodes for OWL constraints; ``shacl`` "
            "emits a separate SHACL shapes graph; ``jsonld`` / ``csv`` are "
            "the established alternative serialisations of the OWL ontology."
        ),
    ),
) -> Response:
    """Export an ontology in OWL Turtle, JSON-LD, CSV, or SHACL Turtle format."""
    entry = _shared.registry_repo.get_registry_entry(ontology_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Ontology '{ontology_id}' not found")

    try:
        if format == "jsonld":
            data = export_svc.export_jsonld(ontology_id)
            return Response(
                content=json.dumps(data, indent=2),
                media_type="application/ld+json",
                headers={"Content-Disposition": f'attachment; filename="{ontology_id}.jsonld"'},
            )
        elif format == "csv":
            csv_content = export_svc.export_csv(ontology_id)
            return PlainTextResponse(
                content=csv_content,
                media_type="text/csv",
                headers={"Content-Disposition": f'attachment; filename="{ontology_id}.csv"'},
            )
        elif format == "shacl":
            # Stream 3 PR 5 -- separate SHACL shapes graph. Convention
            # is a sibling ``.shapes.ttl`` next to the main ontology
            # Turtle, which is what TopBraid / Protege / SHACL parsers
            # expect to find when looking for shape constraints.
            shacl_content = export_svc.export_shacl(ontology_id)
            return PlainTextResponse(
                content=shacl_content,
                media_type="text/turtle",
                headers={
                    "Content-Disposition": (f'attachment; filename="{ontology_id}.shapes.ttl"')
                },
            )
        else:
            ttl_content = export_svc.export_ontology(ontology_id, fmt="turtle")
            return PlainTextResponse(
                content=ttl_content,
                media_type="text/turtle",
                headers={"Content-Disposition": f'attachment; filename="{ontology_id}.ttl"'},
            )
    except Exception as exc:
        log.exception("Export failed for ontology %s", ontology_id)
        raise HTTPException(status_code=500, detail="Internal server error") from exc


@router.post("/{ontology_id}/classes/bulk-reparent")
async def bulk_reparent_classes(ontology_id: str, body: BulkReparentRequest) -> dict[str, Any]:
    """Give a whole selection the same parent, optionally creating it (FR-7.8.20).

    Two shapes in one endpoint because they are the same operation:

    * ``new_parent_key``   — set parent to an existing class.
    * ``new_parent_label`` — introduce a superclass: create it, then parent
      everything to it.

    Per-class outcomes are REPORTED rather than aborting the batch. A cycle or a
    missing class should not silently strand the other nineteen half-moved; the
    caller gets a list it can show and retry. Each move reuses the single-class
    path, so the cycle guard and the expire-old-parents semantics are identical.
    """
    if not body.new_parent_key and not body.new_parent_label:
        raise ValidationError("Provide either new_parent_key or new_parent_label")
    if body.new_parent_key and body.new_parent_label:
        raise ValidationError("Provide new_parent_key OR new_parent_label, not both")

    db = _shared.get_db()
    parent_key = body.new_parent_key
    created_parent: dict[str, Any] | None = None

    if body.new_parent_label:
        created_parent = await create_class(
            ontology_id,
            CreateClassRequest(
                label=body.new_parent_label,
                description=body.new_parent_description,
                uri=None,
                parent_class_key=None,
            ),
        )
        parent_key = str(created_parent.get("_key"))

    # A class cannot become its own superclass; drop it rather than 400 the batch.
    targets = [k for k in body.class_keys if k != parent_key]

    moved: list[str] = []
    failed: list[dict[str, str]] = []
    # FR-7.8.21 — the reparent already computes each class's previous parents.
    # Keeping them is what makes the operation undoable; discarding them (as
    # this endpoint originally did) left a twenty-class reshape reversible only
    # by hand, from parents the UI never showed.
    undo: list[dict[str, str | None]] = []
    for key in targets:
        try:
            res = _reparent_one(
                db, ontology_id=ontology_id, class_key=key, new_parent_key=parent_key
            )
            moved.append(key)
            prev = [str(p).split("/")[-1] for p in (res.get("expired_parent_ids") or [])]
            undo.append({"class_key": key, "previous_parent_key": prev[0] if prev else None})
        except (ValidationError, NotFoundError) as exc:
            failed.append({"class_key": key, "reason": str(exc)})

    log.info(
        "bulk reparent",
        extra={
            "ontology_id": ontology_id,
            "parent_key": parent_key,
            "moved": len(moved),
            "failed": len(failed),
        },
    )
    return {
        "parent_key": parent_key,
        "created_parent": created_parent,
        "moved": moved,
        "failed": failed,
        "moved_count": len(moved),
        "failed_count": len(failed),
        "undo": undo,
    }


@router.post("/{ontology_id}/classes/bulk-reparent/undo")
async def undo_bulk_reparent(ontology_id: str, body: BulkReparentUndoRequest) -> dict[str, Any]:
    """Reverse a bulk reparent by restoring each class's previous parent (FR-7.8.21).

    Takes the ``undo`` payload the forward call returned. Restoring goes through
    the same cycle-checked reparent path, and a ``previous_parent_key`` of
    ``None`` means the class had no parent before — so its current one is
    expired and nothing replaces it.

    Per-class outcomes are reported, exactly as the forward operation does: an
    undo that half-fails must say which half, or the user is left worse off than
    before they tried to reverse it.
    """
    db = _shared.get_db()
    restored: list[str] = []
    failed: list[dict[str, str]] = []
    for entry in body.entries:
        try:
            _reparent_one(
                db,
                ontology_id=ontology_id,
                class_key=entry.class_key,
                new_parent_key=entry.previous_parent_key,
            )
            restored.append(entry.class_key)
        except (ValidationError, NotFoundError) as exc:
            failed.append({"class_key": entry.class_key, "reason": str(exc)})

    log.info(
        "undo bulk reparent",
        extra={"ontology_id": ontology_id, "restored": len(restored), "failed": len(failed)},
    )
    # A superclass left empty by the undo is REPORTED, not deleted: removing a
    # class the user deliberately named is not the system's call (FR-7.8.21).
    return {
        "restored": restored,
        "failed": failed,
        "restored_count": len(restored),
        "failed_count": len(failed),
    }


# ---------------------------------------------------------------------------
# Orphan object properties — curator actions on what the matcher could not fix
# ---------------------------------------------------------------------------


class ResolveOrphanRequest(BaseModel):
    """What to do with an object property that has a domain but no range."""

    action: Literal["reject", "set_range"] = Field(
        ...,
        description=(
            "``reject`` expires the property — the extractor should not have "
            "produced it. ``set_range`` names the class it points at, which "
            "the matcher could not infer."
        ),
    )
    curator_id: str = Field(
        ..., description="Who decided. The audit trail is only as good as this value."
    )
    range_class_key: str | None = Field(
        default=None,
        description="Required for ``set_range``: the class the property points at.",
    )
    notes: str | None = Field(default=None, description="Optional rationale.")


@router.post("/{ontology_id}/orphan-properties/{property_key}/resolve")
async def resolve_orphan_property(
    ontology_id: str,
    property_key: str,
    body: ResolveOrphanRequest,
) -> dict[str, Any]:
    """Reject an orphan object property, or wire it to a range class.

    The repair overlay could only ever APPLY an inferred range. When the
    matcher inferred nothing — 12 of WTW Ontology's 12 orphans — the curator
    had no action at all, so the same properties reappeared on every scan with
    no way to record that they had been looked at.

    The two things a curator actually concludes about such a property are:

    ``reject``
        It should not exist. ``HRPartner aligns_with_company_vision`` is an
        assertion the extractor typed as a relation. Routed through the normal
        curation path, so it expires temporally and lands in
        ``curation_decisions`` with attribution, exactly like rejecting a class.

    ``set_range``
        It is real and the target class exists (or now does), the matcher just
        could not find it from the description. Inserts the missing
        ``rdfs_range_class`` edge, which is what makes the property visible on
        the canvas at all.
    """
    db = _shared.get_db()

    prop = None
    prop_collection = None
    for collection in ("ontology_object_properties", "ontology_datatype_properties"):
        if not db.has_collection(collection):
            continue
        found = doc_get(db.collection(collection), property_key)
        if found is not None:
            prop, prop_collection = found, collection
            break
    if prop is None or prop_collection is None:
        raise NotFoundError(f"Property '{property_key}' not found")
    if prop.get("ontology_id") != ontology_id:
        raise ValidationError("Property belongs to a different ontology")
    if prop.get("expired") != NEVER_EXPIRES:
        raise ValidationError("Property is already expired; there is nothing to resolve")

    if body.action == "reject":
        decision = curation_svc.record_decision(
            db,
            run_id=str(prop.get("extraction_run_id") or ""),
            entity_key=property_key,
            entity_type="property",
            action="reject",
            curator_id=body.curator_id,
            notes=body.notes,
            issue_reasons=["wrong_relationship"],
        )
        return {"status": "rejected", "property_key": property_key, "decision": decision}

    if not body.range_class_key:
        raise ValidationError("range_class_key is required when action is 'set_range'")
    target = doc_get(db.collection("ontology_classes"), body.range_class_key)
    if target is None:
        raise NotFoundError(f"Class '{body.range_class_key}' not found")
    if target.get("ontology_id") != ontology_id:
        raise ValidationError("Range class belongs to a different ontology")

    _ensure_collection(db, "rdfs_range_class", edge=True)
    now = time.time()
    edge = {
        "_from": prop["_id"],
        "_to": target["_id"],
        "ontology_id": ontology_id,
        # Distinguishable from a matcher repair and from an extracted edge: a
        # human named this range, and the audit should say which.
        "repair_meta": {
            "source": "curator",
            "curator_id": body.curator_id,
            "notes": body.notes,
            "resolved_at": now,
        },
        "created": now,
        "expired": NEVER_EXPIRES,
    }
    db.collection("rdfs_range_class").insert(edge)
    return {
        "status": "range_set",
        "property_key": property_key,
        "range_class_key": body.range_class_key,
    }
