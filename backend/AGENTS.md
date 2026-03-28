# Backend — FastAPI Application

Python backend for the AOE platform. FastAPI + ArangoDB + LangGraph.

## What This Is
The server-side application: REST API, LLM extraction pipeline, database operations, MCP server, and business logic for ontology management.

## What This Is NOT
- Not the frontend (that's `frontend/`)
- Not the ArangoDB visualizer customization scripts (those go in `scripts/setup/`)
- Not a standalone CLI tool — all functionality is exposed via API or MCP

## Boundaries
- All external communication goes through `app/api/` routes or the MCP server
- Database access goes through `app/db/` — never import `python-arango` directly in routes or services
- LLM calls go through `app/extraction/` — never call LLM providers directly in routes
- Configuration comes from `app/config.py` via the `settings` singleton — never read env vars directly

## Key Invariants
- Pydantic models validate all API inputs and LLM outputs
- Every ontology mutation creates a new temporal version (never in-place updates on versioned collections)
- `org_id` filtering is mandatory on all tenant-scoped queries
- Tests live in `tests/` mirroring the `app/` structure (unit/, integration/, e2e/)

## PRD Reference
Full spec: `PRD.md` — this backend implements Sections 6–7 (features + API spec)
