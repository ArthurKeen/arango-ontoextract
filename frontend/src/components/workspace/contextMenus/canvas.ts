/**
 * Canvas context-menu builder.
 *
 * Right-click on empty canvas space (no node, no edge selected). Mirrors
 * ``ui-architecture.mdc`` §6 — three independent axes (lens / graph style /
 * layout) all live in this menu, never as a competing top-level switcher:
 *
 *   View As (lens)            — semantic / confidence / curation / diff / source
 *   Graph Style               — Network (circles) / Box & Arrow (UML)
 *   Layout (network only)     — Force-Directed / Circular / Grid / Random
 *   Edge Style (network only) — Curved / Straight
 *   Fit All Nodes
 *   Center View
 *   New Ontology…
 *   Browse Standard Catalog…
 *   Review Feedback Learning
 *
 * Crucially: a lens change must NEVER relayout (§14). Layout changes always
 * relayout. Graph-style geometry changes may force a relayout. The builder
 * only routes the user's intent to the matching ``viewportApi`` method;
 * preserving the lens-stable-layout invariant is the canvas component's
 * responsibility.
 */

import type { ContextMenuItem } from "@/components/workspace/ContextMenu";
import type { LensType } from "@/components/workspace/LensToolbar";

import type { WorkspaceContextMenuActions } from "./types";

/** Lens picker items rendered under the "View As" submenu. Kept here (not
 *  in the page) because the canvas menu is the only consumer per
 *  ``ui-architecture.mdc`` §6 — the toolbar uses its own LensType list. */
export const LENS_OPTIONS: { id: LensType; label: string }[] = [
  { id: "semantic", label: "Semantic" },
  { id: "confidence", label: "Confidence" },
  { id: "curation", label: "Curation Status" },
  { id: "diff", label: "Diff (vs timeline)" },
  { id: "source", label: "Source Type" },
];

export function buildCanvasContextMenu(
  _data: Record<string, unknown>,
  actions: WorkspaceContextMenuActions,
): ContextMenuItem[] {
  // Empty canvas (no ontology loaded) — opened from the empty state or the
  // "Ontologies" asset group. The view/layout/fit knobs have no graph to act
  // on, so show only the ontology-level actions (New Ontology…, Extract…, …).
  const empty = Boolean((_data as { empty?: boolean } | undefined)?.empty);

  const items: ContextMenuItem[] = [];

  if (!empty) {
    items.push(
      {
        label: "View As",
        icon: "👁",
        submenu: LENS_OPTIONS.map((opt) => ({
          label: opt.label,
          checked: actions.activeLens === opt.id,
          onClick: () => actions.setActiveLens(opt.id),
        })),
      },
      {
        label: "Graph Style",
        icon: "📐",
        submenu: [
          {
            label: "Network (circles)",
            checked: actions.graphViewMode === "network",
            onClick: () => actions.setGraphViewMode("network"),
          },
          {
            label: "Box & Arrow (UML)",
            checked: actions.graphViewMode === "box-arrow",
            onClick: () => actions.setGraphViewMode("box-arrow"),
          },
        ],
      },
    );

    // Layout / Edge Style only make sense for the Network (Sigma) renderer;
    // Box & Arrow uses an explicit dagre-style layout that doesn't expose the
    // same knobs.
    if (actions.graphViewMode === "network") {
      items.push(
        {
          // FR-7.8.15 — dims everything beyond N hops of the selected node.
          // Network-only: the Box & Arrow renderer has no dimming pass, so
          // offering the control there would be a no-op with a checkmark.
          label: "Focus",
          icon: "🎯",
          submenu: [
            { hops: 1 as number | null, label: "1 hop" },
            { hops: 2 as number | null, label: "2 hops" },
            { hops: 3 as number | null, label: "3 hops" },
            { hops: null as number | null, label: "Show all (off)" },
          ].map((opt) => ({
            label: opt.label,
            checked: actions.focusHops === opt.hops,
            onClick: () => actions.setFocusHops(opt.hops),
          })),
        },
        {
          label: "Layout",
          icon: "🔄",
          submenu: [
            { label: "Force-Directed", onClick: () => actions.relayout("force") },
            { label: "Circular", onClick: () => actions.relayout("circular") },
            { label: "Grid", onClick: () => actions.relayout("grid") },
            { label: "Random", onClick: () => actions.relayout("random") },
          ],
        },
        {
          label: "Edge Style",
          icon: "〰",
          submenu: [
            { label: "Curved", onClick: () => actions.setEdgeStyle("curved") },
            { label: "Straight", onClick: () => actions.setEdgeStyle("straight") },
          ],
        },
      );
    }

    items.push(
      { label: "separator1", separator: true },
      {
        label: "Fit All Nodes",
        icon: "⬜",
        onClick: () => {
          actions.closeContextMenu();
          actions.fitAllNodes();
        },
      },
      {
        label: "Center View",
        icon: "🎯",
        onClick: () => {
          actions.closeContextMenu();
          actions.centerView();
        },
      },
      { label: "sep-new-ont", separator: true },
    );
  }

  items.push(
    {
      label: "New Ontology…",
      icon: "➕",
      onClick: () => actions.setShowCreateOntology(true),
    },
    {
      label: "Browse Standard Catalog…",
      icon: "📚",
      onClick: () => actions.setShowCatalogBrowser(true),
    },
    {
      label: "Extract from ArangoDB…",
      icon: "🗄",
      onClick: () => actions.setShowSchemaExtraction(true),
    },
    {
      label: "Extract from Relational DB…",
      icon: "🗄",
      onClick: () => actions.setShowRelationalExtraction(true),
    },
    {
      label: "Review Feedback Learning",
      icon: "📊",
      onClick: () =>
        actions.setFeedbackLearning({ ontologyId: null, ontologyName: null }),
    },
  );

  // Show Pending Revisions only when an ontology is loaded -- otherwise
  // there's no inbox to show.
  if (actions.selectedOntologyId) {
    items.push({
      label: "Show Pending Revisions",
      icon: "📨",
      onClick: () => {
        const ontKey = actions.selectedOntologyId;
        if (!ontKey) return;
        actions.setRevisionsInbox({ key: ontKey, name: ontKey });
      },
    });
    // Stream 2: ER (entity resolution) on the open ontology.
    // Triggers a full pipeline run + opens an overlay listing the
    // candidate duplicate pairs. Same overlay-not-route rule (§9)
    // and same per-ontology gating as the revisions inbox above --
    // ER has nothing to run on if no ontology is open.
    items.push({
      label: "Find Duplicates…",
      icon: "🔍",
      onClick: () => {
        const ontKey = actions.selectedOntologyId;
        if (!ontKey) return;
        actions.setMergeCandidates({ key: ontKey, name: ontKey });
      },
    });
    // Stream 20 AL-PR5: align the open ontology with other library ontologies
    // into a reconciled master (overlay-not-route, §9; per-ontology gated).
    items.push({
      label: "Align Ontologies…",
      icon: "🔗",
      onClick: () => {
        const ontKey = actions.selectedOntologyId;
        if (!ontKey) return;
        actions.setAlignmentReview({ key: ontKey, name: ontKey });
      },
    });
    items.push({
      label: "Compare Schema Evolution…",
      icon: "📊",
      onClick: () => {
        const ontKey = actions.selectedOntologyId;
        if (!ontKey) return;
        actions.setSchemaDiffOverlay({
          key: ontKey,
          name: actions.selectedOntologyName ?? ontKey,
        });
      },
    });
  }

  return items;
}
