/**
 * A-box canvas rendering (PRD §6.18 FR-18.13).
 *
 * Asserts the instance overlay the T-box canvas gained: individuals become their
 * own namespaced nodes, `rdf_type` links them to their class, and
 * `individual_assertion` links them to each other — without disturbing the
 * existing class/edge projection when no instances are supplied.
 */

import { render, screen, fireEvent } from "@testing-library/react";
import React from "react";
import GraphCanvas from "../GraphCanvas";
import type {
  OntologyClass,
  OntologyEdge,
  OntologyIndividual,
  RdfTypeEdge,
  IndividualAssertion,
} from "@/types/curation";

global.ResizeObserver = class ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
};

// Exposes the computed nodes/edges as JSON so the projection can be asserted
// without depending on React Flow's real rendering in jsdom.
jest.mock("reactflow", () => {
  const React = require("react");
  const MockReactFlow = ({
    nodes,
    edges,
    onNodeClick,
    children,
  }: {
    nodes: Array<Record<string, unknown>>;
    edges: Array<Record<string, unknown>>;
    onNodeClick?: (e: unknown, node: unknown) => void;
    children?: React.ReactNode;
  }) =>
    React.createElement(
      "div",
      { "data-testid": "mock-reactflow" },
      React.createElement(
        "span",
        { "data-testid": "node-ids" },
        nodes.map((n) => n.id).join(","),
      ),
      React.createElement(
        "span",
        { "data-testid": "node-types" },
        nodes.map((n) => `${n.id}:${n.type}`).join(","),
      ),
      React.createElement(
        "span",
        { "data-testid": "edge-ids" },
        edges.map((e) => e.id).join(","),
      ),
      React.createElement(
        "span",
        { "data-testid": "edge-wiring" },
        edges.map((e) => `${e.id}|${e.source}->${e.target}|${e.label}`).join(";"),
      ),
      ...nodes.map((n) =>
        React.createElement(
          "button",
          {
            key: String(n.id),
            "data-testid": `click-${n.id}`,
            onClick: () => onNodeClick?.({}, n),
          },
          String(n.id),
        ),
      ),
      children,
    );
  MockReactFlow.displayName = "MockReactFlow";

  return {
    __esModule: true,
    default: MockReactFlow,
    Background: () => null,
    BackgroundVariant: { Dots: "dots" },
    MarkerType: { ArrowClosed: "arrowclosed" },
    Handle: () => null,
    Position: { Top: "top", Bottom: "bottom" },
    MiniMap: () => null,
    Controls: () => null,
  };
});

jest.mock("dagre", () => {
  const Graph = class {
    private _nodes = new Map<string, Record<string, number>>();
    setGraph() {}
    setDefaultEdgeLabel() {}
    setNode(id: string, opts: { width: number; height: number }) {
      this._nodes.set(id, { x: 0, y: 0, width: opts.width, height: opts.height });
    }
    setEdge() {}
    node(id: string) {
      return this._nodes.get(id);
    }
  };
  return {
    __esModule: true,
    default: { graphlib: { Graph }, layout: () => {} },
  };
});

function cls(key: string, label = key): OntologyClass {
  return {
    _key: key,
    uri: `http://example.org/${key}`,
    label,
    description: "",
    rdf_type: "owl:Class",
    confidence: 0.9,
    status: "pending",
    ontology_id: "ont1",
    created: "",
    expired: null,
  };
}

function individual(key: string, label = key): OntologyIndividual {
  return {
    _key: key,
    _id: `ontology_individuals/${key}`,
    label,
    provenance: [{ doc_id: "d1" }],
  };
}

function typeEdge(key: string, individualKey: string, classKey: string): RdfTypeEdge {
  return {
    _key: key,
    _from: `ontology_individuals/${individualKey}`,
    _to: `ontology_classes/${classKey}`,
  };
}

const CLASSES = [cls("Person"), cls("Organization")];
const NO_EDGES: OntologyEdge[] = [];

describe("GraphCanvas — A-box overlay (FR-18.13)", () => {
  it("renders only T-box nodes when no individuals are supplied", () => {
    render(<GraphCanvas classes={CLASSES} properties={[]} edges={NO_EDGES} />);
    expect(screen.getByTestId("node-ids")).toHaveTextContent("Person,Organization");
    expect(screen.getByTestId("edge-ids").textContent).toBe("");
  });

  it("adds a namespaced individual node and an rdf:type edge to its class", () => {
    render(
      <GraphCanvas
        classes={CLASSES}
        properties={[]}
        edges={NO_EDGES}
        individuals={[individual("i1", "Acme Corp")]}
        rdfTypeEdges={[typeEdge("e1", "i1", "Organization")]}
      />,
    );

    // Namespaced so an individual _key can never collide with a class _key.
    expect(screen.getByTestId("node-ids")).toHaveTextContent("ind:i1");
    expect(screen.getByTestId("node-types")).toHaveTextContent("ind:i1:individualNode");
    // Class is the layout source (ranked above); label marks it as rdf:type.
    expect(screen.getByTestId("edge-wiring")).toHaveTextContent(
      "rdftype-e1|Organization->ind:i1|rdf:type",
    );
  });

  it("renders assertion edges between two drawn individuals using the predicate", () => {
    const assertions: IndividualAssertion[] = [
      {
        _key: "a1",
        _from: "ontology_individuals/i1",
        _to: "ontology_individuals/i2",
        predicate: "employs",
      },
    ];
    render(
      <GraphCanvas
        classes={CLASSES}
        properties={[]}
        edges={NO_EDGES}
        individuals={[individual("i1"), individual("i2")]}
        rdfTypeEdges={[
          typeEdge("e1", "i1", "Organization"),
          typeEdge("e2", "i2", "Person"),
        ]}
        assertions={assertions}
      />,
    );
    expect(screen.getByTestId("edge-wiring")).toHaveTextContent(
      "assert-a1|ind:i1->ind:i2|employs",
    );
  });

  it("drops an individual whose rdf:type class is not on the canvas", () => {
    // Otherwise the instance renders stranded, with no visible type link.
    render(
      <GraphCanvas
        classes={[cls("Person")]}
        properties={[]}
        edges={NO_EDGES}
        individuals={[individual("i1")]}
        rdfTypeEdges={[typeEdge("e1", "i1", "Organization")]}
      />,
    );
    expect(screen.getByTestId("node-ids").textContent).toBe("Person");
    expect(screen.getByTestId("edge-ids").textContent).toBe("");
  });

  it("drops an assertion whose endpoint individual was not drawn", () => {
    render(
      <GraphCanvas
        classes={CLASSES}
        properties={[]}
        edges={NO_EDGES}
        individuals={[individual("i1")]}
        rdfTypeEdges={[typeEdge("e1", "i1", "Organization")]}
        assertions={[
          {
            _key: "a1",
            _from: "ontology_individuals/i1",
            _to: "ontology_individuals/ghost",
            predicate: "employs",
          },
        ]}
      />,
    );
    expect(screen.getByTestId("edge-ids")).toHaveTextContent("rdftype-e1");
    expect(screen.getByTestId("edge-ids")).not.toHaveTextContent("assert-a1");
  });

  it("routes an individual click to onIndividualSelect with the bare key", () => {
    const onIndividualSelect = jest.fn();
    const onNodeSelect = jest.fn();
    render(
      <GraphCanvas
        classes={CLASSES}
        properties={[]}
        edges={NO_EDGES}
        individuals={[individual("i1")]}
        rdfTypeEdges={[typeEdge("e1", "i1", "Organization")]}
        onIndividualSelect={onIndividualSelect}
        onNodeSelect={onNodeSelect}
      />,
    );
    fireEvent.click(screen.getByTestId("click-ind:i1"));
    expect(onIndividualSelect).toHaveBeenCalledWith("i1");
    // The class detail panel must not try to resolve "ind:i1" as a class.
    expect(onNodeSelect).not.toHaveBeenCalled();
  });

  it("still routes a class click to onNodeSelect", () => {
    const onIndividualSelect = jest.fn();
    const onNodeSelect = jest.fn();
    render(
      <GraphCanvas
        classes={CLASSES}
        properties={[]}
        edges={NO_EDGES}
        individuals={[individual("i1")]}
        rdfTypeEdges={[typeEdge("e1", "i1", "Organization")]}
        onIndividualSelect={onIndividualSelect}
        onNodeSelect={onNodeSelect}
      />,
    );
    fireEvent.click(screen.getByTestId("click-Person"));
    expect(onNodeSelect).toHaveBeenCalledWith("Person");
    expect(onIndividualSelect).not.toHaveBeenCalled();
  });

  it("emits both rdf:type edges for a multi-typed individual without duplicating the node", () => {
    render(
      <GraphCanvas
        classes={CLASSES}
        properties={[]}
        edges={NO_EDGES}
        individuals={[individual("i1")]}
        rdfTypeEdges={[
          typeEdge("e1", "i1", "Person"),
          typeEdge("e2", "i1", "Organization"),
        ]}
      />,
    );
    const ids = screen.getByTestId("node-ids").textContent ?? "";
    expect(ids.split(",").filter((id) => id === "ind:i1")).toHaveLength(1);
    expect(screen.getByTestId("edge-ids")).toHaveTextContent("rdftype-e1");
    expect(screen.getByTestId("edge-ids")).toHaveTextContent("rdftype-e2");
  });
});
