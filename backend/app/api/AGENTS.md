# api/ — REST API Route Handlers

FastAPI routers defining all HTTP endpoints.

## What This Is
Thin route handlers that validate input (via Pydantic), delegate to services, and format responses. One file per endpoint group: `documents.py`, `extraction.py`, `ontology.py`, `curation.py`, `health.py`.

## What This Is NOT
- Not where business logic lives — routes call `services/`, never implement logic directly
- Not where database queries live — routes never import from `db/`
- Not the MCP server interface (that's a separate process)

## Boundaries
- Every route function receives validated Pydantic models and returns Pydantic models or dicts
- Database access is always via a service layer (once implemented), never direct `db/` imports
- Exception: `health.py` may call `db.client.get_db()` directly for readiness checks
- All list endpoints must support cursor-based pagination (see PRD Section 7.8)
- All errors must use the standard error response format (see PRD Section 7.8)

## Key Invariants
- Route files never contain more than ~100 lines — if growing, split or move logic to services
- All tenant-scoped routes must accept and enforce `org_id`
- Routes must not catch and swallow exceptions — let FastAPI's exception handlers manage errors
- WebSocket endpoints for real-time updates go here too (extraction progress, curation events)

## PRD Reference
- Endpoint spec: PRD Sections 7.1–7.7
- Pagination / errors / rate limiting: PRD Section 7.8
- WebSocket events: PRD Section 7.8 (WebSocket Events table)
