/**
 * Label-collision work queue (PRD §6.20 FR-20.1..FR-20.3).
 *
 * The behaviours worth pinning are the ones a curator would be hurt by if they
 * regressed: a partial resolution must be allowed, a blank box must mean "leave
 * this one alone" rather than "blank the label", and dismiss must not quietly
 * record a decision.
 */

import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import React from "react";
import LexiconQueueOverlay from "../LexiconQueueOverlay";
import { api } from "@/lib/api-client";

jest.mock("@/lib/api-client", () => ({
  api: { get: jest.fn(), post: jest.fn() },
  ApiError: class ApiError extends Error {
    body: { message: string };
    constructor(message: string) {
      super(message);
      this.body = { message };
    }
  },
}));

const mockApi = api as jest.Mocked<typeof api>;

const DOC_ROLE = "http://example.org/crm#DocumentRole";
const CONTACT_ROLE = "http://example.org/crm#ContactRole";

const COLLISION = {
  _key: "c1",
  scope: "o1",
  label: "role",
  normalized_label: "role",
  status: "open" as const,
  source: "local",
  occurrence_count: 2,
  occurrences: [
    {
      concept_uri: DOC_ROLE,
      concept_type: "datatype_property",
      ontology_id: "o1",
      label: "role",
      description: "the document's kind",
      source_system: "docs",
      sample_values: ["signal", "qbr"],
    },
    {
      concept_uri: CONTACT_ROLE,
      concept_type: "datatype_property",
      ontology_id: "o1",
      label: "role",
      description: "a person's job",
      source_system: "crm",
      sample_values: ["champion", "exec"],
    },
  ],
};

function renderOverlay() {
  return render(
    <LexiconQueueOverlay
      ontologyId="o1"
      ontologyName="CRM"
      curatorId="arthur"
      onClose={jest.fn()}
    />,
  );
}

async function openFirstCollision() {
  renderOverlay();
  await screen.findByTestId("collision-c1");
  fireEvent.click(screen.getByTestId("collision-toggle-c1"));
}

beforeEach(() => {
  jest.clearAllMocks();
  mockApi.get.mockResolvedValue({ data: [COLLISION] });
  mockApi.post.mockResolvedValue({});
});

describe("LexiconQueueOverlay", () => {
  it("lists open collisions", async () => {
    renderOverlay();
    expect(await screen.findByTestId("collision-c1")).toBeInTheDocument();
    expect(mockApi.get).toHaveBeenCalledWith(
      "/api/v1/ontology/lexicon/collisions?status=open&limit=200",
    );
  });

  it("shows an empty state when nothing is queued", async () => {
    mockApi.get.mockResolvedValue({ data: [] });
    renderOverlay();
    expect(await screen.findByTestId("lexicon-empty")).toBeInTheDocument();
  });

  it("surfaces each occurrence with its source system and sample values", async () => {
    await openFirstCollision();
    // Sample values are the fastest way to settle the judgement, so they must
    // be on screen next to the concept rather than behind another click.
    expect(screen.getByTestId(`samples-${DOC_ROLE}`)).toHaveTextContent("signal");
    expect(screen.getByTestId(`samples-${CONTACT_ROLE}`)).toHaveTextContent("champion");
    expect(screen.getByText("docs")).toBeInTheDocument();
    expect(screen.getByText("crm")).toBeInTheDocument();
    expect(screen.getByText("a person's job")).toBeInTheDocument();
  });

  it("records a decision for only the concepts given a label", async () => {
    await openFirstCollision();
    fireEvent.change(screen.getByTestId(`label-input-${CONTACT_ROLE}`), {
      target: { value: "job title" },
    });
    fireEvent.click(screen.getByTestId("resolve-c1"));

    await waitFor(() => expect(mockApi.post).toHaveBeenCalled());
    const [url, body] = mockApi.post.mock.calls[0];
    expect(url).toBe("/api/v1/ontology/lexicon/collisions/c1/resolve");
    expect(body).toEqual({
      curator_id: "arthur",
      resolutions: [
        {
          concept_uri: CONTACT_ROLE,
          label: "job title",
          concept_type: "datatype_property",
          ontology_id: "o1",
        },
      ],
    });
  });

  it("treats a blank box as leave-unchanged, not blank-the-label", async () => {
    await openFirstCollision();
    fireEvent.change(screen.getByTestId(`label-input-${DOC_ROLE}`), {
      target: { value: "   " },
    });
    fireEvent.change(screen.getByTestId(`label-input-${CONTACT_ROLE}`), {
      target: { value: "job title" },
    });
    fireEvent.click(screen.getByTestId("resolve-c1"));

    await waitFor(() => expect(mockApi.post).toHaveBeenCalled());
    const body = mockApi.post.mock.calls[0][1] as { resolutions: unknown[] };
    expect(body.resolutions).toHaveLength(1);
  });

  it("refuses to resolve when no label was entered at all", async () => {
    await openFirstCollision();
    fireEvent.click(screen.getByTestId("resolve-c1"));
    expect(await screen.findByTestId("lexicon-error")).toBeInTheDocument();
    expect(mockApi.post).not.toHaveBeenCalled();
  });

  it("drops the item from the queue once resolved", async () => {
    await openFirstCollision();
    fireEvent.change(screen.getByTestId(`label-input-${CONTACT_ROLE}`), {
      target: { value: "job title" },
    });
    fireEvent.click(screen.getByTestId("resolve-c1"));
    await waitFor(() =>
      expect(screen.queryByTestId("collision-c1")).not.toBeInTheDocument(),
    );
    expect(screen.getByTestId("lexicon-toast")).toHaveTextContent("survive re-extraction");
  });

  it("dismisses without recording any decision", async () => {
    await openFirstCollision();
    fireEvent.click(screen.getByTestId("dismiss-c1"));
    await waitFor(() => expect(mockApi.post).toHaveBeenCalled());
    expect(mockApi.post.mock.calls[0][1]).toEqual({
      curator_id: "arthur",
      dismiss: true,
    });
  });

  it("scans the open ontology and reloads the queue", async () => {
    mockApi.post.mockResolvedValue({ detected: 3, skipped_stopwords: 2 });
    renderOverlay();
    await screen.findByTestId("collision-c1");
    fireEvent.click(screen.getByTestId("lexicon-scan"));

    await waitFor(() =>
      expect(mockApi.post).toHaveBeenCalledWith(
        "/api/v1/ontology/lexicon/collisions/detect",
        { ontology_ids: ["o1"] },
      ),
    );
    expect(await screen.findByTestId("lexicon-toast")).toHaveTextContent("3 collisions");
    expect(mockApi.get).toHaveBeenCalledTimes(2);
  });

  it("surfaces a load failure instead of rendering an empty queue", async () => {
    mockApi.get.mockRejectedValue(new Error("backend down"));
    renderOverlay();
    expect(await screen.findByTestId("lexicon-error")).toHaveTextContent("backend down");
  });

  it("keeps the item in the queue when resolving fails", async () => {
    await openFirstCollision();
    mockApi.post.mockRejectedValue(new Error("conflict"));
    fireEvent.change(screen.getByTestId(`label-input-${CONTACT_ROLE}`), {
      target: { value: "job title" },
    });
    fireEvent.click(screen.getByTestId("resolve-c1"));
    expect(await screen.findByTestId("lexicon-error")).toHaveTextContent("conflict");
    expect(screen.getByTestId("collision-c1")).toBeInTheDocument();
  });
});
