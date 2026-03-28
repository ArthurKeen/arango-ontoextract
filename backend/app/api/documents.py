"""Document REST endpoints — PRD Section 7.1.

Thin route handlers that validate input, delegate to services/repo, and return
Pydantic-shaped responses.  Routes never import from ``db/`` directly; all data
access goes through the repository and service layers.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Query, UploadFile

from app.api.errors import ConflictError, NotFoundError
from app.db import documents_repo
from app.models.common import PaginatedResponse
from app.services.ingestion import compute_file_hash
from app.tasks import process_document

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/documents", tags=["documents"])

_background_tasks: set[asyncio.Task] = set()  # prevent GC of fire-and-forget tasks

_ALLOWED_MIME_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text/markdown",
}


def _to_doc_response(doc: dict) -> dict:
    """Ensure the dict has the fields DocumentResponse expects."""
    return {
        "_key": doc["_key"],
        "filename": doc.get("filename", ""),
        "mime_type": doc.get("mime_type", ""),
        "org_id": doc.get("org_id"),
        "status": doc.get("status", "uploading"),
        "upload_date": doc.get("upload_date", ""),
        "chunk_count": doc.get("chunk_count", 0),
        "metadata": doc.get("metadata"),
        "file_hash": doc.get("file_hash"),
        "error_message": doc.get("error_message"),
    }


@router.post("/upload")
async def upload_document(
    file: UploadFile,
    org_id: str | None = Query(default=None),
) -> dict:
    """Upload a document and start async processing pipeline."""
    content = await file.read()

    mime = file.content_type or ""
    if mime not in _ALLOWED_MIME_TYPES:
        if file.filename and file.filename.endswith(".md"):
            mime = "text/markdown"
        elif mime not in _ALLOWED_MIME_TYPES:
            from app.api.errors import ValidationError

            raise ValidationError(
                f"Unsupported file type: {mime}",
                details={"allowed": sorted(_ALLOWED_MIME_TYPES)},
            )

    file_hash = compute_file_hash(content)
    existing = documents_repo.find_document_by_hash(file_hash)
    if existing:
        raise ConflictError(
            "Duplicate document — a file with identical content already exists",
            details={"existing_doc_id": existing["_key"], "file_hash": file_hash},
        )

    doc = documents_repo.create_document(
        filename=file.filename or "untitled",
        mime_type=mime,
        file_hash=file_hash,
        org_id=org_id,
    )

    task = asyncio.create_task(process_document(doc["_key"], content, mime))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    return {
        "doc_id": doc["_key"],
        "filename": doc["filename"],
        "status": doc["status"],
    }


@router.get("")
async def list_documents(
    limit: int = Query(default=25, ge=1, le=100),
    cursor: str | None = Query(default=None),
    sort: str = Query(default="upload_date"),
    order: str = Query(default="desc"),
    org_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
) -> PaginatedResponse[dict]:
    """List all documents (paginated)."""
    return documents_repo.list_documents(
        limit=limit,
        cursor=cursor,
        sort_field=sort,
        sort_order=order,
        org_id=org_id,
        status=status,
    )


@router.get("/{doc_id}")
async def get_document(doc_id: str) -> dict:
    """Get document metadata and processing status."""
    doc = documents_repo.get_document(doc_id)
    if doc is None:
        raise NotFoundError(
            f"Document '{doc_id}' not found",
            details={"doc_id": doc_id},
        )
    return _to_doc_response(doc)


@router.get("/{doc_id}/chunks")
async def get_chunks(
    doc_id: str,
    limit: int = Query(default=25, ge=1, le=100),
    cursor: str | None = Query(default=None),
) -> PaginatedResponse[dict]:
    """List chunks for a document (paginated)."""
    doc = documents_repo.get_document(doc_id)
    if doc is None:
        raise NotFoundError(
            f"Document '{doc_id}' not found",
            details={"doc_id": doc_id},
        )
    return documents_repo.get_chunks_for_document(doc_id, limit=limit, cursor=cursor)


@router.delete("/{doc_id}")
async def delete_document(doc_id: str) -> dict:
    """Soft-delete a document (set status='deleted')."""
    doc = documents_repo.get_document(doc_id)
    if doc is None:
        raise NotFoundError(
            f"Document '{doc_id}' not found",
            details={"doc_id": doc_id},
        )
    documents_repo.delete_document(doc_id)
    return {"doc_id": doc_id, "status": "deleted"}
