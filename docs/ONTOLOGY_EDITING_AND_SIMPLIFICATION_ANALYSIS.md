# Ontology Editing, Extraction Guidance & Simplification — Analysis & Plan

_Date: 2026-08-11 · Author: analysis pass over the codebase (read-only)_

Driven by two customer demos:

1. During a **HITL curation** demo, the customer asked whether curators can **combine two
   classes into one** or **insert a superclass over one or more classes and sweep up the
   relevant relationships** — via a lasso / shift-click multi-select then a right-click
   action. They expect the broader set of ontology-editor operations, **and** an agent that
   **critiques the curator's action** (pros/cons) because the LLM has a more holistic view
   than the curator's near focus.
2. A second customer wanted to supply a **dictionary of business terms to guide extraction**
   (conceptually similar to providing a **starting ontology** before extraction — which we
   have never verified actually works).

Plus a standing concern: **iterative refinement does not simplify large extracted
ontologies** (the JLR Land Rover manuals produced ~1,700 classes), and questions about
whether the refinement process needs re-specifying and whether to **schedule** it (nightly).

This document reports current state (with `file:line` evidence), and proposes concrete PRD
and implementation-plan updates. **No PRD edits are applied here** — per the dark-factory
policy, PRD patches require explicit acceptance.

---

## 0. Executive summary

**Headline findings**

- **Combine classes exists in the backend but is unreachable as a manual 2-select action.**
  `merge_entities` (`backend/app/services/curation.py:246`, `POST /api/v1/curation/merge`)
  expires the sources and re-points their edges to the target. The only UI path to it is the
  ER-driven **Find Duplicates** overlay — there is no "select these two → merge."
- **Insert-superclass + rehome relationships does not exist** — no endpoint, service, or UI.
- **Reparent is partial and subtly broken** (additive edge — see Bug #2).
- **The workspace canvas is single-select only.** Multi-select (shift / marquee) exists only
  on the _other_ canvas (`GraphCanvas`/React Flow, used by `/ontology/edit` and `/curation`),
  and even there nothing consumes a multi-selection beyond highlight + bulk approve/reject.
  A "select N classes → insert superclass" flow needs a new multi-select + multi-node menu.
- **No agent critiques curation actions today**, but the building blocks are strong and
  reusable (qualitative-evaluation agent = pros/cons prose; revision agent = proposal +
  cross-check + confidence + safety rails).
- **A starting ontology _is_ injected into the extractor prompt** and helps a little — but
  only the target-ontology path is internally consistent, and the **structural enforcement
  net that would prevent duplicates no-ops during extraction** (Bug #1).
- **A business-terms dictionary does not exist**; PRD explicitly defers term-governance
  gating to v2.
- **"Iterative refinement" never reduces the class count of a single over-extracted
  ontology.** The only count-reducer (ER merge) is manual and not wired into any loop; the
  automatic near-duplicate detector is **lexical-only** (misses "Vehicle Alarm System" vs
  "Alarm System"); there is **no scheduler**; and a **single-ontology simplification /
  abstraction process is neither documented nor implemented**.

**Two bugs worth fixing regardless of roadmap priority** (details in §3 and §1):

- **Bug #1 — extraction ER/extension enforcement no-ops.** `target_ontology_id` is never
  threaded into `run_pipeline`, so `metadata["ontology_id"]` is empty; the in-pipeline ER
  agent (`backend/app/extraction/agents/er_agent.py:43,117-129`) and cross-tier extension
  edges (`cross_tier.py`) run against `""` and produce zero merge candidates / zero
  `extends_domain` links. This is a direct contributor to duplicate-class sprawl when
  extracting into an existing ontology.
- **Bug #2 — reparent creates multiple inheritance.** Posting a new `subclass_of` edge only
  expires an edge with the _same_ `_from` **and** `_to` (`mutations.py:220-235`); moving a
  child from parent A to B leaves the old `child→A` edge live. No atomic reparent endpoint
  exists.

---

## 1. Interactive ontology-editing operations

### Current state (backend mutations + curation)

| Operation | Status | Evidence |
|---|---|---|
| Create class / property (+ parent edge) | ✅ | `backend/app/api/ontology/mutations.py:50,118` |
| Edit class label/description/uri/status | ✅ (fields only) | `mutations.py:279-318` |
| Edit edge | ⚠️ status-only | `mutations.py:252-271` (no re-type / re-point) |
| Delete class (temporal cascade) | ✅ | `mutations.py:361` (`expire_class_cascade`) |
| **Merge/combine N classes → 1** | ✅ backend, ⚠️ no manual UI | `services/curation.py:246` `merge_entities`; `POST /api/v1/curation/merge`; UI only via ER "Find Duplicates" (`contextMenus/canvas.ts:175`) |
| **Insert superclass over N + rehome edges** | ❌ missing | none |
| **Reparent (move in hierarchy)** | ⚠️ partial/broken | Bug #2; orphaned `ReparentSelect.tsx` |
| Extract subclass / split class | ❌ missing | none |
| Bulk reparent | ❌ missing | `BatchActions.tsx` = approve/reject-all only |
| Rename (label) | ✅ label-only | `mutations.py:294` (no URI/edge-label cascade) |

### Multi-select blocker

- Workspace (`frontend/src/app/workspace/page.tsx`) uses scalar `selectedNodeKey` /
  `selectedEdgeKey` (`:150-151`); `SigmaCanvas` / `BoxArrowCanvas` take single keys; no
  shift/marquee.
- `GraphCanvas.tsx` (React Flow) supports `multiSelectionKeyCode="Shift"`, `selectionOnDrag`,
  `selectedNodes: string[]` — but only `/ontology/edit` and `/curation` use it, and only for
  highlight / bulk approve-reject. **No multi-node context menu exists anywhere.**

### Reusable primitive

`merge_entities`' edge-re-pointing logic (`re_create_edges` over the ontology edge
collections, `curation.py:285-291`) is the reusable core for "sweep up relationships" — an
insert-superclass op is essentially: create the new class, add `subclass_of` from each
selected class to it, and (optionally) lift shared outgoing/incoming relationships to the
superclass.

### Proposed — PRD

- **FR-4.16 (new): Interactive editing operations.** Curators can, from a multi-selection:
  **Merge** selected classes; **Insert superclass** (create parent + `subclass_of` from each,
  with an option to lift relationships shared by all children up to the new superclass);
  **Reparent** (atomic: expire old `subclass_of`, create new); **Extract subclass**; **Split
  class**. Every operation is temporal (reversible) and evidence-preserving.
- **FR-4.17 (new): Multi-select on the workspace canvas.** Shift-click and marquee/lasso
  selection with a **multi-node context menu**; single-select behavior unchanged.
- Amend **FR-4.2 / FR-4.12** (node actions / drag-reparent) to reference the atomic reparent
  endpoint (closes CQ.5 — see §5).

### Proposed — implementation plan (new Stream: "Interactive Editing", ~M–L)

- **IE.1** Atomic `POST /{id}/classes/{key}/reparent` (expire old `subclass_of`, create new;
  reject cycles). _(also closes CQ.5 reparent half)_
- **IE.2** `POST /{id}/classes/insert-superclass` `{child_keys[], label, lift_shared_relations?}`
  — reuses `re_create_edges` for the sweep-up.
- **IE.3** Manual `POST /{id}/classes/merge` thin wrapper over `merge_entities` for a 2..N
  selection (no ER candidate required).
- **IE.4** Workspace multi-select state (`selectedNodeKeys: string[]`) + shift/marquee in
  `SigmaCanvas`/`BoxArrowCanvas` (or migrate workspace to `GraphCanvas`).
- **IE.5** Multi-node context menu (`contextMenus/multi.ts`) → Merge / Insert superclass /
  Bulk reparent, routed through the shared optimistic-curation helper.
- **IE.6** Wire inline rename (`EditableLabel.tsx`) + reparent (`ReparentSelect.tsx` / DnD) —
  currently orphaned components. _(closes CQ.5 rename half)_
- **IE.7** Tests (backend op semantics incl. cycle rejection + reversibility; UI wiring).

---

## 2. Agent critique of curator actions ("Curation Copilot")

**No such service exists.** Reusable pieces:

- **Qualitative Evaluation agent** → pros/cons prose. `run_qualitative_evaluation(...) ->
  {"strengths":[...], "weaknesses":[...]}` (`backend/app/extraction/judges/qualitative_eval_node.py:312`),
  surfaced at `GET /api/v1/quality/{id}/evaluation`. Currently whole-run scoped.
- **Revision agent** → proposal + deterministic cross-check + confidence + justification +
  safety rails (`services/revision_agent.py:166,272,316`, `revision_safety.py`). The right
  template for "evaluate a proposed action, holistically, with a confidence."
- Deterministic checks to run _before_ the LLM: `ontology_rule_engine.py` (disjoint /
  cardinality / cycle violations the action would introduce), `structural_gate.compute_health_report`.

### Proposed — PRD

- **FR-4.18 (new): Curation action critique.** When a curator initiates a structural edit
  (merge, insert-superclass, reparent, delete), an agent returns a concise **pros/cons +
  risk** assessment before commit: deterministic checks (would this create a cycle, violate a
  declared `disjointWith`, orphan a subtree, or lose evidence?) plus an LLM holistic critique
  (semantic coherence, over-generalization, naming). Advisory by default; the curator decides.
  Non-blocking, time-boxed, and cached per (operation signature, ontology version).

### Proposed — implementation plan (fold into Interactive Editing or Stream 19)

- **CC.1** `POST /{id}/curation/critique` `{operation, targets[]}` → `{deterministic:[...],
  llm_pros:[...], llm_cons:[...], risk, recommendation}`.
- **CC.2** Deterministic pre-checks over `ontology_rule_engine` + affected subgraph.
- **CC.3** LLM critique node (compose `_get_llm` + qualitative-eval prompt style; scope the
  prompt to the affected subgraph + the proposed operation).
- **CC.4** UI: show the critique inline in the confirm step of each structural op.

_Design note:_ this is the same critic engine Stream 19 (Release Readiness) needs — build the
critique core once and use it both at edit-time (per action) and at release-time (whole
candidate). Recommend implementing the shared critic in Stream 19 and calling it here.

---

## 3. Extraction guidance: starting ontology + business-terms dictionary

### What works

- API accepts `target_ontology_id` + `base_ontology_ids` (`api/extraction.py:33-40`) →
  `domain_context` built in `services/extraction.py:209-261` → injected into the Tier-2
  prompt (`prompts/tier2/tier2_standard.py:9-30`, `{domain_context}`). The **target-ontology**
  serializer emits labels **with URIs** + a firm reuse footer
  (`services/ontology_context.py:516-552`). Against a capable model this nudges reuse.

### What's weak / broken

- **Base-ontology context is label-only (no URIs)** (`ontology_context.py:95-99`) while the
  prompt orders the model to "cite the exact domain class URI" — a contradiction that makes
  EXISTING/EXTENSION classification unreliable.
- **No token budget / truncation** — the whole class list is re-sent every batch and every
  pass (catalog bases are up to ~800 classes). Cost + prompt dilution scale badly.
- **No descriptions / `skos:altLabel` synonyms** are injected, even though classes carry them
  — so near-synonyms aren't recognized.
- **Bug #1 — the enforcement layer no-ops.** `er_agent.py:43` reads `metadata.get("ontology_id","")`;
  `_run_er_matching` (`:117-129`) filters `ontology_classes` by `oid==""` → `no_existing_classes`
  → **zero merge candidates**; `_create_extension_edges` → `cross_tier.py` also runs with
  `""` so EXTENSION classes are never linked. Root cause: `execute_run` never passes
  `target_ontology_id` into `run_pipeline` (`extraction.py:324-331`), and `run_pipeline` only
  sets `metadata["domain_ontology_ids"]` (`pipeline.py:240-242`). `belief_revision.py:103` has
  the same empty-id read.
- **Materialization does no semantic dedup** — `_materialize_to_graph` keys a class by URI
  fragment only and `insert(..., overwrite=True)` (`extraction.py:1283,1308`); a
  different-label duplicate is written as new.

### No business-terms dictionary

Repo-wide grep for `glossary|business_terms|controlled vocabulary|lexicon|seed term` is empty
in `app/`. PRD FR-7.8.11 (`PRD.md:3177`) specs an editable glossary **view** but marks
**term-governance gating of extractions out of scope for v1**; Q14e (`PRD.md:4047`) recommends
deferring governance gating to v2.

### Proposed — PRD

- **FR-9.16 (new): Business-terms dictionary as extraction guidance.** Accept a term list
  (term, definition, synonyms/`altLabel`, optional canonical URI) — attached to a target
  ontology or passed per run — injected into extraction as a controlled vocabulary that maps
  surface forms to canonical labels/URIs, with a post-extraction match/canonicalize step.
  (A starting ontology is the OWL-shaped special case of the same mechanism.)
- **Amend FR (Tier-2 context):** require the **base-ontology** serializer to emit URIs +
  definitions + synonyms (parity with the target path), with **retrieval-based budgeting**
  (inject only terms relevant to each batch, using the existing embedding infra), not a
  whole-list dump.
- **Promote FR-7.8.11 governance gate** from v2-deferred to a scoped v1.x flag (advisory
  first): flag off-vocabulary classes.

### Proposed — implementation plan (Stream: "Extraction Guidance", ~M)

- **EG.0 (bug):** thread `target_ontology_id` into `run_pipeline` + set
  `metadata["ontology_id"]` so ER matching + extension edges actually run. _Small, high value._
- **EG.1** URI+definition+synonym base serializer; retrieval-budgeted context (reuse
  `ontology_embeddings.py`, the RAG hook at `extractor.py:179-215`).
- **EG.2** Business-terms input model + prompt injection + post-extraction canonicalize/merge
  (embedding + string) before `_materialize_to_graph`.
- **EG.3** Optional advisory governance flag (off-vocabulary → curation flag).
- **EG.4** Tests + a documented manual verification (extract into an existing ontology, assert
  reuse / merge-candidate creation).

---

## 4. Iterative refinement & single-ontology simplification

### What "refinement" does today — and does not

- **Alignment "iterative refinement"** (`services/alignment.py:747-880`, `refresh_alignment`)
  re-scores **cross-source correspondences** between separate ontologies. It never touches the
  class set of a single ontology.
- **Belief-revision consolidation** (`services/consolidation.py:293`, `run_consolidation`)
  runs rule-engine + optional confidence decay (off by default) + stale-belief scan — and its
  only writes are **`FLAG_FOR_CURATION`** rows (`:210-285`). It flags; it never merges,
  collapses, or prunes. Stale flags are capped at 200 (`:156-159,299`).
- **The only count-reducer is ER merge** (`services/er.py`, `execute_merge` via
  `accept_candidate` `:325-394`) — **human-gated, on-demand only** (`POST /api/er` /
  MCP), and **not invoked after extraction or by consolidation**.
- **The automatic near-duplicate detector is lexical-only.** `_r4_redundant_class`
  (`ontology_rule_engine.py:654-802`) clusters only on **exact normalized label** + a
  conservative singular/plural union. So **"Vehicle Alarm System" vs "Alarm System"** (head/
  modifier), abbreviations, and synonyms are never even flagged — and a hit only emits a
  warning, no merge.
- **No abstraction layer** (no superclass introduction, hierarchy collapse, clustering) and
  **no low-value pruning** that reduces count.

### Why the 1,700-class JLR ontology doesn't simplify

1. Terminology mismatch: "refinement" here = cross-source re-align + incremental belief
   revision as _new documents arrive_ — not "compress this over-extraction."
2. The only reducer (ER merge) is manual and disconnected from any loop.
3. The auto detector is lexical, so it misses the dominant duplication pattern.
4. Consolidation only flags (and caps at 200) → curation noise, not fewer classes.
5. No abstraction / clustering to fold hundreds of leaf classes into higher concepts.
6. No scheduler, so even flag-only consolidation runs only on an admin click.

### Is the process documented? (your question)

- **Belief-revision (§6.16, `PRD.md:2585-2704`) and alignment refinement (§6.17 /
  `docs/multi-source-alignment.md`) are fully documented and implemented.** §6.16 Phase 4 even
  aspires to "background consolidation … on a schedule (default daily)" — but that scheduler
  does not exist, and consolidation only flags.
- **A single-ontology simplification / abstraction algorithm is NOT documented and NOT
  implemented.** → **Yes, please re-share the simplification process you designed.** It is
  genuinely net-new. What it needs to specify: (a) **semantic** near-duplicate detection
  beyond exact-label (embedding + head/modifier + abbreviation/synonym via `altLabel`);
  (b) **superclass abstraction** (cluster leaf classes into higher concepts); (c) **hierarchy
  collapse** (redundant single-child chains); (d) **low-value pruning** (singletons / orphans
  / low-confidence, with evidence-based guards); (e) whether the loop **applies** changes
  (auto, with reversibility + a faithfulness floor) or **proposes** them to a review queue;
  (f) convergence / stopping criteria.

### Scheduling? (your question)

- **No scheduler infrastructure exists** (`tasks.py:4` — "future optimisation"; no
  APScheduler/celery/cron; `main.py` lifespan registers nothing periodic).
- Recommendation: **on-demand + event-triggered first, scheduled second.** Concretely:
  1. Make simplification a **first-class action** (button + endpoint) that a curator runs on a
     bloated ontology and reviews the proposed merges/abstractions (reuses the review-queue +
     critique from §2).
  2. **Trigger** a simplification pass automatically at end of a large extraction (e.g., class
     count over a threshold) — as _proposals_, never silent auto-apply.
  3. **Then** add a nightly job (new lightweight scheduler — APScheduler in the FastAPI
     lifespan, or a k8s `CronJob` hitting an admin endpoint) that runs the simplification +
     consolidation in **dry-run/propose** mode per ontology and files proposals. Nightly
     _auto-apply_ should stay off by default (faithfulness floor + reversibility required),
     consistent with the release-governance autonomy dial (Stream 19).

### Proposed — PRD

- **FR-6.20 (new): Single-ontology simplification.** Semantic near-duplicate detection
  (embedding + morphological), superclass abstraction, hierarchy collapse, and low-value
  pruning — surfaced as **reviewable proposals** (never silent), reversible, with a
  faithfulness floor. Runs on-demand, post-large-extraction (auto-propose), and optionally
  scheduled.
- **Amend §6.16 Phase 4** to state that scheduled consolidation is _unimplemented_ and to
  reference FR-6.20 for the simplification (apply-capable) variant vs today's flag-only
  consolidation.

### Proposed — implementation plan (new Stream: "Simplification", ~L)

- **SI.1** Semantic near-duplicate clustering over `ontology_classes` (reuse ER blocking:
  embedding + BM25) with morphological/head-modifier + `altLabel` synonym matching → merge
  proposals. _(fixes the lexical-only R4 gap)_
- **SI.2** Superclass abstraction: cluster sibling leaf classes → propose a superclass
  (reuses IE.2 insert-superclass).
- **SI.3** Hierarchy collapse + low-value pruning proposals (guarded by evidence/degree).
- **SI.4** Proposal review queue + apply (reuse curation temporal ops + §2 critique).
- **SI.5** Auto-propose hook at end of extraction when class count exceeds a threshold.
- **SI.6** Minimal scheduler (APScheduler/CronJob) → nightly dry-run/propose per ontology,
  hooking `consolidation.run_consolidation`, `er.run_er_pipeline`, and SI.1–SI.3. Auto-apply
  gated by the Stream 19 autonomy policy; default off.

---

## 5. The 8 open drift gaps — state + how they interleave

| Gap (PRD) | State | Remaining | Size | Ties to customer ask |
|---|---|---|---|---|
| **CQ.5 rename/reparent** (§6.4) | components + endpoints exist, unwired; reparent additive (Bug #2) | atomic reparent endpoint + wire `EditableLabel`/`ReparentSelect` | **S/M** | ← §1 editing ops |
| **VCR reverse playback** (§6.5) | forward playback done | continuous reverse + side-by-side diff | **S** | — |
| **FR-19.4 CQ scope** | LLM path done | CQ-priority annotations for relational + graph adapters | M | ← §3 guidance |
| **RS.3 schema enrichment** (§6.9) | analyzer wired as _replacement_ | re-architect to additive (Markdown domain desc + `rdfs:comment` merge, no provenance/SHACL regression) | M | ← §3 guidance |
| **FR-2.15 split-by-domain** | detection done; split action missing | curator "Split by domain" (N staging + umbrella) + UI | M | ← §4 large-ontology mgmt |
| **SO.3 surgeon** (Stream 15) | SO.1/SO.2 done | LLM bounded-patch repair loop + faithfulness gate | M | ← §2 critic engine |
| **S19 release governance** | nothing built (substrate exists) | readiness aggregator + **LLM critic** + autonomy policy + gated publish + UI | L | ← §2 critique engine (**shared**) |
| **S08 editor panels** | canvas done; 6 panels missing | property matrix, restriction builder, namespace mgr, validation console, semantic zoom, true edge bundling | L | ← §1 editing surface |

**Cross-cutting insight:** the two customer asks are not separate from the roadmap —
they _are_ the roadmap, viewed from the demo floor. "Editor operations + multi-select" is the
heart of **S08 + CQ.5**; "agent critiques the curator" is the same **LLM critic** that S19 and
SO.3 need. Building the shared critic once and the editing-op core once serves all of them.

---

## 6. Recommended execution order

**Phase 0 — Bugs & quick wins (days).** High value, low risk, mostly closes open gaps.
- Bug #1 (EG.0): thread `target_ontology_id` into the pipeline so ER/extension enforcement
  runs. _Directly attacks duplicate sprawl._
- Bug #2 / CQ.5: atomic reparent endpoint + wire `EditableLabel` + `ReparentSelect`.
- VCR reverse playback + diff (§6.5) — small, visible.

**Phase 1 — Interactive editing (Stream IE).** The demo ask #1.
- Multi-select on workspace + multi-node menu; manual Merge; **Insert superclass + rehome**;
  bulk reparent. Closes much of S08's _operation_ set (panels can follow).

**Phase 2 — Shared critic (Stream 19 core + CC + SO.3).** The demo ask #2.
- Build the critic engine once (deterministic pre-checks + LLM pros/cons + confidence +
  safety). Use it at **edit-time** (curation critique), **release-time** (readiness), and as
  the **surgeon** repair loop. Then the autonomy policy.

**Phase 3 — Extraction guidance (Stream EG).** The demo ask #2b.
- URI+synonym budgeted base context; business-terms dictionary; advisory governance flag;
  FR-19.4 deterministic-adapter annotations; RS.3 additive enrichment.

**Phase 4 — Simplification (Stream SI).** The standing concern.
- Semantic dedup, superclass abstraction, collapse/prune as proposals; auto-propose after big
  extractions; minimal scheduler for nightly dry-run proposals. **(Gated on you re-sharing the
  simplification process.)**

---

## 7. Answers to your direct questions

- **"Do I need to re-give you the process for iterative refinement?"** — For _belief revision /
  alignment_: no, it's documented (§6.16 / §6.17) and built. For the **simplification** you're
  actually asking about (shrink a 1,700-class extraction): **yes, please share it** — it is
  neither documented nor implemented, and your design should drive FR-6.20 / Stream SI.
- **"Do we need to schedule iterative refinement (e.g., nightly)?"** — Eventually yes, but
  **on-demand + post-extraction-trigger first, nightly second**, and nightly should
  **propose** (dry-run), not auto-apply, until the autonomy dial (Stream 19) exists. There is
  **no scheduler today**; a minimal APScheduler/CronJob is part of Stream SI.
- **"Does providing a starting ontology work?"** — Partially: the prompt injection is real and
  helps on the target-ontology path, but the base path is degraded (label-only vs a "cite the
  URI" instruction), there's no budget, and the structural enforcement no-ops (Bug #1). It
  helps a little; it does not robustly prevent duplicates. Fixing Bug #1 + the base serializer
  is the fastest way to make "starting ontology" and "business terms" actually bite.

---

## 8. PRD-patch checklist (proposed, not applied)

New: **FR-4.16** (editing ops), **FR-4.17** (workspace multi-select), **FR-4.18** (action
critique), **FR-9.16** (business-terms dictionary), **FR-6.20** (single-ontology
simplification). Amend: **FR-4.2/4.12** (reference atomic reparent), **Tier-2 context FR**
(base serializer URI/synonym parity + budgeting), **§6.16 Phase 4** (scheduler unimplemented;
point to FR-6.20), **FR-7.8.11 / Q14e** (advisory governance gate to v1.x). Implementation
plan: add Streams **IE**, **EG**, **SI**, and **CC** (folded into Stream 19) to
`docs/REMAINING_WORK_PLAN.md`.
