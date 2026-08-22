# Frontend agent guide

Scope: `frontend/`. Read alongside the repo-root `AGENTS.md`, which carries the
general engineering rules (read-before-write, test-what-you-touch,
verify-before-done, wiring-over-deletion, …).

Mirrored from `.cursor/rules/ui-architecture.mdc`,
`.cursor/rules/arango-frontend-rules.mdc` and the Jest half of
`.cursor/rules/mock-fidelity.mdc`, because Cursor reads `.cursor/rules/` and
Claude Code reads `AGENTS.md`. **Both copies are tracked — change a rule in both.**

## Verification

Before claiming any frontend change is done:

```bash
npx tsc --noEmit -p frontend/tsconfig.json   # types
npm --prefix frontend run lint               # eslint
npm --prefix frontend test                   # jest
```

## Jest mock fidelity

The general rule is in the root `AGENTS.md`; these are the mechanics.

`jest.mock(...)` is hoisted above imports, so this is correct and sufficient:

```typescript
jest.mock("@/lib/api-client", () => ({ ApiError: class extends Error {} }));
import { ApiError } from "@/lib/api-client";  // resolves to the mock
```

If you reach for any of the following, stop — each is a workaround for hoisting
that hides a real problem:

| Anti-pattern | Why it's wrong |
| --- | --- |
| `const { X } = require("@/lib/...")` after `jest.mock(...)` | Hoisting already handled it; `require` is dead weight |
| `// eslint-disable-next-line @typescript-eslint/no-require-imports` | Silencing the rule that exists to catch exactly this |
| `// @ts-ignore` on a mocked import | Type the mock properly; `ts-ignore` hides the real bug |
| Defining the mock class *outside* the `jest.mock` factory | Causes "Cannot access 'X' before initialization" — move the class **inside** the factory rather than `require`-ing it back out |

The fix is always: define the mock class inside the factory, then take a typed
reference with a normal top-level import.

## UI architecture — object-centric workspace

Applies to `frontend/src/components/**` and `frontend/src/app/**`.

The workspace is **one persistent stage**: users stay on the graph and act on
*objects* (classes, edges, properties, documents, ontologies, runs, pipeline
steps). Features are capabilities on those objects, never new destinations. Two
failure modes must never happen: the user asking *"where am I?"* (navigation
disorientation), or *"what does this colour/size mean?"* with no in-UI answer
(encoding ambiguity).

### Interaction contract

**Left-click selects, right-click acts.** This underpins every other rule.

| Gesture | Meaning | Surface |
| --- | --- | --- |
| Left-click an entity | Select + open read-only detail | `FloatingDetailPanel` (canvas) / `AssetInfoPanel` (explorer) |
| Right-click an entity or canvas | Open a menu of **actions** | `ContextMenu` |
| Drag explorer ↔ canvas | Extraction / reparenting / import | Drop zones |
| Keyboard accelerator (1–5, Esc) | Shortcut for frequent menu items | `window` listener when focus is not in an input |

Never attach a mutation to left-click — no "click to approve", no "click to
delete". Read-only selection must be safe.

### Structure

1. **No new routes for workspace workflows.** Everything object-centric lives in
   `/workspace`. Exempt: `/login`, `/logout`, `/api/*` handlers, framework auth
   and error shells. Legacy routes (`/curation`, `/dashboard`, `/library`,
   `/ontology/[id]`, `/pipeline`, `/quality`, `/upload`, `/entity-resolution`)
   predate this rule — don't link to them from new code, don't extend them, plan
   migration to overlays; removing one beats growing one. Deep-link with query
   params on `/workspace` (`?ontologyId=…&runId=…&lens=confidence`) read via
   `useSearchParams()`.
2. **Context menus are the primary path**, not button panels. Toolbars may
   duplicate a subset for discoverability but must never be the only route to an
   action.
3. **Context over navigation** — update selection plus a floating panel rather
   than routing.
4. **Canvas content is object-driven, not mode-driven.** Ontology → graph canvas;
   Run → pipeline DAG + metrics; nothing selected → `EmptyCanvasState`. Swapping is
   an object swap, not navigation. A global edit-vs-view mode is forbidden.
5. **Drag and drop over multi-step wizards** (document → canvas to extract,
   class → class to reparent, ontology → ontology to import).
6. **Persistent zones, resizable, never collapsed.** Left = asset explorer,
   centre = canvas, bottom = VCR/timeline when an ontology is open. Users tune
   widths; do not add "hide sidebar" toggles.
7. **Overlay panels, not pages.** Detail, provenance, quality and dialogs render
   as children of the workspace page, opened from context-menu actions.
8. **Coordinate simultaneous panels.** Two panels open at once must use distinct
   placements via `useDraggablePanel(width, { placement })` —
   `viewportTopRight` for entity details, `mainColumnTopLeft` for asset info.
   Same-placement overlays offset with `stackIndex` (0, 1, 2…). All panels are
   draggable by `PanelDragGrip` and dismissable with Esc or `×`.
9. **Links leave the workspace only.** `<Link>` to `/`, `/login`, `/logout` is
   fine; a `<Link>` that starts an object workflow is forbidden — use a
   context-menu action or a query-param deep link.

### Lens, graph style and layout are three different axes

All three live in the canvas context menu; none belongs in a toolbar as the
primary path.

| Axis | Changes | May relayout? | Where |
| --- | --- | --- | --- |
| **Lens** | Paint (colour, ring, size from the same `baseSize`) | **Never** | Canvas menu → "View As" + keys 1–5 |
| **Graph style** | Node/edge geometry (circle vs UML box, straight vs curved) | Sometimes | Canvas menu → "Graph Style" |
| **Layout** | Node positions (force / circular / grid / random) | Always | Canvas menu → "Layout" |

The active lens shows as a subtle header indicator (e.g. "(Semantic view)"),
never a competing top-level switcher.

**A lens change paints; it never relayouts.** It must preserve the topology
fingerprint — the node and edge key sets must be identical before and after, and
positions of surviving nodes unchanged. This is testable: assert it in any new
canvas implementation. Topology changes (timeline-filtered subgraphs, new
extraction results) *may* relayout — that's a data change. The temporal/diff lens
is the exception that proves the rule: scrubbing the VCR changes which entities
exist, so the legend must distinguish "lens change (stable layout)" from "scrub
(different subgraph)".

### Every encoding is legible in-UI

`CanvasLensLegend` must document, per lens: what node colour and node border/ring
mean; what edge colour and weight mean where used; what node size means —
explicitly, saying whether it is structural (PageRank, degree) or tied to an
attribute; and any fallback chain for missing fields ("per-class tier when
present; otherwise the ontology's library tier; grey = neither"). Users assume
"big = important" and "bright = bad" unless told otherwise, so spell out every
convention. No implicit metaphors.

### Objects and data parity

- **Edges are first-class.** Selection, detail panel, context actions, API
  mutations and legend rules that apply to nodes apply to edges. Don't ship class
  curation without a plan for edge curation where edges carry review state.
- **Optimistic curation via a shared helper.** Approve/reject updates local graph
  state immediately and rolls back (or refreshes) on API failure. Do not
  reimplement per entity kind in `page.tsx` — use or create a shared hook taking
  `{ entityKind, ontologyId, onRollback }` and returning `{ approve, reject }`.
- **Destructive actions never use native dialogs.** `window.confirm`,
  `window.alert` and `window.prompt` are forbidden anywhere, no exceptions.
  *Reversible* destructive actions (delete class, reject, remove import) act
  immediately with `danger: true` styling plus an **undo toast** —
  undo-over-confirm is the default. *Irreversible* ones (delete ontology, release
  a version, delete a run) use a dedicated confirmation **overlay** with a typed
  name or explicit Confirm. Be consistent: if delete-class confirms, so must
  delete-edge and delete-ontology.

### Discoverability and accessibility

Keyboard accelerators accelerate, they don't replace the menu — every shortcut
must also be reachable from a context menu. Existing: `1`–`5` (lens), `Esc`
(close menu/panel). Document new ones in a tooltip or "?" overlay, not a
permanent key legend.

Context-menu-primary is genuinely hard to discover, so mitigate explicitly. All
of these may coexist: one-line empty states ("Right-click on canvas for more
options"), legend copy telling users to right-click, a first-run toast or tour,
and a single discreet "?" overlay kept out of the primary action path. A
permanent wall of toolbar buttons duplicating every action is **not** allowed —
it trains users to ignore the menu.

### Engineering patterns

**Context-menu builders are colocated by entity.** Each entity type's builder
lives in `frontend/src/components/workspace/contextMenus/<entity>.ts` and exports
`build<Entity>ContextMenu(args): ContextMenuItem[]`. The workspace page wires the
selected type to its builder, passing handlers as arguments. When adding an entity
type, create its builder there — do not extend the historical single switch in
`page.tsx`. This is what keeps `page.tsx` under the 1500-line cap.

**Every new entity type ships with all six of these:**

| Required | Where |
| --- | --- |
| Left-click selection handler | `page.tsx` (or wherever the canvas/explorer is wired) |
| Read-only detail panel | `FloatingDetailPanel` extension or dedicated component |
| Right-click context-menu builder | `workspace/contextMenus/<entity>.ts` |
| Legend entry for every lens it appears in | `CanvasLensLegend` |
| Optimistic curation (if curable) | Shared helper, not duplicated |
| Test: menu items render and fire handlers | `__tests__/` beside the source |

Shipping without all six is an incomplete feature.

**Canonical icons per action verb** — reuse these; do not invent a new icon for a
verb that already has one.

| Verb | Icon | Verb | Icon |
| --- | --- | --- | --- |
| View / inspect | 🔍 | Copy | 📋 |
| View info | ℹ️ | Edit / rename | ✏️ |
| View history | 📜 | Retry | 🔄 |
| View provenance / imports | 🔗 | Open in canvas | 🔷 |
| View data / report | 📊 | Pipeline / metrics | ⚡ |
| Approve | ✅ | Export | 📤 |
| Reject | ❌ | Release / publish | 🚀 |
| Delete | 🗑️ | Fit / frame | ⬜ |
| Center | 🎯 | Layout | 🔄 |
| Edge style | 〰 | Graph style | 📐 |
| View As (lens) | 👁 | Add / new | ➕ |

Submenus collapse into `▸`; radio-style submenu items show `✓` in place of the
icon (`ContextMenu.tsx` handles this).

### Anti-patterns

New routes for workflows that could be overlays · `<Link>` as the primary path for
canvas-adjacent tasks · multi-step page wizards where DnD + panel would do ·
toolbar-only actions with no context-menu path · left-click triggering a mutation ·
a global edit-vs-view mode · a side panel that *replaces* the canvas · a lens
change that re-runs layout without a topology change · colours or sizes meaning
different things per lens without legend text saying so · `window.confirm` /
`alert` / `prompt` anywhere · a growing single-switch menu builder in `page.tsx` ·
two overlays at the same placement without `stackIndex` · inventing an icon for a
verb that already has a canonical one.

## Arango UI design rules

All interfaces must match the ArangoDB web platform (Agentic AI Suite, chat,
GraphRAG). Do not introduce shades outside these groups.

### Brand and hierarchy
Clean and professional with generous white space. Arango Green is the action
colour (primary buttons, links, checkmarks, active/selected states). Dark gray
text on white in content areas. The side menu is solid black with white icons and
labels. Red is for errors and deletions only, used sparingly.

### Typography
**Inter** globally — no decorative fonts. Headings semi-bold and clearly larger
than body text; body text regular. A simple monospace (e.g. Courier) for code,
technical blocks and inline variables.

### Colour

Greens — primary and actions:

| Name | Value | Usage |
| --- | --- | --- |
| Light green background | `#f4fef2` | Selected tabs, chips, pills |
| Arango green (main) | `#006532` | Primary buttons, checkmarks, links, active states |
| Dark green hover | `#005329` | Hover on primary green buttons |
| Brand green | `#007339` | Logo representations and charts |

Grays — text and layout:

| Name | Value | Usage |
| --- | --- | --- |
| Page background | `#ffffff` | Main content background |
| Light gray background | `#f8f8f8` | Panels, tables, code blocks |
| Borders | `#e5e5e5` | Subtle separators |
| Body text | `#282828` | Paragraphs, labels, standard text |
| Muted text | `#9a9a9a` | Helper text, hints, secondary info |

Interface specifics:

| Name | Value | Usage |
| --- | --- | --- |
| Error / delete | `#da1a20` | Error messages, destructive buttons |
| Left menu | `#000000` | Narrow sidebar background |
| Menu hover | white @ 15–20% opacity | Side-menu hover highlight |

### Brand assets
**Avocado icon** — the square mark only, used in the narrow left side menu or as
the app icon. **Full logo** — Avocado plus the "ArangoDB" wordmark in dark text,
only on white or pale pages.

### Screen patterns

**Home / AI Suite landing** — white or soft background image; title must read
exactly `"Arango Agentic AI Suite"`; clean cards with short feature descriptions
and prominent Arango Green `"Run"` buttons.

**Chat interfaces (GraphRAG, Ada, …)** — white chat canvas; text input bounded by
thin gray borders; Arango Green for send and success elements; responses rendered
as clean markdown with headings, bullets and light-gray code boxes.

**Forms and settings** — clean white background; readable dark-gray descriptive
labels above or beside inputs; a primary Arango Green confirm button alongside a
secondary gray cancel.

**Data visualisations and graphs** — light gray workspace canvas; Arango Green
accents for selected nodes and paths; nodes and text labels must stay legible
against the canvas.
