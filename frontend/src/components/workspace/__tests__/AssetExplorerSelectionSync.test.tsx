import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import AssetExplorer from "../AssetExplorer";
import { clearOntologyCache } from "@/lib/ontologyDataCache";

const get = jest.fn();

jest.mock("@/lib/api-client", () => ({
  api: { get: (...args: unknown[]) => get(...args) },
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
 * Multi-selection is visible and filterable in the sidebar (FR-4.16b).
 *
 * Reported symptom: 96 classes selected out of 1688 and no way to tell which.
 * Marking rows is necessary but NOT sufficient at that scale — the filter is
 * what makes the selection readable, so it is tested as the primary behaviour.
 */

const ONT = { _key: "jlr", name: "JLR", ontology_id: "jlr", status: "active", class_count: 3 };
const CLASSES = [
  { _key: "A", label: "Alarm System" },
  { _key: "B", label: "Brake System" },
  { _key: "C", label: "Cruise Control" },
];

function mockRoutes() {
  get.mockImplementation((path: string) => {
    if (path === "/api/v1/ontology/library") return Promise.resolve({ data: [ONT] });
    if (path === "/api/v1/documents") return Promise.resolve({ data: [] });
    if (path.includes("/classes")) return Promise.resolve({ data: CLASSES });
    return Promise.resolve({ data: [] });
  });
}

function renderExplorer(overrides: Record<string, unknown> = {}) {
  return render(
    <AssetExplorer
      onSelectOntology={jest.fn()}
      onSelectDocument={jest.fn()}
      onSelectRun={jest.fn()}
      selectedOntologyId="jlr"
      selectedRunId={null}
      onContextMenu={jest.fn()}
      {...overrides}
    />,
  );
}

describe("AssetExplorer multi-selection sync", () => {
  beforeEach(() => {
    get.mockReset();
    clearOntologyCache();
    mockRoutes();
  });

  it("offers the Selected-only filter only while something is selected", async () => {
    const { rerender } = renderExplorer({ multiSelectedKeys: new Set<string>() });
    await screen.findByText("JLR");
    expect(screen.queryByTestId("selected-only-toggle")).not.toBeInTheDocument();

    rerender(
      <AssetExplorer
        onSelectOntology={jest.fn()}
        onSelectDocument={jest.fn()}
        onSelectRun={jest.fn()}
        selectedOntologyId="jlr"
        selectedRunId={null}
        onContextMenu={jest.fn()}
        multiSelectedKeys={new Set(["A"])}
      />,
    );
    expect(await screen.findByTestId("selected-only-toggle")).toBeInTheDocument();
  });

  it("shows the selection count", async () => {
    renderExplorer({ multiSelectedKeys: new Set(["A", "B"]) });
    expect(await screen.findByText("2 selected")).toBeInTheDocument();
  });

  it("shift-clicking a class row toggles membership rather than navigating", async () => {
    const onShiftSelectClass = jest.fn();
    const onSelectClass = jest.fn();
    renderExplorer({
      multiSelectedKeys: new Set(["A"]),
      onShiftSelectClass,
      onSelectClass,
    });
    // Expand the ontology, then its Classes group.
    fireEvent.click(await screen.findByText("JLR"));
    const classesToggle = await screen.findByText("Classes");
    fireEvent.click(classesToggle);
    const row = await screen.findByText("Brake System");
    fireEvent.click(row, { shiftKey: true });
    await waitFor(() => expect(onShiftSelectClass).toHaveBeenCalledWith("B", "jlr"));
    // A shift-click must not double as ordinary navigation.
    expect(onSelectClass).not.toHaveBeenCalled();
  });

  it("marks members of the selection", async () => {
    renderExplorer({ multiSelectedKeys: new Set(["A"]) });
    fireEvent.click(await screen.findByText("JLR"));
    fireEvent.click(await screen.findByText("Classes"));
    await screen.findByText("Alarm System");
    const marked = document.querySelectorAll('[data-in-selection="true"]');
    expect(marked.length).toBe(1);
  });
});
