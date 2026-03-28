import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import VCRTimeline from "@/components/timeline/VCRTimeline";
import type { TimelineEvent } from "@/types/timeline";

const mockEvents: TimelineEvent[] = [
  {
    timestamp: "2026-03-10T10:00:00Z",
    event_type: "created",
    entity_key: "cls_001",
    entity_label: "Person",
    collection: "ontology_classes",
  },
  {
    timestamp: "2026-03-12T14:00:00Z",
    event_type: "edited",
    entity_key: "cls_001",
    entity_label: "Person",
    collection: "ontology_classes",
  },
  {
    timestamp: "2026-03-15T09:00:00Z",
    event_type: "approved",
    entity_key: "cls_002",
    entity_label: "Organization",
    collection: "ontology_classes",
  },
];

function mockFetchEvents(events: TimelineEvent[]) {
  global.fetch = jest.fn().mockResolvedValue({
    ok: true,
    json: () => Promise.resolve({ data: events }),
  });
}

function mockFetchEmpty() {
  global.fetch = jest.fn().mockResolvedValue({
    ok: true,
    json: () => Promise.resolve({ data: [] }),
  });
}

function mockFetchError() {
  global.fetch = jest.fn().mockResolvedValue({
    ok: false,
    statusText: "Not Found",
    json: () =>
      Promise.resolve({
        error: { code: "NOT_FOUND", message: "Timeline not found" },
      }),
  });
}

afterEach(() => {
  jest.restoreAllMocks();
});

describe("VCRTimeline", () => {
  it("renders timeline controls after loading", async () => {
    mockFetchEvents(mockEvents);
    render(<VCRTimeline ontologyId="onto_abc" />);

    await waitFor(() => {
      expect(screen.getByTestId("vcr-timeline")).toBeInTheDocument();
    });

    expect(screen.getByTestId("timeline-play-pause")).toBeInTheDocument();
    expect(screen.getByTestId("timeline-rewind")).toBeInTheDocument();
    expect(screen.getByTestId("timeline-ff")).toBeInTheDocument();
    expect(screen.getByTestId("timeline-slider")).toBeInTheDocument();
    expect(screen.getByTestId("timeline-speed")).toBeInTheDocument();
  });

  it("shows loading state", () => {
    global.fetch = jest.fn().mockImplementation(
      () => new Promise(() => {}),
    );
    render(<VCRTimeline ontologyId="onto_abc" />);
    expect(screen.getByTestId("timeline-loading")).toBeInTheDocument();
  });

  it("shows empty state when no events", async () => {
    mockFetchEmpty();
    render(<VCRTimeline ontologyId="onto_abc" />);

    await waitFor(() => {
      expect(screen.getByTestId("timeline-empty")).toBeInTheDocument();
    });
  });

  it("shows error state on API failure", async () => {
    mockFetchError();
    render(<VCRTimeline ontologyId="onto_abc" />);

    await waitFor(() => {
      expect(screen.getByTestId("timeline-error")).toBeInTheDocument();
    });
  });

  it("displays current event info", async () => {
    mockFetchEvents(mockEvents);
    render(<VCRTimeline ontologyId="onto_abc" />);

    await waitFor(() => {
      expect(screen.getByText("Organization")).toBeInTheDocument();
    });

    expect(screen.getByText("3 / 3")).toBeInTheDocument();
  });

  it("navigates with rewind button", async () => {
    mockFetchEvents(mockEvents);
    const onTimestamp = jest.fn();
    render(
      <VCRTimeline ontologyId="onto_abc" onTimestampChange={onTimestamp} />,
    );

    await waitFor(() => {
      expect(screen.getByTestId("vcr-timeline")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId("timeline-rewind"));

    await waitFor(() => {
      expect(screen.getByText("2 / 3")).toBeInTheDocument();
    });
  });

  it("slider changes current position", async () => {
    mockFetchEvents(mockEvents);
    render(<VCRTimeline ontologyId="onto_abc" />);

    await waitFor(() => {
      expect(screen.getByTestId("timeline-slider")).toBeInTheDocument();
    });

    fireEvent.change(screen.getByTestId("timeline-slider"), {
      target: { value: "0" },
    });

    await waitFor(() => {
      expect(screen.getByText("1 / 3")).toBeInTheDocument();
    });
  });

  it("cycles speed on speed button click", async () => {
    mockFetchEvents(mockEvents);
    render(<VCRTimeline ontologyId="onto_abc" />);

    await waitFor(() => {
      expect(screen.getByTestId("timeline-speed")).toBeInTheDocument();
    });

    expect(screen.getByTestId("timeline-speed")).toHaveTextContent("1x");
    fireEvent.click(screen.getByTestId("timeline-speed"));
    expect(screen.getByTestId("timeline-speed")).toHaveTextContent("2x");
  });
});
