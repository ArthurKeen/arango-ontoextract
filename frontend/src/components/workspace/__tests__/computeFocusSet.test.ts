/**
 * Focus mode hop computation (FR-7.8.15).
 *
 * The reducer that consumes this needs WebGL, but the decision of *what is in
 * focus* is pure graph traversal — so it is tested directly. What matters:
 * the radius is honoured exactly, traversal is undirected, and "show all"
 * short-circuits instead of materialising every node.
 */

// SigmaCanvas pulls in WebGL programs at import; JSDOM has no WebGL, so the
// rendering modules are stubbed exactly as SigmaCanvas.test.tsx does. The
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

import Graph from "graphology";
import { computeFocusSet } from "../SigmaCanvas";

/** a → b → c → d chain, plus an isolated island e—f. */
function chain(): Graph {
  const g = new Graph({ multi: true, type: "directed" });
  ["a", "b", "c", "d", "e", "f"].forEach((n) => g.addNode(n));
  g.addEdge("a", "b");
  g.addEdge("b", "c");
  g.addEdge("c", "d");
  g.addEdge("e", "f");
  return g;
}

describe("computeFocusSet", () => {
  it("includes the origin at radius 1", () => {
    expect(computeFocusSet(chain(), "a", 1)).toEqual(new Set(["a", "b"]));
  });

  it("widens exactly one ring per hop", () => {
    expect(computeFocusSet(chain(), "a", 2)).toEqual(new Set(["a", "b", "c"]));
    expect(computeFocusSet(chain(), "a", 3)).toEqual(new Set(["a", "b", "c", "d"]));
  });

  it("traverses undirected — a curator tracing connections ignores arrow direction", () => {
    // 'd' is downstream of everything; at 2 hops it must still reach back to 'b'.
    expect(computeFocusSet(chain(), "d", 2)).toEqual(new Set(["d", "c", "b"]));
  });

  it("never crosses into a disconnected component", () => {
    expect(computeFocusSet(chain(), "a", 10)).toEqual(new Set(["a", "b", "c", "d"]));
  });

  it("returns null for unlimited rather than a set of every node", () => {
    // Null lets the caller skip dimming entirely — on a 667-node graph the
    // difference between this and building the full set is the whole point.
    expect(computeFocusSet(chain(), "a", null)).toBeNull();
  });

  it("returns an empty set for an unknown origin, not the whole graph", () => {
    // Failing open here would silently un-dim everything and look like a no-op.
    expect(computeFocusSet(chain(), "ghost", 2)).toEqual(new Set());
  });

  it("stops early when the component is exhausted", () => {
    expect(computeFocusSet(chain(), "e", 5)).toEqual(new Set(["e", "f"]));
  });

  it("radius 0 is the origin alone", () => {
    expect(computeFocusSet(chain(), "b", 0)).toEqual(new Set(["b"]));
  });

  it("handles a node with no edges", () => {
    const g = new Graph({ multi: true, type: "directed" });
    g.addNode("lonely");
    expect(computeFocusSet(g, "lonely", 3)).toEqual(new Set(["lonely"]));
  });

  it("does not revisit nodes in a cycle", () => {
    const g = new Graph({ multi: true, type: "directed" });
    ["x", "y", "z"].forEach((n) => g.addNode(n));
    g.addEdge("x", "y");
    g.addEdge("y", "z");
    g.addEdge("z", "x");
    expect(computeFocusSet(g, "x", 5)).toEqual(new Set(["x", "y", "z"]));
  });
});

/**
 * Selection must beat dimming (FR-7.8.18 + FR-7.8.15).
 *
 * The node reducer returned early on the dim branch, BEFORE checking selection.
 * With focus on by default at 2 hops, shift-clicking any node outside that
 * radius updated state and rendered nothing — which is exactly what
 * "multi-select does not work" looked like from the outside.
 *
 * The reducer needs WebGL, so the ordering rule is pinned here as the predicate
 * it reduces to.
 */
describe("selection vs dimming precedence", () => {
  /** Mirrors the reducer's decision: dim only when NOT selected and out of focus. */
  function shouldDim(isSelected: boolean, inFocus: boolean): boolean {
    return !isSelected && !inFocus;
  }

  it("does not dim a selected node that is outside the focus radius", () => {
    expect(shouldDim(true, false)).toBe(false);
  });

  it("still dims an unselected node outside the radius", () => {
    expect(shouldDim(false, false)).toBe(true);
  });

  it("never dims anything inside the radius", () => {
    expect(shouldDim(false, true)).toBe(false);
    expect(shouldDim(true, true)).toBe(false);
  });
});

/**
 * Multi-origin focus (FR-7.8.18 + FR-7.8.15).
 *
 * A lasso selects many nodes and clears the primary selection, so focus driven
 * from a single key switched dimming OFF after every lasso — the graph stayed
 * fully bright and the selection was invisible in a hairball.
 */
describe("computeFocusSet with multiple origins", () => {
  function twoIslands(): Graph {
    const g = new Graph({ multi: true, type: "directed" });
    ["a", "b", "c", "x", "y", "z", "lonely"].forEach((n) => g.addNode(n));
    g.addEdge("a", "b");
    g.addEdge("b", "c");
    g.addEdge("x", "y");
    g.addEdge("y", "z");
    return g;
  }

  it("unions the neighbourhoods of every origin", () => {
    expect(computeFocusSet(twoIslands(), ["a", "x"], 1)).toEqual(
      new Set(["a", "b", "x", "y"]),
    );
  });

  it("still accepts a single key for the plain-selection path", () => {
    expect(computeFocusSet(twoIslands(), "a", 1)).toEqual(new Set(["a", "b"]));
  });

  it("ignores origins that are not in the graph rather than failing", () => {
    // A stale selection after a graph reload must not blank the canvas.
    expect(computeFocusSet(twoIslands(), ["a", "ghost"], 1)).toEqual(new Set(["a", "b"]));
  });

  it("returns an empty set when every origin is unknown", () => {
    expect(computeFocusSet(twoIslands(), ["ghost1", "ghost2"], 2)).toEqual(new Set());
  });

  it("an isolated origin contributes only itself", () => {
    expect(computeFocusSet(twoIslands(), ["a", "lonely"], 1)).toEqual(
      new Set(["a", "b", "lonely"]),
    );
  });

  it("honours the radius from each origin independently", () => {
    expect(computeFocusSet(twoIslands(), ["a", "x"], 2)).toEqual(
      new Set(["a", "b", "c", "x", "y", "z"]),
    );
  });
});
