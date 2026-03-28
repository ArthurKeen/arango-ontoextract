# AOE Implementation Plan

**Derived from:** PRD.md v3 (2026-03-28)
**Approach:** Each PRD phase is decomposed into weekly sprints with specific tasks, files to create/modify, dependencies, and acceptance criteria.

---

## Phase 1: Foundation (Weeks 1–3)

**Goal:** Database schema, document ingestion pipeline, test infrastructure, dev-time MCP.

### Week 1: Schema, Migration Framework & Test Infrastructure

**Focus:** Get the database schema deployed, migration tooling in place, and CI pipeline running.

| # | Task | Files | Depends On | Acceptance Criteria |
|---|------|-------|------------|---------------------|
| 1.1 | Implement migration runner framework | `backend/migrations/runner.py`, `backend/migrations/__init__.py` | — | `python -m migrations.runner` applies pending migrations in order; tracks state in `_system_meta` |
| 1.2 | Migration 001: Create all non-temporal collections | `backend/migrations/001_initial_collections.py` | 1.1 | `documents`, `chunks`, `extraction_runs`, `curation_decisions`, `notifications`, `organizations`, `users`, `_system_meta`, `ontology_registry` created idempotently |
| 1.3 | Migration 002: Create versioned vertex collections | `backend/migrations/002_versioned_vertices.py` | 1.2 | `ontology_classes`, `ontology_properties`, `ontology_constraints` created with temporal field defaults |
| 1.4 | Migration 003: Create edge collections | `backend/migrations/003_edge_collections.py` | 1.3 | All 8 edge collections created (`subclass_of`, `equivalent_class`, `has_property`, `extends_domain`, `extracted_from`, `related_to`, `merge_candidate`, `imports`) |
| 1.5 | Migration 004: Create named graphs | `backend/migrations/004_named_graphs.py` | 1.4 | `domain_ontology` graph created with correct vertex/edge definitions per PRD Section 5.1 |
| 1.6 | Migration 005: MDI-prefixed temporal indexes | `backend/migrations/005_mdi_indexes.py` | 1.3, 1.4 | MDI-prefixed indexes on `[created, expired]` deployed on all versioned vertex and edge collections |
| 1.7 | Migration 006: TTL indexes for historical aging | `backend/migrations/006_ttl_indexes.py` | 1.3, 1.4 | Sparse TTL indexes on `ttlExpireAt` field for all versioned collections |
| 1.8 | Migration 007: ArangoSearch views | `backend/migrations/007_arangosearch_views.py` | 1.2, 1.3 | ArangoSearch view on `ontology_classes` (label, description) for BM25 blocking |
| 1.9 | Migration 008: Vector indexes | `backend/migrations/008_vector_indexes.py` | 1.2 | HNSW vector index on `chunks.embedding` field |
| 1.10 | Update `schema.py` to call migration runner | `backend/app/db/schema.py` | 1.1 | `init_schema(db)` runs all pending migrations |
| 1.11 | CI pipeline: lint + type check + unit tests | `.github/workflows/ci.yml` | — | GitHub Actions runs `ruff check`, `mypy`, `pytest tests/unit/` on every push |
| 1.12 | Docker Compose test profile | `docker-compose.test.yml` | — | `docker compose -f docker-compose.test.yml up` starts ephemeral ArangoDB + Redis for integration tests |
| 1.13 | Test conftest with auto-create/drop test DB | `backend/tests/conftest.py` | 1.12 | `test_db` fixture creates unique DB, runs migrations, yields, drops DB |
| 1.14 | Copy test fixtures | `backend/tests/fixtures/ontologies/aws.ttl`, `backend/tests/fixtures/sample_documents/` | — | Sample OWL file and 2-3 test documents (PDF, DOCX, Markdown) in fixtures |
| 1.15 | Integration test: migration runner | `backend/tests/integration/test_migrations.py` | 1.1–1.9, 1.13 | All migrations apply cleanly on fresh DB; re-running is idempotent |

**Week 1 exit:** `make migrate` creates the full schema on a fresh ArangoDB. CI pipeline green. Test DB auto-provisioning works.

### Week 2: Document Ingestion Pipeline

**Focus:** Upload → parse → chunk → embed, with full API and tests.

| # | Task | Files | Depends On | Acceptance Criteria |
|---|------|-------|------------|---------------------|
| 2.1 | Document repository (DB layer) | `backend/app/db/documents_repo.py` | W1 | CRUD for `documents` and `chunks` collections; typed functions, no raw AQL in other modules |
| 2.2 | Document parsing service (PDF/DOCX/Markdown) | `backend/app/services/ingestion.py` | — | Parses PDF (via `pymupdf` or `pdfplumber`), DOCX (via `python-docx`), and Markdown; extracts text preserving structure |
| 2.3 | Semantic chunking | `backend/app/services/ingestion.py` | 2.2 | Chunks text at section/paragraph boundaries; respects `max_tokens` config; preserves source page/section metadata |
| 2.4 | Vector embedding service | `backend/app/services/embedding.py` | — | Calls OpenAI `text-embedding-3-small` (or configurable model); returns embeddings for text chunks |
| 2.5 | Async pipeline orchestration (Celery/ARQ) | `backend/app/services/ingestion.py`, `backend/app/tasks.py` | 2.2, 2.3, 2.4 | Document upload triggers async task: parse → chunk → embed → store; status updates to `documents.status` |
| 2.6 | Implement document API endpoints | `backend/app/api/documents.py` | 2.1, 2.5 | `POST /upload` triggers pipeline, `GET /{doc_id}` returns status, `GET /{doc_id}/chunks` returns chunks with pagination |
| 2.7 | SHA-256 duplicate detection | `backend/app/services/ingestion.py` | 2.1 | Hash check on upload; rejects identical files with `409 Conflict` |
| 2.8 | Pagination helper (cursor-based) | `backend/app/db/pagination.py` | — | Reusable cursor-based pagination for all list endpoints; returns `{data, cursor, has_more, total_count}` |
| 2.9 | Standard error response handler | `backend/app/api/errors.py` | — | FastAPI exception handlers producing PRD Section 7.8 error format |
| 2.10 | Unit tests: parsing, chunking, embedding | `backend/tests/unit/test_ingestion.py`, `backend/tests/unit/test_embedding.py` | 2.2–2.4 | Mocked LLM/embedding calls; tests for PDF/DOCX/Markdown parsing; edge cases (empty doc, huge doc) |
| 2.11 | Integration tests: document API | `backend/tests/integration/test_documents_api.py` | 2.6, 1.13 | Upload sample PDF → verify chunks created → verify status transitions |
| 2.12 | Add backend dependencies | `backend/pyproject.toml` | — | Add `pymupdf`, `python-docx`, `langchain`, `openai`, `celery`/`arq`, `redis` |

**Week 2 exit:** Can upload a PDF via API and retrieve semantically chunked, embedded content. Duplicate detection works. Pagination and error format established.

### Week 3: Dev-time MCP Server & Ontology Registry

**Focus:** MCP for Cursor development, ontology registry foundation, frontend test setup.

| # | Task | Files | Depends On | Acceptance Criteria |
|---|------|-------|------------|---------------------|
| 3.1 | Dev-time MCP server scaffold | `backend/app/mcp/server.py`, `backend/app/mcp/__init__.py` | W1 | MCP server starts via stdio; connects to same ArangoDB instance |
| 3.2 | MCP tool: `query_collections` | `backend/app/mcp/tools/introspection.py` | 3.1 | Claude in Cursor can list collections and sample documents |
| 3.3 | MCP tool: `run_aql` | `backend/app/mcp/tools/introspection.py` | 3.1 | Claude can run read-only AQL queries against the dev database |
| 3.4 | Ontology registry repository | `backend/app/db/registry_repo.py` | W1 | CRUD for `ontology_registry` collection |
| 3.5 | Ontology library API endpoints | `backend/app/api/ontology.py` | 3.4 | `GET /library` lists registered ontologies; `GET /library/{id}` returns detail with stats |
| 3.6 | Frontend: install Jest + React Testing Library + Playwright | `frontend/package.json`, `frontend/jest.config.ts`, `frontend/playwright.config.ts` | — | `npm test` runs Jest; `npx playwright test` runs E2E |
| 3.7 | Frontend: API client scaffold | `frontend/src/lib/api-client.ts` | — | Typed fetch wrapper for all backend API endpoints; handles pagination envelope |
| 3.8 | Frontend: health check page | `frontend/src/app/page.tsx` | 3.7 | Landing page shows backend connection status and basic system stats |
| 3.9 | CI pipeline: add integration tests + frontend lint | `.github/workflows/ci.yml` | 1.11, 1.12 | CI runs integration tests against Docker ArangoDB; runs `eslint` + `tsc --noEmit` on frontend |
| 3.10 | Makefile: `make migrate`, `make test-unit`, `make test-integration` | `Makefile` | 1.1, 1.11 | Convenience commands for common dev workflows |

**Phase 1 exit:** Full schema deployed. Document ingestion pipeline working end-to-end. Dev MCP server operational in Cursor. CI pipeline green with unit + integration tests. Coverage ≥ 80% on foundation code.

---

## Phase 2: Extraction Pipeline & Agentic Orchestration (Weeks 4–7)

**Goal:** LLM-driven ontology extraction via LangGraph, with pipeline monitoring UI.

### Week 4: LangGraph Scaffold & Strategy Selector

| # | Task | Files | Depends On | Acceptance Criteria |
|---|------|-------|------------|---------------------|
| 4.1 | Install LangGraph; define state schema | `backend/app/extraction/state.py` | — | `ExtractionPipelineState` TypedDict matching PRD Section 6.11 |
| 4.2 | Pipeline graph definition | `backend/app/extraction/pipeline.py` | 4.1 | `StateGraph` with nodes for each agent; conditional edges; compiles to runnable |
| 4.3 | Strategy Selector agent | `backend/app/extraction/agents/strategy.py` | 4.1 | Analyzes document type + length; selects model, prompt template, chunk params |
| 4.4 | Prompt template system | `backend/app/extraction/prompts/` | — | Per-domain prompt templates; Jinja2 or string templates; domain ontology context injection slot |
| 4.5 | Extraction run service | `backend/app/services/extraction.py` | 4.2, W2 | Creates `extraction_runs` record; dispatches LangGraph pipeline; updates status |
| 4.6 | Extraction API endpoints (full) | `backend/app/api/extraction.py` | 4.5 | `POST /run`, `GET /runs`, `GET /runs/{id}`, `GET /runs/{id}/steps`, `POST /runs/{id}/retry`, `GET /runs/{id}/cost` |
| 4.7 | Unit tests: strategy selector | `backend/tests/unit/test_strategy_selector.py` | 4.3 | Different document types produce different configs |

### Week 5: Extraction Agent & Consistency Checker

| # | Task | Files | Depends On | Acceptance Criteria |
|---|------|-------|------------|---------------------|
| 5.1 | Extraction Agent (N-pass with self-correction) | `backend/app/extraction/agents/extractor.py` | 4.1, 4.4 | Runs N LLM passes; validates output against `ExtractedClass`/`ExtractionResult` Pydantic models; retries up to 3x on validation failure with error message fed back |
| 5.2 | Consistency Checker agent | `backend/app/extraction/agents/consistency.py` | 4.1 | Compares N-pass results; keeps concepts appearing in ≥ M passes; assigns confidence scores |
| 5.3 | RAG context injection | `backend/app/extraction/agents/extractor.py` | W2 (embedding) | Retrieves relevant chunks via vector similarity; injects into extraction prompt |
| 5.4 | Pipeline checkpointing | `backend/app/extraction/pipeline.py` | 4.2 | LangGraph state persisted to Redis or DB; pipeline resumable after failure |
| 5.5 | Structured agent logging | `backend/app/extraction/agents/` (all) | 4.1 | Every agent step emits structured log with `run_id`, step name, duration, tokens, errors |
| 5.6 | Record LLM response fixtures | `backend/tests/fixtures/llm_responses/` | 5.1 | 3-5 recorded extraction responses for deterministic testing |
| 5.7 | Unit tests: extractor, consistency checker | `backend/tests/unit/test_extraction_parser.py`, `backend/tests/unit/test_consistency.py` | 5.1, 5.2, 5.6 | Mocked LLM responses; tests for validation failure + retry; tests for cross-pass agreement filtering |

### Week 6: ArangoRDF Integration & Staging Graphs

| # | Task | Files | Depends On | Acceptance Criteria |
|---|------|-------|------------|---------------------|
| 6.1 | ArangoRDF bridge service | `backend/app/services/arangordf_bridge.py` | — | Wraps `arango_rdf.rdf_to_arangodb_by_pgt()`; adds post-import `ontology_id` tagging; creates per-ontology named graph |
| 6.2 | Extraction → OWL serialization | `backend/app/services/extraction.py` | 5.1 | Converts `ExtractionResult` (Pydantic) → rdflib Graph (OWL/TTL) |
| 6.3 | Staging graph creation | `backend/app/services/ontology.py` | 6.1, 6.2, W1 | Extraction output imported via PGT into `staging_{run_id}` named graph; all entities tagged with `ontology_id` |
| 6.4 | Temporal versioning service | `backend/app/services/temporal.py` | W1 | `create_version()`, `expire_entity()`, `re_create_edges()` — core edge-interval time travel operations |
| 6.5 | Ontology repository (DB layer) | `backend/app/db/ontology_repo.py` | W1 | CRUD for `ontology_classes`, `ontology_properties`, edges; all operations use temporal versioning |
| 6.6 | Staging ontology API endpoint | `backend/app/api/ontology.py` | 6.3, 6.5 | `GET /staging/{run_id}` returns staging graph as JSON |
| 6.7 | Integration tests: ArangoRDF import | `backend/tests/integration/test_arangordf_import.py` | 6.1, 1.13, 1.14 | Import `aws.ttl` → verify collections populated → verify named graph → verify `ontology_id` tagging |
| 6.8 | Integration tests: temporal versioning | `backend/tests/integration/test_temporal_queries.py` | 6.4, 1.13 | Create entity → edit → verify old expired + new created → point-in-time snapshot returns correct version |

### Week 7: Pipeline Monitor Dashboard & WebSocket

| # | Task | Files | Depends On | Acceptance Criteria |
|---|------|-------|------------|---------------------|
| 7.1 | WebSocket endpoint: extraction progress | `backend/app/api/ws_extraction.py` | 4.5 | `ws://host/ws/extraction/{run_id}` emits `step_started`, `step_completed`, `step_failed`, `completed` |
| 7.2 | Agent step event emission | `backend/app/extraction/pipeline.py` | 7.1 | LangGraph node callbacks publish events to WebSocket via Redis Pub/Sub |
| 7.3 | Frontend: Pipeline Monitor page scaffold | `frontend/src/app/pipeline/page.tsx` | 3.7 | Route `/pipeline` with run list and detail layout |
| 7.4 | Frontend: Run List component | `frontend/src/components/pipeline/RunList.tsx` | 7.3 | Filterable/sortable list of extraction runs; status badges; auto-refresh |
| 7.5 | Frontend: Agent DAG component (React Flow) | `frontend/src/components/pipeline/AgentDAG.tsx` | 7.3 | React Flow graph rendering the LangGraph pipeline; custom node components with status icons |
| 7.6 | Frontend: WebSocket hook | `frontend/src/lib/use-websocket.ts` | — | React hook for WebSocket connection with reconnect logic; updates Agent DAG nodes in real-time |
| 7.7 | Frontend: Run Metrics panel | `frontend/src/components/pipeline/RunMetrics.tsx` | 7.3 | Duration, token usage, estimated cost, entity counts |
| 7.8 | Frontend: Error Log panel | `frontend/src/components/pipeline/ErrorLog.tsx` | 7.3 | Timestamped error list; expandable details; retry button |
| 7.9 | E2E test: extraction pipeline | `backend/tests/e2e/test_extraction_flow.py` | 6.3, 4.6 | Upload PDF → trigger extraction → verify staging graph created → verify run status transitions |
| 7.10 | Frontend unit tests: pipeline components | `frontend/src/components/pipeline/__tests__/` | 7.4–7.8 | Component rendering, mock WebSocket events, status transitions |

**Phase 2 exit:** Full extraction pipeline working end-to-end. Pipeline Monitor Dashboard shows real-time agent status. Can extract an ontology from a PDF, store it in staging, and monitor progress via UI.

---

## Phase 3: Curation Dashboard, VCR Timeline & Visualizer (Weeks 8–12)

**Goal:** Visual curation, temporal time travel, and ArangoDB Visualizer customization.

### Week 8: Curation Dashboard — Graph Rendering & Actions

| # | Task | Files | Depends On | Acceptance Criteria |
|---|------|-------|------------|---------------------|
| 8.1 | Frontend: Curation page scaffold | `frontend/src/app/curation/[runId]/page.tsx` | 3.7 | Route `/curation/{runId}` with graph viewport and side panels |
| 8.2 | Frontend: Graph Canvas (React Flow or Cytoscape) | `frontend/src/components/graph/GraphCanvas.tsx` | — | Renders ontology graph: nodes = classes (colored by type/tier), edges = relationships; zoom, pan, filter |
| 8.3 | Frontend: Node detail panel | `frontend/src/components/curation/NodeDetail.tsx` | 8.2 | Click node → side panel shows URI, label, description, status, confidence, provenance links |
| 8.4 | Frontend: Node actions (approve/reject/edit/merge) | `frontend/src/components/curation/NodeActions.tsx` | 8.3 | Action buttons; each action calls backend API; UI updates optimistically |
| 8.5 | Frontend: Edge actions (approve/reject/retype) | `frontend/src/components/curation/EdgeActions.tsx` | 8.2 | Right-click or select edge → action panel |
| 8.6 | Frontend: Batch operations | `frontend/src/components/curation/BatchActions.tsx` | 8.2 | Multi-select nodes/edges → bulk approve/reject |
| 8.7 | Curation service (backend) | `backend/app/services/curation.py` | 6.4, 6.5 | `record_decision()` creates `curation_decisions` entry + temporal version; `promote_staging()` moves approved entities |
| 8.8 | Curation API endpoints (full) | `backend/app/api/curation.py` | 8.7 | `POST /decide`, `GET /decisions`, `POST /merge` — all with temporal versioning |
| 8.9 | Promotion service | `backend/app/services/ontology.py` | 8.7, 6.4 | Move approved staging entities to production graph; create temporal versions |

### Week 9: Provenance, Diff View & Confidence

| # | Task | Files | Depends On | Acceptance Criteria |
|---|------|-------|------------|---------------------|
| 9.1 | Provenance display | `frontend/src/components/curation/ProvenancePanel.tsx` | 8.3 | Click node → see source chunks with highlighted text; links to document viewer |
| 9.2 | Confidence score visualization | `frontend/src/components/graph/GraphCanvas.tsx` | 8.2 | Nodes colored/sized by confidence; low-confidence nodes visually highlighted |
| 9.3 | Diff view: staging vs production | `frontend/src/components/curation/DiffView.tsx` | 8.2 | Side-by-side or overlay: new nodes green, removed red, changed yellow |
| 9.4 | Staging promotion workflow UI | `frontend/src/components/curation/PromotePanel.tsx` | 8.9 | Review summary → confirm → one-click promotion; shows what will be promoted |
| 9.5 | Integration tests: curation workflow | `backend/tests/integration/test_curation_workflow.py` | 8.7, 8.8 | Record decision → verify `curation_decisions` entry → verify temporal version created → promote → verify in production graph |
| 9.6 | Frontend component tests: curation | `frontend/src/components/curation/__tests__/` | 8.3–8.6 | Component rendering with mocked API; action click handlers |

### Week 10: Temporal APIs & VCR Timeline

| # | Task | Files | Depends On | Acceptance Criteria |
|---|------|-------|------------|---------------------|
| 10.1 | Point-in-time snapshot API | `backend/app/api/ontology.py`, `backend/app/services/temporal.py` | 6.4 | `GET /ontology/{id}/snapshot?at={ts}` returns full graph state at timestamp |
| 10.2 | Version history API | `backend/app/api/ontology.py`, `backend/app/db/ontology_repo.py` | 6.5 | `GET /ontology/class/{key}/history` returns all versions by URI sorted by `created` DESC |
| 10.3 | Temporal diff API | `backend/app/api/ontology.py`, `backend/app/services/temporal.py` | 6.4 | `GET /ontology/{id}/diff?t1=&t2=` returns added/removed/changed entities |
| 10.4 | Timeline events API | `backend/app/api/ontology.py` | 6.5 | `GET /ontology/{id}/timeline` returns discrete change events for slider tick marks |
| 10.5 | Revert-to-version API | `backend/app/api/ontology.py`, `backend/app/services/temporal.py` | 6.4 | `POST /ontology/class/{key}/revert?to_version={n}` creates new current version restoring historical state |
| 10.6 | Frontend: VCR Timeline slider | `frontend/src/components/timeline/VCRTimeline.tsx` | 10.1, 10.4 | Timeline control with play/pause/rewind/ff; drag to any timestamp; graph re-renders |
| 10.7 | Frontend: Timeline event markers | `frontend/src/components/timeline/VCRTimeline.tsx` | 10.4 | Tick marks on timeline at each version creation; click jumps to that moment |
| 10.8 | Frontend: Diff overlay on graph | `frontend/src/components/graph/DiffOverlay.tsx` | 10.3, 8.2 | Overlay colors: added (green), removed (red), changed (yellow) |
| 10.9 | Frontend: Entity Focus mode | `frontend/src/components/timeline/EntityHistory.tsx` | 10.2 | Select class → vertical timeline showing all versions with diffs between each |
| 10.10 | Integration tests: temporal APIs | `backend/tests/integration/test_temporal_queries.py` | 10.1–10.5 | Create 3 versions → snapshot at each timestamp → diff between t1 and t3 → revert to v1 → verify |
| 10.11 | Frontend tests: VCR timeline | `frontend/src/components/timeline/__tests__/VCRTimeline.test.tsx` | 10.6 | Slider interaction, timestamp display, mock API responses |

### Week 11: ArangoDB Graph Visualizer Customization

| # | Task | Files | Depends On | Acceptance Criteria |
|---|------|-------|------------|---------------------|
| 11.1 | Ontology theme JSON definitions | `docs/visualizer/themes/ontology_theme.json` | — | OWL/RDFS/SKOS node type colors, icons, and edge styles per PRD Section 6.6 |
| 11.2 | Canvas action definitions | `docs/visualizer/actions/ontology_actions.json` | — | All 7 right-click actions from PRD Section 6.6; AQL queries with temporal edge filtering |
| 11.3 | Saved query definitions | `docs/visualizer/queries/ontology_queries.json` | — | All 10 saved queries from PRD Section 6.6 (class hierarchy, orphans, cross-tier, temporal queries) |
| 11.4 | Visualizer install script | `scripts/setup/install_visualizer.py` | 11.1–11.3 | Idempotent installer: creates themes, canvas actions, saved queries, viewpoints; `prune_theme()` per graph |
| 11.5 | Viewpoint auto-creation | `scripts/setup/install_visualizer.py` | 11.4 | `ensure_default_viewpoint()` creates viewpoint per ontology graph; links actions + queries |
| 11.6 | Integration tests: visualizer install | `backend/tests/integration/test_visualizer_install.py` | 11.4, 1.13 | Run installer twice → idempotent → verify `_graphThemeStore`, `_canvasActions`, `_editor_saved_queries` populated |

### Week 12: Integration, Polish & Phase 3 Testing

| # | Task | Files | Depends On | Acceptance Criteria |
|---|------|-------|------------|---------------------|
| 12.1 | Connect curation UI to staging graph | Integration across 8.x and 10.x | W8–W10 | Full flow: see staging graph → make decisions → see temporal versions → scrub timeline |
| 12.2 | Frontend: Ontology Library browser | `frontend/src/app/library/page.tsx`, `frontend/src/components/library/OntologyList.tsx` | 3.5 | List all registered ontologies; drill into class hierarchy |
| 12.3 | Frontend E2E: curation workflow | `frontend/e2e/curation.spec.ts` | 12.1 | Playwright: open staging → approve class → verify promoted |
| 12.4 | Frontend E2E: VCR timeline | `frontend/e2e/timeline.spec.ts` | 10.6 | Playwright: load ontology → drag slider → verify graph changes |
| 12.5 | Performance check: graph rendering | — | 8.2 | Verify < 2s render for 500-node graph; add lazy loading if needed |
| 12.6 | Phase 3 documentation | `docs/design/curation-dashboard.md` | — | Architecture decisions for graph library choice, temporal UX patterns |

**Phase 3 exit:** Domain expert can visually review, edit, and promote extracted ontologies. VCR timeline works. ArangoDB Visualizer customized. ≥ 80% backend coverage; CI green.

---

## Phase 4: Tier 2, Entity Resolution & Pre-Curation (Weeks 13–16)

### Week 13: Tier 2 Context-Aware Extraction

| # | Task | Files | Depends On | Acceptance Criteria |
|---|------|-------|------------|---------------------|
| 13.1 | Domain ontology context serializer | `backend/app/services/ontology.py` | 6.5 | Serialize domain ontology class hierarchy as compact text for LLM prompt injection |
| 13.2 | Tier 2 prompt templates | `backend/app/extraction/prompts/tier2/` | 4.4 | Prompt includes domain ontology context; instructs LLM to classify as EXISTING/EXTENSION/NEW |
| 13.3 | Extension classification in extraction output | `backend/app/models/ontology.py` | — | `ExtractionClassification` enum already exists; verify extraction agent uses it |
| 13.4 | Cross-tier edge creation | `backend/app/services/ontology.py` | 6.4, 6.5 | `extends_domain` edges created for EXTENSION entities linking local → domain classes |
| 13.5 | Organization ontology selection API | `backend/app/api/ontology.py` | 3.4 | `PUT /orgs/{org_id}` to select base ontologies; extraction uses only selected ontologies as context |
| 13.6 | Conflict detection service | `backend/app/services/ontology.py` | 6.5 | Detects same-URI, contradicting range, hierarchy redefinition per PRD Section 6.3 |

### Week 14: Entity Resolution Integration

| # | Task | Files | Depends On | Acceptance Criteria |
|---|------|-------|------------|---------------------|
| 14.1 | Install `arango-entity-resolution` dependency | `backend/pyproject.toml` | — | Library available for import |
| 14.2 | ER configuration service | `backend/app/services/er.py` | 14.1 | `ERPipelineConfig` configured for ontology fields (label, description, uri); blocking strategy orchestration |
| 14.3 | Topological similarity scoring (AOE-specific) | `backend/app/services/er.py` | 14.2, 6.5 | Graph neighborhood comparison: shared properties, shared parents as scoring dimension |
| 14.4 | ER API endpoints | `backend/app/api/er.py` | 14.2 | All 8 endpoints from PRD Section 7.5: run, status, candidates, clusters, explain, cross-tier, config |
| 14.5 | ER collections creation (migration) | `backend/migrations/009_er_collections.py` | 14.1 | `similarTo`, `entity_clusters`, `golden_records` collections created |
| 14.6 | Integration tests: ER pipeline | `backend/tests/integration/test_er_pipeline.py` | 14.2, 14.5 | Seed 20 ontology classes with near-duplicates → run pipeline → verify candidate pairs → verify clusters |

### Week 15: Pre-Curation Filter & ER LangGraph Agents

| # | Task | Files | Depends On | Acceptance Criteria |
|---|------|-------|------------|---------------------|
| 15.1 | Entity Resolution LangGraph agent | `backend/app/extraction/agents/er_agent.py` | 14.2, 4.2 | Wraps ER pipeline; invoked after consistency checker; produces merge candidates + `extends_domain` edges |
| 15.2 | Pre-Curation Filter agent | `backend/app/extraction/agents/filter.py` | 4.2 | Removes noise (generic terms, duplicates within run); annotates confidence tiers; adds provenance |
| 15.3 | Add ER + filter nodes to LangGraph pipeline | `backend/app/extraction/pipeline.py` | 15.1, 15.2 | Full pipeline: Strategy → Extraction → Consistency → ER → Pre-Curation → Staging |
| 15.4 | Human-in-the-loop breakpoint | `backend/app/extraction/pipeline.py` | 15.3 | Pipeline pauses after pre-curation; emits WebSocket event; resumes after curation decisions |
| 15.5 | Unit tests: ER agent, filter agent | `backend/tests/unit/test_er_agent.py`, `backend/tests/unit/test_filter_agent.py` | 15.1, 15.2 | Mocked ER pipeline; verify filtering removes ≥ 20% noise |

### Week 16: Merge UI & Cross-Tier Dashboard

| # | Task | Files | Depends On | Acceptance Criteria |
|---|------|-------|------------|---------------------|
| 16.1 | Frontend: Merge candidate panel | `frontend/src/components/curation/MergeCandidates.tsx` | 14.4 | Shows candidate pairs with scores, `explain_match` evidence; accept/reject buttons |
| 16.2 | Frontend: Merge execution | `frontend/src/components/curation/MergeExecutor.tsx` | 8.7 | One-click merge; shows before/after; preserves provenance |
| 16.3 | Frontend: Cross-tier visualization | `frontend/src/components/graph/GraphCanvas.tsx` | 8.2 | Domain classes in one color, local extensions in another; `extends_domain` edges visible |
| 16.4 | E2E test: Tier 2 extraction + ER + merge | `backend/tests/e2e/test_tier2_flow.py` | 15.3, 8.7 | Upload org doc → extract with domain context → ER finds duplicates → merge in UI → verify |

**Phase 4 exit:** Tier 2 extraction extends domain ontology. ER detects and suggests merges. Pre-curation reduces review burden by ≥ 20%. Cross-tier visualization works.

---

## Phase 5: MCP Server & Runtime Integration (Weeks 17–19)

### Week 17: Runtime MCP Server Core

| # | Task | Files | Depends On | Acceptance Criteria |
|---|------|-------|------------|---------------------|
| 17.1 | MCP server as standalone process | `backend/app/mcp/server.py` | 3.1 | Runs independently from FastAPI; supports stdio + SSE transports |
| 17.2 | Ontology query tools | `backend/app/mcp/tools/ontology.py` | 3.4, 6.5 | `query_domain_ontology`, `get_class_hierarchy`, `get_class_properties`, `search_similar_classes` |
| 17.3 | Pipeline tools | `backend/app/mcp/tools/pipeline.py` | 4.5 | `trigger_extraction`, `get_extraction_status`, `get_merge_candidates` |
| 17.4 | Temporal tools | `backend/app/mcp/tools/temporal.py` | 6.4 | `get_ontology_snapshot`, `get_class_history`, `get_ontology_diff` |
| 17.5 | Provenance + export tools | `backend/app/mcp/tools/export.py` | 6.5 | `get_provenance`, `export_ontology` |

### Week 18: MCP Resources, ER Integration & Auth

| # | Task | Files | Depends On | Acceptance Criteria |
|---|------|-------|------------|---------------------|
| 18.1 | MCP resources | `backend/app/mcp/resources/` | 17.1 | `aoe://ontology/domain/summary`, `aoe://extraction/runs/recent`, `aoe://system/health` |
| 18.2 | ER MCP tool proxying | `backend/app/mcp/tools/er.py` | 14.2, 17.1 | AOE MCP server proxies calls to `arango-entity-resolution` MCP tools |
| 18.3 | Organization-scoped auth for MCP | `backend/app/mcp/auth.py` | 17.1 | MCP tools filter by `org_id`; API key validation |
| 18.4 | Auto-generate tool schemas from Pydantic | `backend/app/mcp/server.py` | 17.2–17.5 | Tool parameter schemas derived from Pydantic models |

### Week 19: MCP Testing & Documentation

| # | Task | Files | Depends On | Acceptance Criteria |
|---|------|-------|------------|---------------------|
| 19.1 | Integration tests: MCP tools | `backend/tests/integration/test_mcp_tools.py` | 17.2–17.5 | Each MCP tool returns correct data; org isolation enforced |
| 19.2 | MCP server documentation | `docs/mcp-server.md` | 17.1 | Tool catalog, connection instructions for Cursor + Claude Desktop + custom clients |
| 19.3 | E2E test: external agent workflow | `backend/tests/e2e/test_mcp_e2e.py` | 17.1 | Simulated external agent: connect → query ontology → trigger extraction → check status |

**Phase 5 exit:** External AI agents can connect via MCP and query/trigger all ontology operations. Tool schemas auto-generated. Org isolation enforced.

---

## Phase 6: Production Hardening (Weeks 20–24)

### Week 20: Import/Export

| # | Task | Files | Depends On | Acceptance Criteria |
|---|------|-------|------------|---------------------|
| 20.1 | OWL/TTL import service | `backend/app/services/arangordf_bridge.py` | 6.1 | Import via UI or API; creates registry entry; per-ontology named graph; `ontology_id` tagging |
| 20.2 | OWL/TTL/JSON-LD export service | `backend/app/services/export.py` | 6.5 | Export any ontology graph as valid OWL 2 Turtle, JSON-LD, or CSV |
| 20.3 | Import/export API endpoints | `backend/app/api/ontology.py` | 20.1, 20.2 | `POST /import` (file upload), `GET /export?format=ttl` |
| 20.4 | Schema extraction service | `backend/app/services/schema_extraction.py` | — | Wraps `arango-schema-mapper`; connects to external ArangoDB; extracts → OWL → AOE import pipeline |
| 20.5 | Schema extraction API endpoints | `backend/app/api/ontology.py` | 20.4 | `POST /schema/extract`, `GET /schema/extract/{run_id}` |
| 20.6 | Integration tests: import/export roundtrip | `backend/tests/integration/test_import_export.py` | 20.1, 20.2 | Import `aws.ttl` → export as TTL → re-import → verify equivalence |

### Week 21: Authentication & Multi-Tenancy

| # | Task | Files | Depends On | Acceptance Criteria |
|---|------|-------|------------|---------------------|
| 21.1 | Auth middleware (OAuth 2.0 / OIDC) | `backend/app/api/auth.py`, `backend/app/api/dependencies.py` | — | JWT validation; extracts user + org from token; FastAPI dependency |
| 21.2 | RBAC enforcement | `backend/app/api/dependencies.py` | 21.1 | Role-based guards: `admin`, `ontology_engineer`, `domain_expert`, `viewer` |
| 21.3 | Organization/user API endpoints | `backend/app/api/orgs.py` | 21.1 | All 8 endpoints from PRD Section 7.6 |
| 21.4 | `org_id` filter enforcement in repository layer | `backend/app/db/` (all repos) | 21.1 | All tenant-scoped queries filter by `org_id` from auth context |
| 21.5 | Frontend: auth integration | `frontend/src/lib/auth.ts`, `frontend/src/middleware.ts` | 21.1 | Login redirect, token management, role-based UI visibility |

### Week 22: Notifications & Observability

| # | Task | Files | Depends On | Acceptance Criteria |
|---|------|-------|------------|---------------------|
| 22.1 | Notification service | `backend/app/services/notification.py` | — | Writes to `notifications` collection; publishes to Redis Pub/Sub |
| 22.2 | Notification API endpoints | `backend/app/api/notifications.py` | 22.1 | `GET /notifications` (paginated), `POST /notifications/{id}/read`, `GET /notifications/unread-count` |
| 22.3 | WebSocket: curation collaboration | `backend/app/api/ws_curation.py` | 22.1 | `ws://host/ws/curation/{session_id}` broadcasts decision events to all curators |
| 22.4 | Prometheus metrics | `backend/app/api/metrics.py` | — | Request latency, extraction throughput, queue depth, error rates |
| 22.5 | OpenTelemetry tracing | `backend/app/main.py` | — | Spans across ingestion → extraction → storage; trace context propagation |
| 22.6 | Alerting rules | `docs/ops/alerts.yml` | 22.4 | Alert definitions: extraction failure rate > 10%, API error rate > 1%, queue backlog > 100 |

### Week 23: Performance, Rate Limiting & Deployment

| # | Task | Files | Depends On | Acceptance Criteria |
|---|------|-------|------------|---------------------|
| 23.1 | Rate limiting middleware | `backend/app/api/rate_limit.py` | — | Per-org limits per PRD Section 7.8 |
| 23.2 | Response caching (snapshot cache) | `backend/app/services/temporal.py` | — | Materialized snapshot cache for frequently-accessed timestamps |
| 23.3 | Dockerfiles | `backend/Dockerfile`, `frontend/Dockerfile`, `backend/app/mcp/Dockerfile` | — | Multi-stage builds; size targets per PRD Section 8.6 |
| 23.4 | Docker Compose production profile | `docker-compose.prod.yml` | 23.3 | All services + TLS + health checks |
| 23.5 | Kubernetes manifests (optional) | `k8s/` | 23.3 | Deployments, services, ingress, HPA for backend |
| 23.6 | Index tuning based on query profiling | `backend/migrations/010_index_tuning.py` | — | Add any missing indexes identified by AQL profiling |

### Week 24: Documentation, Final Testing & Release

| # | Task | Files | Depends On | Acceptance Criteria |
|---|------|-------|------------|---------------------|
| 24.1 | OpenAPI spec review and finalization | — | All API work | OpenAPI spec matches all implemented endpoints |
| 24.2 | User guide | `docs/user-guide.md` | — | Walkthrough: upload → extract → curate → promote → export |
| 24.3 | Architecture decision records | `docs/adr/` | — | ADRs for: graph library choice, temporal pattern, ER integration, auth approach |
| 24.4 | Full E2E test suite | `backend/tests/e2e/`, `frontend/e2e/` | All | Complete flow: auth → upload → extract → curate → merge → promote → export → MCP query |
| 24.5 | Performance benchmarks | `docs/benchmarks.md` | 23.6 | Document: graph rendering < 2s @ 500 nodes, API p95 < 200ms, extraction < 5min/doc |
| 24.6 | Proxy pattern decision | `docs/adr/temporal-proxy-pattern.md` | — | Measure edge re-creation cost; document decision on whether Phase 6 proxy migration is needed |
| 24.7 | Release v1.0.0 | — | All | Tag, changelog, deployment to production |

**Phase 6 exit:** Production-ready with auth, multi-tenancy, observability, notifications, import/export, and documentation. v1.0.0 tagged and deployed.

---

## Summary: Task Count by Phase

| Phase | Weeks | Tasks | Key Dependencies |
|-------|-------|-------|------------------|
| 1: Foundation | 1–3 | 37 | None (greenfield) |
| 2: Extraction Pipeline | 4–7 | 37 | Phase 1 (schema, ingestion, test infra) |
| 3: Curation & Timeline | 8–12 | 38 | Phase 2 (extraction, staging graphs, temporal service) |
| 4: Tier 2 & ER | 13–16 | 22 | Phase 2 (extraction pipeline) + Phase 3 (curation UI) |
| 5: MCP Server | 17–19 | 14 | Phase 2 (extraction) + Phase 3 (temporal) + Phase 4 (ER) |
| 6: Production | 20–24 | 27 | All prior phases |
| **Total** | **24 weeks** | **175 tasks** | |

## Critical Path

```
Schema (W1) → Ingestion (W2) → LangGraph + Extraction (W4-5) → ArangoRDF + Staging (W6)
    ↓                                                                    ↓
Test Infra (W1) ──────────────────────────────────────────────→ All integration tests
    ↓                                                                    ↓
MCP Dev (W3) ──────────────────────────────────────────────────→ MCP Runtime (W17)
                                                                         ↓
Temporal Service (W6) → Temporal APIs (W10) → VCR Timeline (W10) → Snapshot Cache (W23)
    ↓                       ↓
Curation Service (W8) → Curation UI (W8-9) → ER UI (W16)
    ↓
ArangoRDF Bridge (W6) → Import/Export (W20) → Schema Extraction (W20)
    ↓
ER Integration (W14) → ER Agent (W15) → ER MCP (W18)
```
