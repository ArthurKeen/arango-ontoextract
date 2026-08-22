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
 * Explorer search must reach class and property labels (FR-7.8.13).
 *
 * It previously filtered only document filenames and ontology names, so
 * searching "Vehicle" against an ontology full of Vehicle* classes reported
 * "No ontologies" — the search looked broken because it was answering a
 * different question than the one being asked.
 *
 * The backend endpoint already existed (BM25 over ``ontology_search_view``) and
 * the library page already used it; only the explorer never called it. These
 * tests pin that it now does, and that a hit is attributable to its ontology.
 */

const SEARCH_RESPONSE = {
  query: "Vehicle",
  results: {
    registry: [],
    classes: [
      {
        _key: "VehicleSecurity",
        label: "Vehicle Security",
        ontology_id: "jlr",
        ontology_name: "JLR Manual",
        score: 9.1,
        source: "class" as const,
      },
    ],
    properties: [
      {
        _key: "vehicle_speed",
        label: "vehicle speed",
        ontology_id: "jlr",
        ontology_name: "JLR Manual",
        score: 4.2,
        source: "property" as const,
      },
    ],
  },
  counts: { registry: 0, classes: 1, properties: 1 },
  offset: 0,
  limit: 20,
};

function baseRoutes(path: string) {
  if (path === "/api/v1/ontology/library") return Promise.resolve({ data: [] });
  if (path === "/api/v1/documents") return Promise.resolve({ data: [] });
  return Promise.resolve({ data: [] });
}

function renderExplorer(overrides: Record<string, unknown> = {}) {
  return render(
    <AssetExplorer
      onSelectOntology={jest.fn()}
      onSelectDocument={jest.fn()}
      onSelectRun={jest.fn()}
      selectedOntologyId={null}
      selectedRunId={null}
      onContextMenu={jest.fn()}
      {...overrides}
    />,
  );
}

describe("AssetExplorer concept search", () => {
  beforeEach(() => {
    jest.useFakeTimers();
    get.mockReset();
    clearOntologyCache();
    get.mockImplementation((path: string) =>
      path.startsWith("/api/v1/ontology/search")
        ? Promise.resolve(SEARCH_RESPONSE)
        : baseRoutes(path),
    );
  });

  afterEach(() => {
    jest.runOnlyPendingTimers();
    jest.useRealTimers();
  });

  function type(value: string) {
    fireEvent.change(screen.getByPlaceholderText(/search assets/i), {
      target: { value },
    });
    jest.advanceTimersByTime(350); // clear the debounce
  }

  it("queries the backend and lists matching classes and properties", async () => {
    renderExplorer();
    type("Vehicle");

    await waitFor(() => {
      expect(
        get.mock.calls.some((c) => String(c[0]).startsWith("/api/v1/ontology/search?q=Vehicle")),
      ).toBe(true);
    });
    expect(await screen.findByTestId("concept-hit-VehicleSecurity")).toBeInTheDocument();
    expect(await screen.findByTestId("concept-hit-vehicle_speed")).toBeInTheDocument();
  });

  it("attributes each hit to its owning ontology", async () => {
    // The same label can exist in several ontologies; an unattributed hit
    // cannot be acted on.
    renderExplorer();
    type("Vehicle");
    const hit = await screen.findByTestId("concept-hit-VehicleSecurity");
    expect(hit).toHaveTextContent("JLR Manual");
  });

  it("selects the class — and its ontology — when a class hit is clicked", async () => {
    const onSelectClass = jest.fn();
    renderExplorer({ onSelectClass });
    type("Vehicle");
    fireEvent.click(await screen.findByTestId("concept-hit-VehicleSecurity"));
    expect(onSelectClass).toHaveBeenCalledWith("VehicleSecurity", "jlr");
  });

  it("does not query on a single character", async () => {
    // Two-character floor: one letter matches most of a large ontology and the
    // request is pure cost.
    renderExplorer();
    type("V");
    expect(
      get.mock.calls.some((c) => String(c[0]).includes("/ontology/search")),
    ).toBe(false);
    expect(screen.queryByTestId("concept-results")).not.toBeInTheDocument();
  });

  it("says so when nothing matches, rather than showing an empty panel", async () => {
    get.mockImplementation((path: string) =>
      path.startsWith("/api/v1/ontology/search")
        ? Promise.resolve({
            ...SEARCH_RESPONSE,
            results: { registry: [], classes: [], properties: [] },
            counts: { registry: 0, classes: 0, properties: 0 },
          })
        : baseRoutes(path),
    );
    renderExplorer();
    type("Zzz");
    expect(await screen.findByTestId("concept-empty")).toBeInTheDocument();
  });

  it("survives a failing search without breaking the explorer", async () => {
    get.mockImplementation((path: string) =>
      path.startsWith("/api/v1/ontology/search")
        ? Promise.reject(new Error("view missing"))
        : baseRoutes(path),
    );
    renderExplorer();
    type("Vehicle");
    expect(await screen.findByTestId("concept-empty")).toBeInTheDocument();
  });
});

/**
 * Pending-work badge (FR-7.8.14).
 *
 * The revisions inbox is reachable only by right-clicking an ontology and
 * already knowing it exists — the §7.8 rules call that functionally absent
 * without an explicit discoverability mitigation. The badge is that mitigation.
 */
describe("AssetExplorer pending-work badge", () => {
  const ONT = {
    _key: "jlr",
    name: "JLR Manual",
    ontology_id: "jlr",
    status: "active",
  };

  beforeEach(() => {
    get.mockReset();
    clearOntologyCache();
  });

  function mockWith(inbox: unknown) {
    get.mockImplementation((path: string) => {
      if (path === "/api/v1/ontology/library") return Promise.resolve({ data: [ONT] });
      if (path === "/api/v1/documents") return Promise.resolve({ data: [] });
      if (path.startsWith("/api/v1/revisions/inbox")) return inbox as Promise<unknown>;
      return Promise.resolve({ data: [] });
    });
  }

  it("shows the count for the open ontology", async () => {
    mockWith(Promise.resolve({ count: 7 }));
    renderExplorer({ selectedOntologyId: "jlr" });
    expect(await screen.findByTestId("pending-badge-jlr")).toHaveTextContent("7");
  });

  it("shows no badge when nothing is pending", async () => {
    mockWith(Promise.resolve({ count: 0 }));
    renderExplorer({ selectedOntologyId: "jlr" });
    await screen.findByText("JLR Manual");
    expect(screen.queryByTestId("pending-badge-jlr")).not.toBeInTheDocument();
  });

  it("caps the display at 99+ so the row cannot be blown out", async () => {
    mockWith(Promise.resolve({ count: 250 }));
    renderExplorer({ selectedOntologyId: "jlr" });
    expect(await screen.findByTestId("pending-badge-jlr")).toHaveTextContent("99+");
  });

  it("does not query the inbox when no ontology is open", async () => {
    mockWith(Promise.resolve({ count: 7 }));
    renderExplorer({ selectedOntologyId: null });
    await screen.findByText("JLR Manual");
    expect(get.mock.calls.some((c) => String(c[0]).includes("/revisions/inbox"))).toBe(false);
  });

  it("degrades to no badge if the inbox call fails", async () => {
    // An absent badge reads as "nothing pending" — the safe wrong answer.
    // A broken row is not.
    mockWith(Promise.reject(new Error("boom")));
    renderExplorer({ selectedOntologyId: "jlr" });
    await screen.findByText("JLR Manual");
    expect(screen.queryByTestId("pending-badge-jlr")).not.toBeInTheDocument();
  });
});
