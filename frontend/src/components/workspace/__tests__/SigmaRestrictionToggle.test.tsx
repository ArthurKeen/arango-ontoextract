/**
 * Toggling owl:Restriction edges must not rebuild the graph.
 *
 * It used to refetch under a different cache profile, which replaced the
 * edges array, which made the canvas discard its graph and re-run layout —
 * so the canvas blanked for seconds on every toggle. The edges now stay in
 * the graph once fetched and visibility is an edge-reducer decision.
 *
 * Sigma is mocked (it touches WebGL at import), so the test captures the
 * reducer the component installs and calls it directly.
 */

import { render } from "@testing-library/react";

const installedEdgeReducers: Array<
  (e: string, d: Record<string, unknown>) => unknown
> = [];

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
  default: class MockSigma {
    on() {
      return this;
    }
    kill() {}
    refresh() {}
    resize() {}
    getDimensions() {
      return { width: 800, height: 600 };
    }
    getBBox() {
      return {
        x: [0, 100] as [number, number],
        y: [0, 100] as [number, number],
      };
    }
    getCamera() {
      return {
        setState: () => {},
        getState: () => ({ ratio: 1, angle: 0, x: 0, y: 0 }),
        animate: () => {},
      };
    }
    getMouseCaptor() {
      return { on: () => {} };
    }
    getNodeDisplayData() {
      return { x: 400, y: 300, size: 10, color: "#000", label: "t" };
    }
    graphToViewport() {
      return { x: 400, y: 300 };
    }
    viewportToFramedGraph() {
      return { x: 0.5, y: 0.5 };
    }
    getStagePadding() {
      return 0;
    }
    setSetting(name: string, fn: unknown) {
      if (name === "edgeReducer" && typeof fn === "function") {
        installedEdgeReducers.push(
          fn as (e: string, d: Record<string, unknown>) => unknown,
        );
      }
    }
  },
}));

import SigmaCanvas from "../SigmaCanvas";

const CLASSES = [
  { _key: "A", label: "A", uri: "http://x#A", ontology_id: "o" },
  { _key: "B", label: "B", uri: "http://x#B", ontology_id: "o" },
] as never;

const EDGES = [
  {
    _key: "s1",
    _from: "ontology_classes/A",
    _to: "ontology_classes/B",
    type: "subclass_of",
  },
  {
    _key: "restriction:abc",
    _from: "ontology_classes/A",
    _to: "ontology_classes/B",
    type: "owl_restriction",
  },
] as never;

function lastReducer() {
  return installedEdgeReducers[installedEdgeReducers.length - 1];
}

describe("restriction visibility is a reducer decision, not a refetch", () => {
  beforeEach(() => {
    installedEdgeReducers.length = 0;
  });

  it("hides restriction edges when the toggle is off", () => {
    render(
      <SigmaCanvas
        classes={CLASSES}
        edges={EDGES}
        activeLens="semantic"
        hideRestrictions
      />,
    );

    const reduce = lastReducer();
    expect(reduce).toBeDefined();
    const hidden = reduce("e", {
      edgeType: "owl_restriction",
      label: "deployedSystem",
    });
    expect(hidden).toMatchObject({ hidden: true });
  });

  it("leaves every other edge type alone when the toggle is off", () => {
    render(
      <SigmaCanvas
        classes={CLASSES}
        edges={EDGES}
        activeLens="semantic"
        hideRestrictions
      />,
    );

    const kept = lastReducer()("e", {
      edgeType: "subclass_of",
      label: "subclass of",
    });
    expect(kept).not.toMatchObject({ hidden: true });
  });

  it("installs no reducer at all when nothing needs one", () => {
    // With restrictions shown and no filters or selection, the canvas should
    // not pay for a reducer on every edge.
    render(
      <SigmaCanvas
        classes={CLASSES}
        edges={EDGES}
        activeLens="semantic"
        hideRestrictions={false}
      />,
    );

    expect(installedEdgeReducers).toHaveLength(0);
  });
});
