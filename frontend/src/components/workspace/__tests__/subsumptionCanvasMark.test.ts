/**
 * Canvas mark for flagged hierarchy links (PRD §6.2 FR-2.20).
 *
 * The judge's flags are only useful if a curator can see them where they are
 * looking, which is the canvas. The mark is a glyph on the edge label rather
 * than a colour, because the confidence and curation lenses both repaint edge
 * colour and a mark that vanishes when you switch lens is worse than none.
 */

// SigmaCanvas pulls in WebGL programs at import; JSDOM has no WebGL, so the
// rendering modules are stubbed exactly as computeFocusSet.test.ts does. The
// function under test touches none of them.
jest.mock("sigma/rendering", () => ({
  __esModule: true,
  NodeCircleProgram: class {},
  EdgeArrowProgram: class {},
  EdgeRectangleProgram: class {},
}));
jest.mock("@sigma/edge-curve", () => ({
  __esModule: true,
  EdgeCurvedArrowProgram: class {},
  indexParallelEdgesIndex: () => {},
}));
jest.mock("@sigma/node-border", () => ({
  __esModule: true,
  createNodeBorderProgram: () => class {},
}));
jest.mock("sigma", () => ({
  __esModule: true,
  default: class MockSigma {},
}));

import { buildTopologyGraph } from "../SigmaCanvas";
import type { OntologyClass, OntologyEdge } from "@/types/curation";

const WARNING = "⚠";

function cls(key: string, label: string): OntologyClass {
  return {
    _key: key,
    uri: `http://x#${key}`,
    label,
    description: "",
    confidence: 0.9,
    status: "pending",
    ontology_id: "o1",
    created: "",
    expired: null,
  } as OntologyClass;
}

function edge(
  key: string,
  from: string,
  to: string,
  flagged?: boolean,
): OntologyEdge {
  return {
    _key: key,
    _from: `ontology_classes/${from}`,
    _to: `ontology_classes/${to}`,
    type: "subclass_of",
    label: "subclass of",
    ...(flagged === undefined ? {} : { subsumption_flagged: flagged }),
  } as OntologyEdge;
}

const CLASSES = [
  cls("Tyre", "Tyre"),
  cls("Vehicle", "Vehicle"),
  cls("WinterTyre", "Winter Tyre"),
];

describe("flagged subclass edges on the canvas", () => {
  it("marks an edge the judge rejected", () => {
    const g = buildTopologyGraph(CLASSES, [
      edge("e1", "Tyre", "Vehicle", true),
    ]);
    expect(g.getEdgeAttribute("e1", "label")).toContain(WARNING);
    expect(g.getEdgeAttribute("e1", "subsumptionFlagged")).toBe(true);
  });

  it("leaves a passing edge unmarked", () => {
    const g = buildTopologyGraph(CLASSES, [
      edge("e2", "WinterTyre", "Tyre", false),
    ]);
    expect(g.getEdgeAttribute("e2", "label")).not.toContain(WARNING);
    expect(g.getEdgeAttribute("e2", "subsumptionFlagged")).toBe(false);
  });

  it("leaves an unjudged edge unmarked", () => {
    // Every edge extracted before the judge existed. Absence of a verdict is
    // not a failing verdict, and must not paint the graph with warnings.
    const g = buildTopologyGraph(CLASSES, [edge("e3", "WinterTyre", "Tyre")]);
    expect(g.getEdgeAttribute("e3", "label")).not.toContain(WARNING);
  });

  it("keeps the mark in the base label, so it survives a lens relabel", () => {
    // The confidence lens rebuilds edge labels from ``baseLabel``; a mark that
    // only lived in ``label`` would disappear the moment the lens changed.
    const g = buildTopologyGraph(CLASSES, [
      edge("e1", "Tyre", "Vehicle", true),
    ]);
    expect(g.getEdgeAttribute("e1", "baseLabel")).toContain(WARNING);
  });

  it("keeps the underlying relationship name readable", () => {
    const g = buildTopologyGraph(CLASSES, [
      edge("e1", "Tyre", "Vehicle", true),
    ]);
    expect(g.getEdgeAttribute("e1", "label")).toContain("subclass of");
  });
});
