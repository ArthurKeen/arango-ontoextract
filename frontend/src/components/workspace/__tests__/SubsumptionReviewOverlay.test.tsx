/**
 * Subsumption review queue (PRD §6.2 FR-2.20).
 *
 * The behaviours worth pinning are the ones a curator would be hurt by:
 * the question must be legible without knowing the data model, "keep" and
 * "detach" must reach the backend as distinct rulings, and a failed ruling
 * must leave the row in the queue rather than swallowing it.
 */

import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import React from "react";
import SubsumptionReviewOverlay from "../SubsumptionReviewOverlay";
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

const AIRBAG = {
  edge_key: "e1",
  child_key: "Airbag",
  child_label: "Airbag",
  parent_key: "SRS",
  parent_label: "Supplementary Restraint System",
  relation: "part-of",
  reason: "An airbag is a component of the restraint system.",
};

function renderOverlay(
  overrides: Partial<
    React.ComponentProps<typeof SubsumptionReviewOverlay>
  > = {},
) {
  return render(
    <SubsumptionReviewOverlay
      ontologyId="o1"
      ontologyName="JLR"
      curatorId="arthur"
      onClose={jest.fn()}
      {...overrides}
    />,
  );
}

beforeEach(() => {
  jest.clearAllMocks();
  mockApi.get.mockResolvedValue({ data: [AIRBAG] });
  mockApi.post.mockResolvedValue({});
});

describe("the queue", () => {
  it("asks the question in the words the judge used", async () => {
    renderOverlay();
    // Not "subClassOf(Airbag, SRS) verdict=false" -- a curator should be able
    // to rule on this without knowing the data model.
    expect(await screen.findByText(/Is every.*a.*\?/)).toHaveTextContent(
      "Is every Airbag a Supplementary Restraint System?",
    );
  });

  it("glosses the relation code in plain English", async () => {
    renderOverlay();
    expect(await screen.findByText(/The judge says it is/)).toHaveTextContent(
      "The judge says it is part of it.",
    );
  });

  it("shows the judge's reason", async () => {
    renderOverlay();
    expect(await screen.findByTestId("reason-e1")).toHaveTextContent(
      "An airbag is a component of the restraint system.",
    );
  });

  it("says so plainly when nothing is flagged", async () => {
    mockApi.get.mockResolvedValue({ data: [] });
    renderOverlay();
    expect(await screen.findByTestId("subsumption-empty")).toBeInTheDocument();
  });

  it("surfaces a load failure instead of rendering an empty queue", async () => {
    mockApi.get.mockRejectedValue(new Error("boom"));
    renderOverlay();
    expect(await screen.findByTestId("subsumption-error")).toHaveTextContent(
      "boom",
    );
    expect(screen.queryByTestId("subsumption-empty")).not.toBeInTheDocument();
  });
});

describe("ruling", () => {
  it("detach posts the detach action with the curator's identity", async () => {
    renderOverlay();
    fireEvent.click(await screen.findByTestId("detach-e1"));
    await waitFor(() => expect(mockApi.post).toHaveBeenCalled());
    const [url, body] = mockApi.post.mock.calls[0];
    expect(url).toBe("/api/v1/ontology/o1/subsumption/e1/resolve");
    expect(body).toEqual({ action: "detach", curator_id: "arthur" });
  });

  it("keep posts the keep action", async () => {
    renderOverlay();
    fireEvent.click(await screen.findByTestId("keep-e1"));
    await waitFor(() => expect(mockApi.post).toHaveBeenCalled());
    expect(mockApi.post.mock.calls[0][1]).toEqual({
      action: "keep",
      curator_id: "arthur",
    });
  });

  it("says what detaching actually did — the class is now unparented", async () => {
    renderOverlay();
    fireEvent.click(await screen.findByTestId("detach-e1"));
    expect(await screen.findByTestId("subsumption-toast")).toHaveTextContent(
      "now has no parent",
    );
  });

  it("tells the canvas to refresh, since a ruling changes the graph", async () => {
    const onResolved = jest.fn();
    renderOverlay({ onResolved });
    fireEvent.click(await screen.findByTestId("detach-e1"));
    await waitFor(() =>
      expect(onResolved).toHaveBeenCalledWith("e1", "detach"),
    );
  });

  it("drops the ruled row from the queue", async () => {
    renderOverlay();
    fireEvent.click(await screen.findByTestId("keep-e1"));
    await waitFor(() =>
      expect(screen.queryByTestId("flagged-e1")).not.toBeInTheDocument(),
    );
  });

  it("keeps the row when the ruling fails to save", async () => {
    mockApi.post.mockRejectedValue(new Error("network down"));
    const onResolved = jest.fn();
    renderOverlay({ onResolved });
    fireEvent.click(await screen.findByTestId("detach-e1"));
    expect(await screen.findByTestId("subsumption-error")).toHaveTextContent(
      "network down",
    );
    // The row must survive: a queue that silently loses items a curator
    // believes they ruled on is worse than one that errors.
    expect(screen.getByTestId("flagged-e1")).toBeInTheDocument();
    expect(onResolved).not.toHaveBeenCalled();
  });
});

describe("dismissal", () => {
  it("closes on Escape", async () => {
    const onClose = jest.fn();
    renderOverlay({ onClose });
    await screen.findByTestId("flagged-e1");
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalled();
  });
});
