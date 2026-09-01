"use client";

import { useEffect, useRef, useMemo, useState, useCallback } from "react";
import Graph from "graphology";
import Sigma from "sigma";
import {
  EdgeArrowProgram,
  EdgeRectangleProgram,
  NodeCircleProgram,
} from "sigma/rendering";
import {
  EdgeCurvedArrowProgram,
  indexParallelEdgesIndex,
} from "@sigma/edge-curve";
import { createNodeBorderProgram } from "@sigma/node-border";
import forceAtlas2 from "graphology-layout-forceatlas2";
import noverlap from "graphology-layout-noverlap";
import { circular } from "graphology-layout";
import pagerank from "graphology-metrics/centrality/pagerank";
import type {
  OntologyClass,
  OntologyEdge,
  CurationStatus,
} from "@/types/curation";
import {
  FILTERED_FROM_CLASS_GRAPH,
  getEdgeType,
  documentKey,
  buildSyntheticRdfsRangeClassEdges,
  RDFS_RANGE_CLASS_LABEL_FALLBACK,
} from "@/components/graph/graphCanvasEdges";
import { ONTOLOGY_EDGE_COLORS as EDGE_COLORS } from "@/components/graph/graphVisualPalette";
import {
  confidenceNodeColor,
  UNMEASURED_CONFIDENCE_COLOR,
  normalizeConfidence01,
} from "@/components/workspace/confidenceLensPalette";
import {
  IMPORTED_NODE_BORDER,
  dimColorForImported,
} from "@/components/workspace/importedEntityStyle";
import type { LensType } from "@/components/workspace/LensToolbar";

/* ── Color palettes ──────────────────────────────────── */

const STATUS_NODE_COLORS: Record<CurationStatus, string> = {
  pending: "#94a3b8",
  approved: "#22c55e",
  rejected: "#ef4444",
};

/** Curation ring colors — only used when the active lens is "curation". */
function statusBorderForClass(cls: OntologyClass): string {
  if (cls.status === "approved") return "#22c55e";
  if (cls.status === "rejected") return "#ef4444";
  return "#f59e0b";
}

/** Neutral outline so semantic/confidence/diff/source lenses are not dominated by curation. */
const NEUTRAL_NODE_BORDER = "#475569";

/**
 * Stream 1 H.15: classes annotated as imported via the effective-graph
 * endpoint render with a slate border + dimmed fill, regardless of the
 * active lens. Visual constants and colour math live in
 * ``importedEntityStyle.ts`` so the box-arrow canvas and the legend agree
 * on the exact same encoding.
 */
function borderColorForLens(lens: LensType, cls: OntologyClass): string {
  if (cls.is_imported) return IMPORTED_NODE_BORDER;
  if (lens === "curation") return statusBorderForClass(cls);
  return NEUTRAL_NODE_BORDER;
}

/** Deterministic layout seed so lens switches do not reshuffle the graph. */
function stableNodePosition(nodeKey: string): { x: number; y: number } {
  let h = 0;
  for (let i = 0; i < nodeKey.length; i++) {
    h = (Math.imul(31, h) + nodeKey.charCodeAt(i)) | 0;
  }
  const u = (h % 1000) / 1000;
  const v = ((h >>> 8) % 1000) / 1000;
  return { x: u * 200 - 100, y: v * 200 - 100 };
}

/** Semantic lens: varied hues by URI hash + bright OWL-type hints (dark canvas). */
function semanticNodeColor(cls: OntologyClass): string {
  const rt = (cls.rdf_type || "").toLowerCase();
  if (rt.includes("objectproperty")) return "#e879f9";
  if (rt.includes("datatype")) return "#7dd3fc";
  if (rt.includes("restriction")) return "#fdba74";
  let h = 0;
  const s = cls.uri || cls._key;
  for (let i = 0; i < s.length; i++) {
    h = (Math.imul(31, h) + s.charCodeAt(i)) | 0;
  }
  const hue = 18 + (Math.abs(h) % 312);
  return `hsl(${hue}, 82%, 70%)`;
}

function effectiveTier(
  cls: OntologyClass,
  ontologyTier: "domain" | "local" | null | undefined,
): string | undefined {
  return cls.tier ?? ontologyTier ?? undefined;
}

function lensNodeColor(
  cls: OntologyClass,
  lens: LensType,
  visibleNodeKeys: Set<string> | null | undefined,
  ontologyTier: "domain" | "local" | null | undefined,
): string {
  switch (lens) {
    case "confidence":
      // Unmeasured is not mid-range. See UNMEASURED_CONFIDENCE_COLOR.
      return cls.confidence == null || Number.isNaN(cls.confidence)
        ? UNMEASURED_CONFIDENCE_COLOR
        : confidenceNodeColor(cls.confidence);
    case "curation":
      return STATUS_NODE_COLORS[cls.status ?? "pending"] ?? "#94a3b8";
    case "diff":
      if (visibleNodeKeys != null && visibleNodeKeys.size > 0) {
        return visibleNodeKeys.has(cls._key) ? "#34d399" : "#475569";
      }
      return semanticNodeColor(cls);
    case "source": {
      const tier = effectiveTier(cls, ontologyTier)?.toLowerCase();
      if (tier === "local") return "#fbbf24";
      if (tier === "domain") return "#2dd4bf";
      return "#94a3b8";
    }
    case "semantic":
    default:
      return semanticNodeColor(cls);
  }
}

function lensNodeSize(
  baseSize: number,
  cls: OntologyClass,
  lens: LensType,
): number {
  if (lens !== "confidence") return baseSize;
  const c = normalizeConfidence01(cls.confidence ?? 0.5);
  const scale = 0.72 + 0.56 * Math.min(1, Math.max(0, c));
  return Math.max(10, Math.min(36, baseSize * scale));
}

function displayNodeLabel(cls: OntologyClass, lens: LensType): string {
  if (lens !== "confidence") return cls.label;
  const pct = Math.round(normalizeConfidence01(cls.confidence ?? 0) * 100);
  return `${cls.label} ${pct}%`;
}

/** Edge label shown on the canvas. In the confidence lens we append a ``%`` so
 *  the lens has visible parity with class nodes (FR-7.8.6 / workspace rule §16,
 *  "edges are first-class"). When the edge has no confidence we leave the base
 *  relation label alone so the label doesn't lie ("0%" would imply we measured
 *  it). The base label falls back to a human-readable version of the edge type
 *  when the LLM didn't supply a relation label. */
function displayEdgeLabel(
  baseLabel: string,
  edgeType: string,
  edgeConfidence: number | null | undefined,
  lens: LensType,
): string {
  const base = baseLabel || edgeType.replace(/_/g, " ");
  if (lens !== "confidence") return base;
  if (edgeConfidence == null || Number.isNaN(edgeConfidence)) return base;
  const pct = Math.round(normalizeConfidence01(edgeConfidence) * 100);
  return `${base} ${pct}%`;
}

function lensEdgeVisual(
  edge: OntologyEdge,
  edgeType: string,
  lens: LensType,
): { color: string; size: number } {
  const fallbackColor = EDGE_COLORS[edgeType] ?? "#94a3b8";
  const baseSize = edgeType === "subclass_of" ? 2.5 : 2;

  if (lens === "confidence") {
    const c = edge.confidence;
    if (c == null || Number.isNaN(c)) {
      return {
        color: fallbackColor,
        size: Math.max(1, baseSize * 0.85),
      };
    }
    return {
      color: confidenceNodeColor(c),
      size: Math.max(1.2, Math.min(5, 1.1 + c * 3.5)),
    };
  }

  if (lens === "curation" && edge.status) {
    const cur: Record<string, string> = {
      approved: "#22c55e",
      rejected: "#ef4444",
      pending: "#f59e0b",
    };
    return {
      color: cur[edge.status] ?? fallbackColor,
      size: baseSize * 1.15,
    };
  }

  return { color: fallbackColor, size: baseSize };
}

/* ── Dark-theme hover label renderer ──────────────────── */

const HOVER_BG = "#1e1e3a";
const HOVER_TEXT = "#e2e8f0";
const HOVER_SHADOW = "rgba(0,0,0,0.6)";

function drawDarkNodeHover(
  context: CanvasRenderingContext2D,
  data: {
    x: number;
    y: number;
    size: number;
    label?: string | null;
    color: string;
  },
  settings: { labelSize: number; labelFont: string; labelWeight: string },
): void {
  const size = settings.labelSize;
  const font = settings.labelFont;
  const weight = settings.labelWeight;
  context.font = `${weight} ${size}px ${font}`;

  context.fillStyle = HOVER_BG;
  context.shadowOffsetX = 0;
  context.shadowOffsetY = 2;
  context.shadowBlur = 10;
  context.shadowColor = HOVER_SHADOW;

  const PADDING = 2;

  if (typeof data.label === "string") {
    const textWidth = context.measureText(data.label).width;
    const boxWidth = Math.round(textWidth + 5);
    const boxHeight = Math.round(size + 2 * PADDING);
    const radius = Math.max(data.size, size / 2) + PADDING;
    const angleRadian = Math.asin(boxHeight / 2 / radius);
    const xDeltaCoord = Math.sqrt(
      Math.abs(Math.pow(radius, 2) - Math.pow(boxHeight / 2, 2)),
    );

    context.beginPath();
    context.moveTo(data.x + xDeltaCoord, data.y + boxHeight / 2);
    context.lineTo(data.x + radius + boxWidth, data.y + boxHeight / 2);
    context.lineTo(data.x + radius + boxWidth, data.y - boxHeight / 2);
    context.lineTo(data.x + xDeltaCoord, data.y - boxHeight / 2);
    context.arc(data.x, data.y, radius, angleRadian, -angleRadian);
    context.closePath();
    context.fill();
  } else {
    context.beginPath();
    context.arc(data.x, data.y, data.size + PADDING, 0, Math.PI * 2);
    context.closePath();
    context.fill();
  }

  context.shadowOffsetX = 0;
  context.shadowOffsetY = 0;
  context.shadowBlur = 0;

  if (typeof data.label === "string") {
    context.fillStyle = HOVER_TEXT;
    context.font = `${weight} ${size}px ${font}`;
    context.fillText(data.label, data.x + data.size + 3, data.y + size / 3);
  }
}

/* ── Props ────────────────────────────────────────────── */

/** Outer ring = `borderColor` (e.g. curation); inner fill = `color` (lens / semantic).
 * A single-border config omits the fill pass and Sigma's shader divides by zero fill count,
 * so `color` never appears — confidence/semantic fills looked grey. */
const NodeBorderProgram = createNodeBorderProgram({
  borders: [
    { size: { value: 0.15 }, color: { attribute: "borderColor" } },
    { size: { fill: true }, color: { attribute: "color" } },
  ],
});

export interface SigmaCanvasProps {
  classes: OntologyClass[];
  edges: OntologyEdge[];
  activeLens: LensType;
  /** Registry tier for the open ontology — classes often omit ``tier`` on each vertex */
  ontologyTier?: "domain" | "local" | null;
  onNodeSelect: (key: string) => void;
  onEdgeSelect: (key: string) => void;
  onContextMenu: (
    e: MouseEvent,
    type: "node" | "edge" | "canvas",
    data?: Record<string, unknown>,
  ) => void;
  /** Called when Sigma is ready or torn down (null on unmount). */
  onViewportApi?: (api: SigmaViewportApi | null) => void;
  /** When set, only nodes in this set are visible (VCR timeline filtering). */
  visibleNodeKeys?: Set<string> | null;
  /** When set, only edges in this set are visible (e.g. confidence-threshold
   *  filtering by ``ConfidenceThresholdSlider``). Combines additively with
   *  ``visibleNodeKeys``: an edge is visible iff both endpoints pass the node
   *  filter **and** its own ``_key`` is in this set. ``null`` disables this
   *  axis (no edge-level filter — every edge whose endpoints are visible is
   *  drawn). */
  visibleEdgeKeys?: Set<string> | null;
  /** Hide ``owl_restriction`` edges without removing them from the graph.
   *  They are toggled through the edge reducer rather than by refetching, so
   *  the canvas never discards its layout and blanks. */
  hideRestrictions?: boolean;
  /** Externally-driven node selection (e.g. sidebar click). Highlighted with a ring. */
  selectedNodeKey?: string | null;
  /** Externally-driven edge selection (e.g. sidebar click). */
  selectedEdgeKey?: string | null;
  /**
   * Focus mode (FR-7.8.15). When set, everything more than ``focusHops`` hops
   * from this node is dimmed — NOT hidden, so surrounding structure still reads
   * as context. ``null`` disables focus entirely.
   *
   * Dimming rather than highlighting is the point: at 667 classes a single
   * highlighted node is one lit circle among hundreds and cannot be found.
   */
  focusNodeKey?: string | null;
  /** Hop radius for {@link focusNodeKey}. ``null`` means "no limit" (show all). */
  focusHops?: number | null;
  /**
   * Additional selected nodes beyond {@link selectedNodeKey} (FR-7.8.18).
   * Rendered with the same ring so a multi-selection reads as one thing.
   */
  multiSelectedKeys?: Set<string> | null;
  /**
   * Shift-click on a node. Adds it to the selection, or removes it if already
   * selected — so a multi-selection can be unpicked without starting over.
   */
  onNodeShiftSelect?: (nodeKey: string) => void;
  /** Click on empty canvas. The way OUT of a selection (FR-7.8.18). */
  onStageClick?: () => void;
  /**
   * Lasso (FR-7.8.18): every node inside the dragged rectangle. Fired once on
   * release. Held modifier + drag, so ordinary panning is unaffected.
   */
  onLassoSelect?: (nodeKeys: string[]) => void;
  /**
   * How many nodes the current focus radius leaves visible, out of the total.
   * Surfaced so the UI can explain why little appears dimmed on a dense graph —
   * 2 hops from a 20-node selection reaches 147 of 160 nodes here.
   */
  onFocusCoverage?: (coverage: { shown: number; total: number } | null) => void;
}

/**
 * Keys within ``hops`` undirected steps of ``origin`` (FR-7.8.15), origin included.
 *
 * Undirected on purpose: a curator tracing "what is this connected to" does not
 * care which way the arrow points. ``hops = null`` means no limit, and returns
 * ``null`` so callers can skip dimming entirely rather than build a set of every
 * node — the difference matters on a 667-node graph.
 *
 * Exported for testing: this is the part worth pinning, and it needs no WebGL.
 */
export function computeFocusSet(
  graph: Graph,
  origins: string | readonly string[],
  hops: number | null,
): Set<string> | null {
  if (hops === null) return null;
  // Multi-origin: a lasso selects many nodes at once, and focus must follow the
  // whole selection. Driving it from a single key meant a lasso turned dimming
  // OFF entirely, because the lasso clears the primary selection.
  const starts = (typeof origins === "string" ? [origins] : origins).filter(
    (o) => graph.hasNode(o),
  );
  if (starts.length === 0) return new Set();

  const seen = new Set<string>(starts);
  let frontier = [...starts];

  for (let depth = 0; depth < hops; depth++) {
    const next: string[] = [];
    for (const node of frontier) {
      graph.forEachNeighbor(node, (neighbor: string) => {
        if (!seen.has(neighbor)) {
          seen.add(neighbor);
          next.push(neighbor);
        }
      });
    }
    if (next.length === 0) break;
    frontier = next;
  }
  return seen;
}

export type FocusCoverage = { shown: number; total: number } | null;

/**
 * Has focus coverage changed in a way worth telling the parent about?
 *
 * Exported for testing: it is the guard that keeps the reducer effect from
 * being its own trigger, and it needs no WebGL to check. See
 * ``reportFocusCoverage`` for why an equal-but-new object is not "changed".
 */
export function focusCoverageChanged(
  prev: FocusCoverage,
  next: FocusCoverage,
): boolean {
  if (prev === next) return false;
  if (!prev || !next) return true;
  return prev.shown !== next.shown || prev.total !== next.total;
}

/* ── Topology graph (lens-independent positions & structure) ── */

/**
 * Build the graphology graph the canvas renders from.
 *
 * Exported for testing: the structural decisions here (which edges are drawn,
 * what their labels say) are worth pinning and need no WebGL to check.
 */
export function buildTopologyGraph(
  classes: OntologyClass[],
  edges: OntologyEdge[],
): Graph {
  const graph = new Graph({ multi: true, type: "directed" });

  const classKeySet = new Set(classes.map((c) => c._key));

  for (const cls of classes) {
    const pos = stableNodePosition(cls._key);
    graph.addNode(cls._key, {
      label: cls.label,
      size: 18,
      baseSize: 18,
      color: "#64748b",
      borderColor: cls.is_imported ? IMPORTED_NODE_BORDER : NEUTRAL_NODE_BORDER,
      type: "bordered",
      x: pos.x,
      y: pos.y,
      confidence: cls.confidence,
      status: cls.status,
      uri: cls.uri,
      description: cls.description,
      // Effective-graph annotation fields (Stream 1 H.12 / H.15). The
      // lens painter reads ``isImported`` to dim the fill and pin the
      // border to the imported colour, regardless of which lens is
      // active; ``sourceOntologyId`` / ``sourceOntologyName`` are
      // forwarded to the right-click handler so the "Open Source
      // Ontology" menu item knows where to deep-link.
      isImported: cls.is_imported === true,
      sourceOntologyId: cls.source_ontology_id ?? null,
      sourceOntologyName: cls.source_ontology_name ?? null,
    });
  }

  const syntheticEdges = buildSyntheticRdfsRangeClassEdges(edges, classKeySet);
  for (const syn of syntheticEdges) {
    const label = syn.label || RDFS_RANGE_CLASS_LABEL_FALLBACK;
    graph.addEdgeWithKey(
      `syn-${syn.edgeKey}`,
      syn.sourceClassKey,
      syn.targetClassKey,
      {
        label,
        // ``baseLabel`` is the lens-independent label; ``label`` is what's
        // currently shown (rewritten by ``paintLensOnGraph`` per active lens).
        baseLabel: label,
        color: EDGE_COLORS.rdfs_range_class,
        size: 2,
        type: "curvedArrow",
        edgeKey: syn.edgeKey,
        edgeType: "rdfs_range_class",
      },
    );
  }

  for (const edge of edges) {
    const edgeType = getEdgeType(edge);
    if (FILTERED_FROM_CLASS_GRAPH.has(edgeType)) continue;
    if (edgeType === "rdfs_range_class") continue;

    const fromKey = documentKey(edge._from);
    const toKey = documentKey(edge._to);
    if (!classKeySet.has(fromKey) || !classKeySet.has(toKey)) continue;
    if (fromKey === toKey) continue;

    const isHierarchy =
      edgeType === "subclass_of" || edgeType === "extends_domain";
    const source = isHierarchy ? fromKey : fromKey;
    const target = isHierarchy ? toKey : toKey;

    // FR-2.20 -- mark hierarchy links the judge rejected. A glyph on the label
    // rather than a colour, so the mark survives every lens: the confidence and
    // curation lenses both repaint edge colour, and a mark that disappears when
    // you switch lens is worse than no mark.
    const flagged = edge.subsumption_flagged === true;
    const rawLabel = edge.label || edgeType.replace(/_/g, " ");
    const displayLabel = flagged ? `\u26A0 ${rawLabel}` : rawLabel;

    const baseEdgeColor = EDGE_COLORS[edgeType] ?? "#94a3b8";
    // An owl:Restriction edge is thinner and quieter than an asserted
    // relation: `allValuesFrom` says "if it has one, it is a System", which
    // does not assert the relation holds at all. Same position on the canvas,
    // deliberately lower visual weight.
    const isRestriction = edgeType === "owl_restriction";
    graph.addEdgeWithKey(edge._key, source, target, {
      label: displayLabel,
      baseLabel: displayLabel,
      color: edge.is_imported
        ? dimColorForImported(baseEdgeColor)
        : baseEdgeColor,
      size: isRestriction ? 1.2 : edgeType === "subclass_of" ? 2.5 : 2,
      type: "curvedArrow",
      restrictionType:
        (edge as unknown as Record<string, unknown>).restriction_type ?? null,
      edgeKey: edge._key,
      edgeType,
      isImported: edge.is_imported === true,
      subsumptionFlagged: flagged,
      sourceOntologyId: edge.source_ontology_id ?? null,
      sourceOntologyName: edge.source_ontology_name ?? null,
    });
  }

  if (graph.order > 0) {
    try {
      pagerank.assign(graph);
    } catch {
      // Very small / degenerate graphs — fall back to degree below
    }
    let minP = Infinity;
    let maxP = -Infinity;
    graph.forEachNode((node) => {
      const p = graph.getNodeAttribute(node, "pagerank") as number | undefined;
      if (typeof p === "number" && !Number.isNaN(p)) {
        minP = Math.min(minP, p);
        maxP = Math.max(maxP, p);
      }
    });
    if (Number.isFinite(minP) && maxP > minP) {
      graph.forEachNode((node) => {
        const p = graph.getNodeAttribute(node, "pagerank") as number;
        const t = (p - minP) / (maxP - minP);
        const baseSize = 12 + t * 18;
        const clamped = Math.max(12, Math.min(30, baseSize));
        graph.setNodeAttribute(node, "baseSize", clamped);
        graph.setNodeAttribute(node, "size", clamped);
      });
    } else {
      graph.forEachNode((node) => {
        const d = graph.degree(node);
        const baseSize = Math.max(12, Math.min(30, 12 + d * 2));
        graph.setNodeAttribute(node, "baseSize", baseSize);
        graph.setNodeAttribute(node, "size", baseSize);
      });
    }
  }

  return graph;
}

function paintLensOnGraph(
  g: Graph,
  classes: OntologyClass[],
  edges: OntologyEdge[],
  lens: LensType,
  visibleNodeKeys: Set<string> | null | undefined,
  ontologyTier: "domain" | "local" | null | undefined,
): void {
  g.forEachNode((node) => {
    const cls = classes.find((c) => c._key === node);
    if (!cls) return;
    const stored = g.getNodeAttribute(node, "baseSize") as number | undefined;
    const baseSize =
      typeof stored === "number" && !Number.isNaN(stored)
        ? stored
        : Math.max(12, Math.min(30, 12 + g.degree(node) * 2));
    const sized = lensNodeSize(baseSize, cls, lens);
    g.setNodeAttribute(node, "size", sized);
    g.setNodeAttribute(node, "label", displayNodeLabel(cls, lens));
    // Imported entities (Stream 1 H.15): dim the lens colour towards
    // slate so the lens identity stays legible while the "not owned by
    // this ontology" signal dominates. Border is also pinned to the
    // imported colour regardless of curation lens. The painter is the
    // single place we ever touch ``color`` / ``borderColor`` after the
    // initial build, so doing the override here covers every lens
    // change without bespoke per-lens branches.
    const rawColor = lensNodeColor(cls, lens, visibleNodeKeys, ontologyTier);
    g.setNodeAttribute(
      node,
      "color",
      cls.is_imported ? dimColorForImported(rawColor) : rawColor,
    );
    g.setNodeAttribute(node, "borderColor", borderColorForLens(lens, cls));
    g.setNodeAttribute(node, "status", cls.status);
  });

  g.forEachEdge((eid) => {
    const attrs = g.getEdgeAttributes(eid);
    const ek = attrs.edgeKey as string | undefined;
    const et = attrs.edgeType as string | undefined;
    if (!ek || !et) return;
    // ``baseLabel`` is whatever was written into the topology graph at build
    // time — the LLM-supplied relation label or the synthetic-edge fallback.
    // We need it for ``displayEdgeLabel`` so the confidence-lens append is
    // consistent with the non-confidence lens.
    const baseLabel =
      (attrs.baseLabel as string | undefined) ?? String(attrs.label ?? "");
    const domainEdge = edges.find((ed) => ed._key === ek);
    if (!domainEdge) {
      const synEdge: OntologyEdge = {
        _key: ek,
        _from: "",
        _to: "",
        type: "rdfs_range_class",
        label: baseLabel,
      };
      const ev = lensEdgeVisual(synEdge, et, lens);
      g.setEdgeAttribute(eid, "color", ev.color);
      g.setEdgeAttribute(eid, "size", ev.size);
      g.setEdgeAttribute(
        eid,
        "label",
        displayEdgeLabel(baseLabel, et, null, lens),
      );
      return;
    }
    const ev = lensEdgeVisual(domainEdge, et, lens);
    g.setEdgeAttribute(
      eid,
      "color",
      domainEdge.is_imported ? dimColorForImported(ev.color) : ev.color,
    );
    g.setEdgeAttribute(eid, "size", ev.size);
    g.setEdgeAttribute(
      eid,
      "label",
      displayEdgeLabel(baseLabel, et, domainEdge.confidence ?? null, lens),
    );
  });
}

/**
 * Reset camera to show the full graph.
 *
 * Sigma v3 with autoRescale (default) normalizes node positions to fit the
 * viewport, so the default camera state {x:0.5, y:0.5, ratio:1} already
 * shows everything. We just need to reset to that default.
 */
function fitCameraToGraph(sigma: Sigma): void {
  sigma.getCamera().setState({ x: 0.5, y: 0.5, ratio: 1, angle: 0 });
  sigma.refresh();
}

function centerCameraOnGraph(sigma: Sigma): void {
  sigma.getCamera().setState({ x: 0.5, y: 0.5, ratio: 1, angle: 0 });
  sigma.refresh();
}

/**
 * Focus-mode dim colours (FR-7.8.15), tuned for the dark canvas (#111118).
 * Low enough to recede, high enough that the graph's shape still reads —
 * hiding out-of-focus nodes would remove the context that makes the
 * neighbourhood meaningful.
 */
const DIMMED_NODE_COLOR = "#2a2a3d";
const DIMMED_EDGE_COLOR = "#1e1e2c";

export type LayoutType = "force" | "circular" | "grid" | "random";
export type EdgeStyleType = "curved" | "straight";

function applyLayout(graph: Graph, layout: LayoutType): void {
  switch (layout) {
    case "circular":
      circular.assign(graph, { scale: 100 });
      break;
    case "grid": {
      const nodes = graph.nodes();
      const cols = Math.ceil(Math.sqrt(nodes.length));
      const spacing = 10;
      nodes.forEach((node, i) => {
        graph.setNodeAttribute(node, "x", (i % cols) * spacing);
        graph.setNodeAttribute(node, "y", Math.floor(i / cols) * spacing);
      });
      break;
    }
    case "random":
      graph.forEachNode((node) => {
        graph.setNodeAttribute(node, "x", Math.random() * 200 - 100);
        graph.setNodeAttribute(node, "y", Math.random() * 200 - 100);
      });
      break;
    case "force":
    default:
      forceAtlas2.assign(graph, {
        iterations: 150,
        settings: {
          gravity: 5,
          scalingRatio: 20,
          strongGravityMode: true,
          barnesHutOptimize: graph.order > 50,
        },
      });
      noverlap.assign(graph, { maxIterations: 50, settings: { ratio: 2 } });
      break;
  }
}

/** Imperative controls for parent (workspace context menu, shortcuts). */
export interface SigmaViewportApi {
  fitAll: () => void;
  centerView: () => void;
  relayout: (layout?: LayoutType) => void;
  setEdgeStyle: (style: EdgeStyleType) => void;
  /** Animate the camera to center on a specific node and highlight it. */
  focusNode: (nodeKey: string) => void;
  /** Animate the camera to center on a specific edge (midpoint of source+target). */
  focusEdge: (edgeKey: string) => void;
  /**
   * Node keys currently within the focus radius (FR-7.8.15), or null when focus
   * is off. Imperative rather than a callback prop so "Hide other nodes"
   * (FR-7.8.17) can read the set on demand without the canvas pushing state
   * upward on every render.
   */
  getFocusSet: () => Set<string> | null;
  /** Every node key the canvas knows about — the denominator for "hide others". */
  getAllNodeKeys: () => string[];
}

/* ── Component ────────────────────────────────────────── */

export default function SigmaCanvas({
  classes,
  edges,
  activeLens,
  ontologyTier = null,
  onNodeSelect,
  onEdgeSelect,
  onContextMenu,
  onViewportApi,
  visibleNodeKeys,
  visibleEdgeKeys,
  selectedNodeKey,
  selectedEdgeKey,
  focusNodeKey,
  focusHops = 1,
  hideRestrictions = false,
  multiSelectedKeys,
  onNodeShiftSelect,
  onStageClick,
  onLassoSelect,
  onFocusCoverage,
}: SigmaCanvasProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const sigmaRef = useRef<Sigma | null>(null);
  const graphRef = useRef<Graph | null>(null);
  const [layoutRunning, setLayoutRunning] = useState(false);
  // Screen-space rectangle while a lasso drag is in progress (FR-7.8.18).
  const [lassoRect, setLassoRect] = useState<{
    x: number;
    y: number;
    w: number;
    h: number;
  } | null>(null);
  // The mouseup handler is bound once, so it cannot close over `lassoRect`
  // state — it would always read the value from first render.
  const lassoRectRef = useRef<{
    x: number;
    y: number;
    w: number;
    h: number;
  } | null>(null);
  lassoRectRef.current = lassoRect;
  const lassoCleanupRef = useRef<(() => void) | null>(null);

  const stableClassesKey = useMemo(
    () =>
      classes
        .map((c) => c._key)
        .sort()
        .join(","),
    [classes],
  );
  const stableEdgesKey = useMemo(
    () =>
      edges
        .map((e) => e._key)
        .sort()
        .join(","),
    [edges],
  );

  const topologySignature = `${stableClassesKey}|${stableEdgesKey}`;
  const lastLaidOutTopologyRef = useRef<string>("");

  const graph = useMemo(
    () => buildTopologyGraph(classes, edges),
    // Rebuild only when vertex/edge keys change — class field updates repaint via paintLensOnGraph.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [stableClassesKey, stableEdgesKey],
  );

  useEffect(() => {
    if (graph.order === 0) return;
    if (lastLaidOutTopologyRef.current === topologySignature) return;
    lastLaidOutTopologyRef.current = topologySignature;
    setLayoutRunning(true);
    try {
      applyLayout(graph, "force");
    } finally {
      setLayoutRunning(false);
    }
  }, [graph, topologySignature]);

  useEffect(() => {
    if (graph.order === 0) return;
    paintLensOnGraph(
      graph,
      classes,
      edges,
      activeLens,
      visibleNodeKeys,
      ontologyTier,
    );
    sigmaRef.current?.refresh();
  }, [graph, classes, edges, activeLens, visibleNodeKeys, ontologyTier]);

  const onNodeSelectRef = useRef(onNodeSelect);
  onNodeSelectRef.current = onNodeSelect;
  const onEdgeSelectRef = useRef(onEdgeSelect);
  onEdgeSelectRef.current = onEdgeSelect;
  const onContextMenuRef = useRef(onContextMenu);
  onContextMenuRef.current = onContextMenu;
  const onNodeShiftSelectRef = useRef(onNodeShiftSelect);
  onNodeShiftSelectRef.current = onNodeShiftSelect;
  const onStageClickRef = useRef(onStageClick);
  onStageClickRef.current = onStageClick;
  const onLassoSelectRef = useRef(onLassoSelect);
  onLassoSelectRef.current = onLassoSelect;
  const onFocusCoverageRef = useRef(onFocusCoverage);
  onFocusCoverageRef.current = onFocusCoverage;
  // Last coverage reported upward. The reducer effect below runs whenever any
  // of seven props changes identity, and the parent turns each report into
  // state -- so reporting an equal-but-new object every run makes the effect
  // its own trigger. See ``reportFocusCoverage``.
  const lastFocusCoverageRef = useRef<FocusCoverage>(null);
  const edgesRef = useRef(edges);
  edgesRef.current = edges;

  useEffect(() => {
    if (!containerRef.current || graph.order === 0) return;
    graphRef.current = graph;

    indexParallelEdgesIndex(graph, {
      edgeIndexAttribute: "parallelIndex",
      edgeMaxIndexAttribute: "parallelMaxIndex",
    });

    const renderer = new Sigma(graph, containerRef.current, {
      renderLabels: true,
      renderEdgeLabels: true,
      labelRenderedSizeThreshold: 6,
      labelColor: { color: "#e2e8f0" },
      labelFont: "Inter, system-ui, sans-serif",
      labelSize: 13,
      edgeLabelColor: { color: "#94a3b8" },
      edgeLabelFont: "Inter, system-ui, sans-serif",
      edgeLabelSize: 10,
      defaultDrawNodeHover: drawDarkNodeHover,
      defaultNodeType: "bordered",
      defaultEdgeType: "curvedArrow",
      stagePadding: 40,
      enableEdgeEvents: true,
      nodeProgramClasses: {
        circle: NodeCircleProgram,
        bordered: NodeBorderProgram,
      },
      edgeProgramClasses: {
        curvedArrow: EdgeCurvedArrowProgram,
        arrow: EdgeArrowProgram,
        line: EdgeRectangleProgram,
      },
    });

    sigmaRef.current = renderer;

    let killed = false;
    let retryCount = 0;
    const MAX_RETRIES = 30;

    const afterLayout = () => {
      if (killed) return;
      renderer.resize();
      const dims = renderer.getDimensions();
      if (dims.width === 0 || dims.height === 0) {
        retryCount++;
        if (retryCount < MAX_RETRIES) {
          setTimeout(afterLayout, 100);
        }
        return;
      }
      renderer.refresh();
      fitCameraToGraph(renderer);
    };
    requestAnimationFrame(() => {
      requestAnimationFrame(afterLayout);
    });

    const resizeObserver =
      typeof ResizeObserver !== "undefined"
        ? new ResizeObserver(() => {
            if (killed) return;
            const el = containerRef.current;
            if (!el || el.offsetWidth === 0 || el.offsetHeight === 0) return;
            renderer.resize();
            renderer.refresh();
          })
        : null;
    resizeObserver?.observe(containerRef.current);

    let hoveredNode: string | null = null;
    let draggedNode: string | null = null;
    let isDragging = false;

    renderer.on("enterNode", ({ node }) => {
      if (killed) return;
      hoveredNode = node;
      renderer.setSetting("labelRenderedSizeThreshold", 0);
      graph.setNodeAttribute(node, "highlighted", true);
      renderer.refresh();
    });

    renderer.on("leaveNode", ({ node }) => {
      if (killed) return;
      hoveredNode = null;
      renderer.setSetting("labelRenderedSizeThreshold", 6);
      graph.setNodeAttribute(node, "highlighted", false);
      renderer.refresh();
    });

    renderer.on("downNode", ({ node, event }) => {
      if ("button" in event.original && event.original.button !== 0) return;
      isDragging = true;
      draggedNode = node;
      graph.setNodeAttribute(node, "highlighted", true);
      renderer.setSetting("enableCameraPanning", false);
    });

    renderer
      .getMouseCaptor()
      .on(
        "mousemovebody",
        (event: { x: number; y: number; preventSigmaDefault?: () => void }) => {
          if (!isDragging || !draggedNode) return;
          const pos = renderer.viewportToGraph({ x: event.x, y: event.y });
          graph.setNodeAttribute(draggedNode, "x", pos.x);
          graph.setNodeAttribute(draggedNode, "y", pos.y);
          event.preventSigmaDefault?.();
        },
      );

    renderer.getMouseCaptor().on("mouseup", () => {
      if (draggedNode) {
        graph.setNodeAttribute(draggedNode, "highlighted", false);
      }
      isDragging = false;
      draggedNode = null;
      renderer.setSetting("enableCameraPanning", true);
    });

    renderer.on("clickNode", ({ node, event }) => {
      if (isDragging) return;
      if (suppressNextClick) {
        suppressNextClick = false;
        return;
      }
      // Shift toggles membership of a multi-selection (FR-7.8.18); a plain
      // click replaces it.
      const ev = event.original as MouseEvent | undefined;
      if (ev?.shiftKey && onNodeShiftSelectRef.current) {
        onNodeShiftSelectRef.current(node);
        return;
      }
      onNodeSelectRef.current(node);
    });

    // Clicking empty canvas clears the selection. Without this the only exit
    // from a selection is to select something else (FR-7.8.18).
    // ── Lasso (FR-7.8.18) ──────────────────────────────────────────────
    // Modifier + drag draws a rectangle and selects every node inside it, for
    // grabbing a cluster no single click can express. Gated on the modifier so
    // ordinary drag-to-pan is untouched, and Sigma's camera is disabled for the
    // duration so the canvas does not pan underneath the rectangle.
    // The component's own container, not renderer.getContainer() — one less
    // renderer API to depend on, and it is already non-null past the guard at
    // the top of this effect. Deliberately NOT an early return: this sits above
    // the remaining handlers and the cleanup, so bailing here would leak the
    // renderer and silently drop clickStage.
    const container = containerRef.current;
    let lassoStart: { x: number; y: number } | null = null;
    let lassoBox: { x: number; y: number; w: number; h: number } | null = null;
    // A completed lasso must not also read as a click.
    //
    // We stopPropagation on mousemove so Sigma cannot pan the camera under
    // the rectangle — but that also starves Sigma's `draggedEvents` counter,
    // so on release it believes the mouse never moved and emits a click.
    // That click landed on empty canvas and ran handleStageClick, wiping the
    // selection the lasso had just made. The symptom was maddening: the
    // selection appeared only when the drag happened to END on a node.
    let suppressNextClick = false;

    // Shift, Alt/Option, Cmd or Ctrl — any of them starts a lasso.
    //
    // Ctrl alone is NOT enough: on macOS Ctrl+click is the secondary click, so
    // the browser fires button 2 and a contextmenu instead of a drag, and the
    // lasso can never begin. Shift and Alt are unmodified on every platform.
    // Left button only, for the same reason.
    const isLassoModifier = (e: MouseEvent) =>
      e.button === 0 && (e.shiftKey || e.altKey || e.metaKey || e.ctrlKey);

    const onMouseDown = (e: MouseEvent) => {
      if (!isLassoModifier(e) || !onLassoSelectRef.current) return;
      const rect = container.getBoundingClientRect();
      lassoStart = { x: e.clientX - rect.left, y: e.clientY - rect.top };
      lassoBox = { x: lassoStart.x, y: lassoStart.y, w: 0, h: 0 };
      setLassoRect(lassoBox);
      renderer.setSetting("enableCameraPanning", false);
      e.preventDefault();
    };

    const onMouseMove = (e: MouseEvent) => {
      if (!lassoStart) return;
      const rect = container.getBoundingClientRect();
      const cx = e.clientX - rect.left;
      const cy = e.clientY - rect.top;
      // The authoritative box is this plain variable, NOT React state. Routing
      // it through state meant mouseup depended on a re-render having committed
      // mid-drag; when it had not, the selection silently did nothing. State is
      // now only for drawing the rectangle.
      // Keep the drag away from Sigma entirely while lassoing.
      e.preventDefault();
      e.stopPropagation();
      lassoBox = {
        x: Math.min(lassoStart.x, cx),
        y: Math.min(lassoStart.y, cy),
        w: Math.abs(cx - lassoStart.x),
        h: Math.abs(cy - lassoStart.y),
      };
      setLassoRect(lassoBox);
    };

    const onMouseUp = () => {
      if (!lassoStart) return;
      const box = lassoBox;
      lassoStart = null;
      lassoBox = null;
      setLassoRect(null);
      renderer.setSetting("enableCameraPanning", true);
      if (!box || box.w < 4 || box.h < 4) return; // a click, not a drag
      suppressNextClick = true;

      // Compare in VIEWPORT space: node positions are graph coordinates, and
      // the rectangle the user drew is on screen. Converting each node forward
      // is correct under any zoom/pan; converting the box back is not, because
      // the projection is not affine under Sigma's camera ratio handling.
      const picked: string[] = [];
      graph.forEachNode((node) => {
        const d = renderer.getNodeDisplayData(node);
        if (!d) return;
        // getNodeDisplayData returns GRAPH coordinates (verified against a live
        // canvas: displayXY === the node's graph x/y). graphToViewport is the
        // transform that lands them in screen pixels; framedGraphToViewport is
        // for already-framed coordinates and returns values orders of magnitude
        // outside the canvas for these inputs — which is why the lasso drew a
        // rectangle and selected nothing.
        const p = renderer.graphToViewport({ x: d.x, y: d.y });
        if (
          p.x >= box.x &&
          p.x <= box.x + box.w &&
          p.y >= box.y &&
          p.y <= box.y + box.h
        ) {
          picked.push(node);
        }
      });
      if (picked.length > 0) onLassoSelectRef.current?.(picked);
    };

    if (container) {
      // CAPTURE phase, and this is load-bearing rather than a style choice.
      //
      // Sigma's MouseCaptor listens for mousemove on `document` and, while the
      // button is down, calls BOTH preventDefault() and stopPropagation() so it
      // can pan the camera (sigma.cjs.dev.js handleMove). A bubble-phase
      // listener on `window` sits AFTER `document` in the bubble path, so every
      // move after the first was swallowed and the lasso rectangle froze a few
      // pixels from where it started — visible, but never growing or selecting.
      //
      // Capture runs window -> document -> target, so we see the event before
      // Sigma can stop it, whatever Sigma does afterwards.
      const CAPTURE = true;
      container.addEventListener("mousedown", onMouseDown, CAPTURE);
      window.addEventListener("mousemove", onMouseMove, CAPTURE);
      window.addEventListener("mouseup", onMouseUp, CAPTURE);
      lassoCleanupRef.current = () => {
        container.removeEventListener("mousedown", onMouseDown, CAPTURE);
        window.removeEventListener("mousemove", onMouseMove, CAPTURE);
        window.removeEventListener("mouseup", onMouseUp, CAPTURE);
      };
    }

    renderer.on("clickStage", ({ event }) => {
      if (isDragging) return;
      if (suppressNextClick) {
        suppressNextClick = false;
        return;
      }
      // A SHIFT-click that misses a node must not wipe the selection. On a
      // dense graph you miss constantly, so clearing here destroyed a
      // painstakingly built multi-selection on a near-miss — which read as
      // "shift-click does not accumulate". Shift means "modify the selection";
      // an unmodified click means "start over".
      const ev = (event as { original?: MouseEvent } | undefined)?.original;
      if (ev?.shiftKey) return;
      onStageClickRef.current?.();
    });

    renderer.on("clickEdge", ({ edge }) => {
      const attrs = graph.getEdgeAttributes(edge);
      onEdgeSelectRef.current(attrs.edgeKey ?? edge);
    });

    renderer.on("rightClickNode", ({ node, event }) => {
      event.original.preventDefault();
      const attrs = graph.getNodeAttributes(node);
      onContextMenuRef.current(event.original as MouseEvent, "node", {
        _key: node,
        label: attrs.label,
        confidence: attrs.confidence,
        status: attrs.status,
        uri: attrs.uri,
        // Effective-graph annotation (Stream 1 H.12 / H.15). The class
        // context menu builder reads ``is_imported`` to switch to the
        // read-only + "Open Source Ontology" inventory; the source
        // fields drive the deep-link target.
        is_imported: attrs.isImported === true,
        source_ontology_id: attrs.sourceOntologyId ?? null,
        source_ontology_name: attrs.sourceOntologyName ?? null,
      });
    });

    renderer.on("rightClickEdge", ({ edge, event }) => {
      event.original.preventDefault();
      const attrs = graph.getEdgeAttributes(edge);
      const ek = (attrs.edgeKey ?? edge) as string;
      const full = edgesRef.current.find((ed) => ed._key === ek);
      onContextMenuRef.current(event.original as MouseEvent, "edge", {
        _key: ek,
        edgeType: attrs.edgeType,
        label: attrs.label,
        status: full?.status,
        is_imported: attrs.isImported === true,
        source_ontology_id: attrs.sourceOntologyId ?? null,
        source_ontology_name: attrs.sourceOntologyName ?? null,
      });
    });

    renderer.on("rightClickStage", ({ event }) => {
      event.original.preventDefault();
      onContextMenuRef.current(event.original as MouseEvent, "canvas");
    });

    return () => {
      killed = true;
      resizeObserver?.disconnect();
      // Window-level lasso listeners outlive the renderer unless removed.
      lassoCleanupRef.current?.();
      lassoCleanupRef.current = null;
      renderer.kill();
      sigmaRef.current = null;
      graphRef.current = null;
    };
  }, [graph]);

  /**
   * Report focus coverage upward, but ONLY when it actually changed.
   *
   * The parent stores this in state, so every call re-renders it. Sending an
   * equal-but-freshly-allocated ``{shown, total}`` on each run therefore
   * guarantees a render, and any parent state that gets recomputed during that
   * render feeds straight back into this effect's dependencies -- an unbounded
   * loop, which React reports as "Maximum update depth exceeded".
   *
   * The ``null`` case never had this problem, because ``Object.is(null, null)``
   * lets React bail out of the update. This restores the same property for the
   * populated case: running the effect N times produces at most one setState.
   */
  const reportFocusCoverage = useCallback((next: FocusCoverage) => {
    if (!focusCoverageChanged(lastFocusCoverageRef.current, next)) return;
    lastFocusCoverageRef.current = next;
    onFocusCoverageRef.current?.(next);
  }, []);

  useEffect(() => {
    const s = sigmaRef.current;
    if (!s) return;
    const hasVisFilter = !!visibleNodeKeys;
    const hasEdgeVisFilter = !!visibleEdgeKeys;
    const hasNodeSel = !!selectedNodeKey;
    const hasEdgeSel = !!selectedEdgeKey;

    // FR-7.8.15 — focus set. Computed once per render, not per node.
    const g = graphRef.current;
    const focusOrigins = [
      ...(focusNodeKey ? [focusNodeKey] : []),
      ...(multiSelectedKeys ?? []),
    ];
    const focusSet =
      focusOrigins.length > 0 && g
        ? computeFocusSet(g, focusOrigins, focusHops ?? null)
        : null;
    // An edge is in focus iff BOTH endpoints are, so a dimmed node never keeps a
    // bright edge dangling off it.
    const inFocus = (key: string) => !focusSet || focusSet.has(key);

    reportFocusCoverage(
      focusSet && g ? { shown: focusSet.size, total: g.order } : null,
    );

    const needsReducer =
      hideRestrictions ||
      hasVisFilter ||
      hasEdgeVisFilter ||
      hasNodeSel ||
      hasEdgeSel ||
      !!focusSet ||
      !!multiSelectedKeys?.size;

    if (!needsReducer) {
      s.setSetting("nodeReducer", null);
      s.setSetting("edgeReducer", null);
    } else {
      s.setSetting(
        "nodeReducer",
        (_node: string, data: Record<string, unknown>) => {
          let d = data;
          if (hasVisFilter && !visibleNodeKeys!.has(_node)) {
            return { ...d, hidden: true };
          }
          // Dim, never hide: the shape of the surrounding graph is the context
          // that makes the focused neighbourhood interpretable.
          // Primary and shift-added selections render identically — a
          // multi-selection should read as one thing, not a hierarchy.
          const isSelected =
            (hasNodeSel && _node === selectedNodeKey) ||
            !!multiSelectedKeys?.has(_node);

          // Selection BEATS dimming. This check used to sit after the dim branch,
          // which returned early — so shift-clicking a node outside the focus
          // radius updated state and rendered nothing, making multi-select look
          // broken. Anything the user explicitly picked must stay visible.
          if (!isSelected && !inFocus(_node)) {
            return { ...d, color: DIMMED_NODE_COLOR, label: "", zIndex: 0 };
          }
          if (isSelected) {
            d = { ...d, highlighted: true, zIndex: 10 };
          }
          return d;
        },
      );
      s.setSetting(
        "edgeReducer",
        (edge: string, data: Record<string, unknown>) => {
          const g = graphRef.current;
          if (!g) return data;
          if (focusSet) {
            // Both endpoints must be in focus, otherwise a bright edge would
            // trail off a dimmed node and read as a live connection.
            if (!inFocus(g.source(edge)) || !inFocus(g.target(edge))) {
              return {
                ...data,
                color: DIMMED_EDGE_COLOR,
                label: "",
                zIndex: 0,
              };
            }
          }
          if (hasVisFilter) {
            const src = g.source(edge);
            const tgt = g.target(edge);
            if (!visibleNodeKeys!.has(src) || !visibleNodeKeys!.has(tgt)) {
              return { ...data, hidden: true };
            }
          }
          // Restrictions toggle WITHOUT rebuilding the graph. Once fetched
          // they live in it permanently; showing and hiding them is a reducer
          // decision, so the canvas never discards its layout and blanks.
          if (hideRestrictions && data.edgeType === "owl_restriction") {
            return { ...data, hidden: true };
          }
          if (hasEdgeVisFilter) {
            const attrs = g.getEdgeAttributes(edge);
            // ``edgeKey`` is the domain key (e.g. ``150170542``); the graphology
            // ``edge`` may differ for synthetic edges (``syn-…`` prefix). The
            // filter is keyed by the domain key the slider observed.
            const ek = (attrs.edgeKey ?? edge) as string;
            if (!visibleEdgeKeys!.has(ek)) {
              return { ...data, hidden: true };
            }
          }
          if (hasEdgeSel) {
            const attrs = g.getEdgeAttributes(edge);
            if ((attrs.edgeKey ?? edge) === selectedEdgeKey) {
              return {
                ...data,
                size: ((data.size as number) ?? 2) + 2,
                color: "#818cf8",
                zIndex: 10,
              };
            }
          }
          return data;
        },
      );
    }
    s.refresh();
  }, [
    visibleNodeKeys,
    visibleEdgeKeys,
    selectedNodeKey,
    selectedEdgeKey,
    focusNodeKey,
    focusHops,
    multiSelectedKeys,
    hideRestrictions,
    reportFocusCoverage,
  ]);

  const handleRelayout = useCallback((layout: LayoutType = "force") => {
    if (!graphRef.current || !sigmaRef.current) return;
    setLayoutRunning(true);
    try {
      applyLayout(graphRef.current, layout);
      sigmaRef.current.resize();
      sigmaRef.current.refresh();
      fitCameraToGraph(sigmaRef.current);
    } finally {
      setLayoutRunning(false);
    }
  }, []);

  const fitAll = useCallback(() => {
    const s = sigmaRef.current;
    if (!s) return;
    s.resize();
    s.refresh();
    fitCameraToGraph(s);
  }, []);

  const centerView = useCallback(() => {
    const s = sigmaRef.current;
    if (!s) return;
    centerCameraOnGraph(s);
  }, []);

  const setEdgeStyle = useCallback((style: EdgeStyleType) => {
    const g = graphRef.current;
    const s = sigmaRef.current;
    if (!g || !s) return;
    const edgeType = style === "curved" ? "curvedArrow" : "arrow";
    g.forEachEdge((edge) => {
      g.setEdgeAttribute(edge, "type", edgeType);
    });
    s.refresh();
  }, []);

  const focusNode = useCallback((nodeKey: string) => {
    const g = graphRef.current;
    const s = sigmaRef.current;
    if (!g || !s || !g.hasNode(nodeKey)) return;

    const nodeAttrs = g.getNodeAttributes(nodeKey);

    // Compute bounding box of all visible nodes in raw graph coordinates
    let minX = Infinity;
    let maxX = -Infinity;
    let minY = Infinity;
    let maxY = -Infinity;
    g.forEachNode((_n, a) => {
      if (a.hidden) return;
      const ax = a.x as number;
      const ay = a.y as number;
      if (ax < minX) minX = ax;
      if (ax > maxX) maxX = ax;
      if (ay < minY) minY = ay;
      if (ay > maxY) maxY = ay;
    });
    if (!isFinite(minX)) return;

    // Sigma with autoRescale normalizes the bounding box to [0, 1] camera space.
    // Camera {x: 0.5, y: 0.5, ratio: 1} shows the full graph centered.
    const rangeX = maxX - minX || 1;
    const rangeY = maxY - minY || 1;
    const x = (nodeAttrs.x - minX) / rangeX;
    const y = (nodeAttrs.y - minY) / rangeY;

    if (!isFinite(x) || !isFinite(y)) return;

    s.getCamera().animate({ x, y, ratio: 0.35, angle: 0 }, { duration: 300 });
  }, []);

  const focusEdge = useCallback((edgeKey: string) => {
    const g = graphRef.current;
    const s = sigmaRef.current;
    if (!g || !s) return;

    // Find the graphology edge whose edgeKey attribute matches
    let graphEdgeId: string | null = null;
    g.forEachEdge((eid, attrs) => {
      if (attrs.edgeKey === edgeKey || eid === edgeKey) {
        graphEdgeId = eid;
      }
    });
    if (!graphEdgeId) return;

    const srcKey = g.source(graphEdgeId);
    const tgtKey = g.target(graphEdgeId);
    const srcAttrs = g.getNodeAttributes(srcKey);
    const tgtAttrs = g.getNodeAttributes(tgtKey);

    // Center on the midpoint of the two endpoint nodes
    let minX = Infinity;
    let maxX = -Infinity;
    let minY = Infinity;
    let maxY = -Infinity;
    g.forEachNode((_n, a) => {
      if (a.hidden) return;
      const ax = a.x as number;
      const ay = a.y as number;
      if (ax < minX) minX = ax;
      if (ax > maxX) maxX = ax;
      if (ay < minY) minY = ay;
      if (ay > maxY) maxY = ay;
    });
    if (!isFinite(minX)) return;

    const rangeX = maxX - minX || 1;
    const rangeY = maxY - minY || 1;
    const midGraphX = (srcAttrs.x + tgtAttrs.x) / 2;
    const midGraphY = (srcAttrs.y + tgtAttrs.y) / 2;
    const x = (midGraphX - minX) / rangeX;
    const y = (midGraphY - minY) / rangeY;

    if (!isFinite(x) || !isFinite(y)) return;

    s.getCamera().animate({ x, y, ratio: 0.35, angle: 0 }, { duration: 300 });
  }, []);

  const getFocusSet = useCallback((): Set<string> | null => {
    const g = graphRef.current;
    const origins = [
      ...(focusNodeKey ? [focusNodeKey] : []),
      ...(multiSelectedKeys ?? []),
    ];
    if (!g || origins.length === 0) return null;
    return computeFocusSet(g, origins, focusHops ?? null);
  }, [focusNodeKey, focusHops, multiSelectedKeys]);

  const getAllNodeKeys = useCallback((): string[] => {
    const g = graphRef.current;
    return g ? g.nodes() : [];
  }, []);

  useEffect(() => {
    if (!onViewportApi) return;
    const api: SigmaViewportApi = {
      fitAll,
      centerView,
      relayout: handleRelayout,
      setEdgeStyle,
      focusNode,
      focusEdge,
      getFocusSet,
      getAllNodeKeys,
    };
    onViewportApi(api);
    return () => {
      onViewportApi(null);
    };
  }, [
    onViewportApi,
    fitAll,
    centerView,
    handleRelayout,
    setEdgeStyle,
    focusNode,
    focusEdge,
    getFocusSet,
    getAllNodeKeys,
  ]);

  if (classes.length === 0) {
    return (
      <div
        className="flex items-center justify-center h-full text-gray-500"
        data-testid="sigma-empty"
      >
        <div className="text-center">
          <p className="text-lg">No ontology data available</p>
          <p className="text-sm mt-1 text-gray-400">
            The staging graph is empty or still loading.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div
      data-testid="sigma-canvas"
      style={{
        width: "100%",
        height: "100%",
        position: "relative",
        background: "#111118",
        overflow: "hidden",
      }}
    >
      {/* Lasso rectangle (FR-7.8.18). pointer-events-none so the drag it is
          drawn for keeps reaching the canvas underneath. */}
      {lassoRect && (
        <div
          data-testid="lasso-rect"
          className="absolute z-30 pointer-events-none border-2 border-dashed border-indigo-300 bg-indigo-400/20"
          style={{
            left: lassoRect.x,
            top: lassoRect.y,
            width: lassoRect.w,
            height: lassoRect.h,
          }}
        />
      )}
      {layoutRunning && (
        <div className="absolute inset-0 z-10 flex items-center justify-center bg-[#1a1a2e]/60 backdrop-blur-sm">
          <div className="flex flex-col items-center gap-3">
            <div className="animate-spin h-10 w-10 border-3 border-indigo-400 border-t-transparent rounded-full" />
            <p className="text-sm text-gray-300">Computing layout…</p>
          </div>
        </div>
      )}
      {/* Node/edge count — subtle top-left overlay */}
      <div className="absolute bottom-2 right-2 z-20 text-[10px] text-gray-600 pointer-events-none">
        {graph.order} nodes &middot; {graph.size} edges
      </div>
      <div
        ref={containerRef}
        style={{
          width: "100%",
          height: "100%",
          position: "relative",
        }}
      />
    </div>
  );
}
