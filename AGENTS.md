# Agent / contributor guide

## Layout

| Area | Role |
|------|------|
| `backend/` | FastAPI API, LangGraph extraction, ArangoDB access, MCP server |
| `frontend/` | Next.js 15 workspace UI, graph canvas, curation |
| `backend/migrations/` | Ordered `NNN_description.py` modules with `up(db)` — applied via `make migrate` |
| `docs/` | PRD references, ADRs, user guide, remaining-work plans |
| `scripts/` | Tooling (e.g. ArangoDB Visualizer asset install) |

## Conventions

- **Config:** `backend/app/config.py` (`Settings`) — do not read env vars elsewhere.
- **DB:** Repositories under `backend/app/db/`; temporal mutations follow `NEVER_EXPIRES` (`sys.maxsize`).
- **UI:** Primary actions via context menus on `/workspace`; avoid new top-level routes except `/login`.
- **Tests:** Unit tests mock I/O; integration tests use Arango (see `tests/conftest.py`). Run `make test` from repo root.

## Deeper docs

- `backend/AGENTS.md` — backend module boundaries
- `PRD.md` — product requirements
- `docs/REMAINING_WORK_PLAN.md` — backlog streams
