import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import AssetExplorer from "../AssetExplorer";
import { clearOntologyCache } from "@/lib/ontologyDataCache";

const get = jest.fn();

jest.mock("@/lib/api-client", () => ({
  api: {
    get: (...args: unknown[]) => get(...args),
  },
  ApiError: class ApiError extends Error {
    body: { message: string };
    status: number;
    constructor(status: number, body: { message: string }) {
      super(body.message);
      this.status = status;
      this.body = body;
    }
  },
}));

/**
 * Regression test for the cross-ontology edge/class dereference bug.
 *
 * The asset explorer lets several ontologies be expanded at once. When a
 * relation (or class) row is clicked, the explorer MUST report the row's
 * OWNING ontology id — not the globally-active one — so the workspace can
 * fetch ``GET /api/v1/ontology/{owner}/edges/{key}`` against the ontology
 * that actually holds the edge.
 *
 * The observed bug: with ontology A active but ontology B's relations
 * expanded, clicking one of B's relations fetched the edge against A and
 * 404'd with ``edge "…" does not belong to ontology`` (the FloatingDetailPanel
 * rendered "edge … not found"). The workspace-page handlers ignored the
 * ontology id the explorer already passes; this test pins the explorer half
 * of the contract so the id keeps flowing.
 */

const LIBRARY = {
  data: [
    { _key: "ont_active", name: "Active Ontology", label: null, tier: "local", status: "active", edge_count: 1 },
    { _key: "ont_other", name: "Other Ontology", label: null, tier: "local", status: "active", edge_count: 1 },
  ],
  cursor: null,
  has_more: false,
  total_count: 2,
};

const OTHER_CLASSES = {
  data: [
    { _key: "SmartKey", label: "SmartKey", status: "approved" },
    { _key: "LockingSystem", label: "Locking System", status: "approved" },
  ],
};

const OTHER_EDGES = {
  data: [
    {
      _key: "1417303",
      _from: "ontology_classes/SmartKey",
      _to: "ontology_classes/LockingSystem",
      edge_type: "subclass_of",
      label: null,
    },
  ],
};

function mockApi() {
  get.mockImplementation((path: string) => {
    if (path === "/api/v1/ontology/library") return Promise.resolve(LIBRARY);
    if (path === "/api/v1/ontology/ont_other/classes?include=summary")
      return Promise.resolve(OTHER_CLASSES);
    if (path === "/api/v1/ontology/ont_other/edges?include=summary")
      return Promise.resolve(OTHER_EDGES);
    // Catch-all for /api/v1/documents and anything else fired on mount.
    return Promise.resolve({ data: [] });
  });
}

describe("AssetExplorer cross-ontology selection passes the owning ontology id", () => {
  beforeEach(() => {
    get.mockReset();
    clearOntologyCache();
    mockApi();
  });

  it("passes the row's ontology id (not the active one) to onSelectEdge", async () => {
    const onSelectEdge = jest.fn();

    render(
      <AssetExplorer
        onSelectOntology={() => {}}
        onSelectDocument={() => {}}
        onSelectRun={() => {}}
        // A DIFFERENT ontology is active — the bug only shows when they differ.
        selectedOntologyId="ont_active"
        selectedRunId={null}
        onContextMenu={() => {}}
        onSelectEdge={onSelectEdge}
      />,
    );

    // Expand the non-active ontology, then open its Relations sub-section.
    fireEvent.click(await screen.findByText("Other Ontology"));
    fireEvent.click(await screen.findByText("Relations"));

    // The enriched relation row renders "source → target".
    const relationRow = await screen.findByText(/SmartKey\s*→\s*Locking System/);
    fireEvent.click(relationRow);

    await waitFor(() => expect(onSelectEdge).toHaveBeenCalled());
    // The whole point: the SECOND arg is the row's owning ontology, "ont_other".
    expect(onSelectEdge).toHaveBeenCalledWith("1417303", "ont_other");
  });

  it("passes the row's ontology id to onSelectClass", async () => {
    const onSelectClass = jest.fn();

    render(
      <AssetExplorer
        onSelectOntology={() => {}}
        onSelectDocument={() => {}}
        onSelectRun={() => {}}
        selectedOntologyId="ont_active"
        selectedRunId={null}
        onContextMenu={() => {}}
        onSelectClass={onSelectClass}
      />,
    );

    fireEvent.click(await screen.findByText("Other Ontology"));
    fireEvent.click(await screen.findByText("Classes"));

    fireEvent.click(await screen.findByText("SmartKey"));

    await waitFor(() => expect(onSelectClass).toHaveBeenCalled());
    expect(onSelectClass).toHaveBeenCalledWith("SmartKey", "ont_other");
  });
});
