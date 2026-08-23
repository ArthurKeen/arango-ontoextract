/**
 * Does the selection wiring actually receive Sigma's events? (FR-7.8.18)
 *
 * The existing SigmaCanvas mock stubs `on()` as a no-op, so every handler this
 * component registers was untested — which is how shift-click and lasso shipped
 * broken. This mock CAPTURES handlers so they can be fired with realistic
 * payloads, matching Sigma 3.0.2's actual shapes:
 *   clickNode -> { node, event: { x, y, original: MouseEvent, ... } }
 */

import { render } from "@testing-library/react";

const handlers = new Map<string, (payload: unknown) => void>();
const captorHandlers = new Map<string, (payload: unknown) => void>();
const settings: Record<string, unknown> = {};

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
    on(name: string, fn: (payload: unknown) => void) {
      handlers.set(name, fn);
      return this;
    }
    kill() {}
    refresh() {}
    resize() {}
    setSetting(k: string, v: unknown) {
      settings[k] = v;
    }
    getDimensions() {
      return { width: 800, height: 600 };
    }
    getBBox() {
      return { x: [0, 100] as [number, number], y: [0, 100] as [number, number] };
    }
    getCamera() {
      return {
        setState: () => {},
        getState: () => ({ ratio: 1, angle: 0, x: 0, y: 0 }),
        animate: () => {},
      };
    }
    getMouseCaptor() {
      return {
        on: (name: string, fn: (payload: unknown) => void) => captorHandlers.set(name, fn),
      };
    }
    getNodeDisplayData(node: string) {
      // Two nodes at known viewport positions so a lasso box can include one.
      return node === "A"
        ? { x: 100, y: 100, size: 10, color: "#000", label: "A" }
        : { x: 600, y: 500, size: 10, color: "#000", label: "B" };
    }
    viewportToGraph() {
      return { x: 0, y: 0 };
    }
    graphToViewport() {
      return { x: 0, y: 0 };
    }
  },
}));

import SigmaCanvas from "../SigmaCanvas";
import type { OntologyClass, OntologyEdge } from "@/types/curation";

global.ResizeObserver = class {
  observe() {}
  unobserve() {}
  disconnect() {}
} as unknown as typeof ResizeObserver;

function cls(key: string): OntologyClass {
  return {
    _key: key,
    uri: `http://example.org/o#${key}`,
    label: key,
    description: "",
    rdf_type: "owl:Class",
    confidence: 0.9,
    status: "pending",
    ontology_id: "o",
    created: "",
    expired: null,
  };
}

const CLASSES = [cls("A"), cls("B")];
const EDGES: OntologyEdge[] = [];

/** Sigma 3.0.2 clickNode payload shape. */
function clickPayload(node: string, mouse: Partial<MouseEvent>) {
  return {
    node,
    event: { x: 0, y: 0, original: mouse as MouseEvent, preventSigmaDefault: () => {} },
    preventSigmaDefault: () => {},
  };
}

describe("SigmaCanvas selection wiring", () => {
  beforeEach(() => {
    handlers.clear();
    captorHandlers.clear();
  });

  it("registers clickNode and clickStage handlers at all", () => {
    render(<SigmaCanvas classes={CLASSES} edges={EDGES} activeLens="semantic" />);
    expect(handlers.has("clickNode")).toBe(true);
    expect(handlers.has("clickStage")).toBe(true);
  });

  it("routes a SHIFT-click to onNodeShiftSelect, not onNodeSelect", () => {
    const onNodeSelect = jest.fn();
    const onNodeShiftSelect = jest.fn();
    render(
      <SigmaCanvas
        classes={CLASSES}
        edges={EDGES}
        activeLens="semantic"
        onNodeSelect={onNodeSelect}
        onNodeShiftSelect={onNodeShiftSelect}
      />,
    );
    handlers.get("clickNode")?.(clickPayload("A", { shiftKey: true, button: 0 }));
    expect(onNodeShiftSelect).toHaveBeenCalledWith("A");
    expect(onNodeSelect).not.toHaveBeenCalled();
  });

  it("routes a plain click to onNodeSelect", () => {
    const onNodeSelect = jest.fn();
    const onNodeShiftSelect = jest.fn();
    render(
      <SigmaCanvas
        classes={CLASSES}
        edges={EDGES}
        activeLens="semantic"
        onNodeSelect={onNodeSelect}
        onNodeShiftSelect={onNodeShiftSelect}
      />,
    );
    handlers.get("clickNode")?.(clickPayload("A", { shiftKey: false, button: 0 }));
    expect(onNodeSelect).toHaveBeenCalledWith("A");
    expect(onNodeShiftSelect).not.toHaveBeenCalled();
  });

  it("does not start a lasso without a modifier — plain drag still pans", () => {
    const onLassoSelect = jest.fn();
    const { container } = render(
      <SigmaCanvas
        classes={CLASSES}
        edges={EDGES}
        activeLens="semantic"
        onLassoSelect={onLassoSelect}
      />,
    );
    const el = (container.querySelector('[data-testid="sigma-canvas"]') as HTMLElement)
      .lastElementChild as HTMLElement;
    el.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, button: 0, clientX: 50, clientY: 50 }));
    window.dispatchEvent(new MouseEvent("mousemove", { bubbles: true, clientX: 300, clientY: 300 }));
    window.dispatchEvent(new MouseEvent("mouseup", { bubbles: true }));
    expect(onLassoSelect).not.toHaveBeenCalled();
  });

  it("ignores a right-button drag — Ctrl+click IS the secondary click on macOS", () => {
    const onLassoSelect = jest.fn();
    const { container } = render(
      <SigmaCanvas
        classes={CLASSES}
        edges={EDGES}
        activeLens="semantic"
        onLassoSelect={onLassoSelect}
      />,
    );
    const el = (container.querySelector('[data-testid="sigma-canvas"]') as HTMLElement)
      .lastElementChild as HTMLElement;
    el.dispatchEvent(
      new MouseEvent("mousedown", { bubbles: true, ctrlKey: true, button: 2, clientX: 50, clientY: 50 }),
    );
    window.dispatchEvent(new MouseEvent("mousemove", { bubbles: true, clientX: 300, clientY: 300 }));
    window.dispatchEvent(new MouseEvent("mouseup", { bubbles: true }));
    expect(onLassoSelect).not.toHaveBeenCalled();
  });

  it("treats a click-sized box as a click, not a lasso", () => {
    const onLassoSelect = jest.fn();
    const { container } = render(
      <SigmaCanvas
        classes={CLASSES}
        edges={EDGES}
        activeLens="semantic"
        onLassoSelect={onLassoSelect}
      />,
    );
    const el = (container.querySelector('[data-testid="sigma-canvas"]') as HTMLElement)
      .lastElementChild as HTMLElement;
    el.dispatchEvent(
      new MouseEvent("mousedown", { bubbles: true, shiftKey: true, button: 0, clientX: 50, clientY: 50 }),
    );
    window.dispatchEvent(new MouseEvent("mousemove", { bubbles: true, clientX: 51, clientY: 51 }));
    window.dispatchEvent(new MouseEvent("mouseup", { bubbles: true }));
    expect(onLassoSelect).not.toHaveBeenCalled();
  });

  it("draws a lasso and selects the nodes inside it on ctrl+drag", () => {
    const onLassoSelect = jest.fn();
    const { container } = render(
      <SigmaCanvas
        classes={CLASSES}
        edges={EDGES}
        activeLens="semantic"
        onLassoSelect={onLassoSelect}
      />,
    );
    // The lasso listener lives on the INNER div that holds the ref (where
    // Sigma renders), not the outer test-id wrapper — events bubble up to it
    // from Sigma's canvas, but a dispatch on the wrapper never reaches it.
    const wrapper = container.querySelector('[data-testid="sigma-canvas"]') as HTMLElement;
    const canvasEl = wrapper.lastElementChild as HTMLElement;
    expect(canvasEl).toBeTruthy();

    // Node A sits at viewport (100,100); B at (600,500). The box covers A only.
    canvasEl.dispatchEvent(
      new MouseEvent("mousedown", { bubbles: true, shiftKey: true, button: 0, clientX: 50, clientY: 50 }),
    );
    window.dispatchEvent(new MouseEvent("mousemove", { bubbles: true, clientX: 300, clientY: 300 }));
    window.dispatchEvent(new MouseEvent("mouseup", { bubbles: true }));

    expect(onLassoSelect).toHaveBeenCalledWith(["A"]);
  });

  it("fires onStageClick when empty canvas is clicked", () => {
    const onStageClick = jest.fn();
    render(
      <SigmaCanvas
        classes={CLASSES}
        edges={EDGES}
        activeLens="semantic"
        onStageClick={onStageClick}
      />,
    );
    handlers.get("clickStage")?.({ event: { x: 0, y: 0 } });
    expect(onStageClick).toHaveBeenCalled();
  });
});
