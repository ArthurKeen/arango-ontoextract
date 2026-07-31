/**
 * Tests for ``IndividualsOverlay`` (Stream 21 AB-PR6, A-box instance lens).
 */

import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import IndividualsOverlay from "../IndividualsOverlay";

const apiGet = jest.fn();
const apiPost = jest.fn();

jest.mock("@/lib/api-client", () => ({
  api: {
    get: (...a: unknown[]) => apiGet(...a),
    post: (...a: unknown[]) => apiPost(...a),
  },
  ApiError: class ApiError extends Error {
    public readonly status: number;
    public readonly body: { code: string; message: string };
    constructor(status = 500, body = { code: "X", message: "stub" }) {
      super(body.message);
      this.status = status;
      this.body = body;
    }
  },
}));

beforeEach(() => {
  apiGet.mockReset();
  apiPost.mockReset();
  apiPost.mockResolvedValue({});
});

function renderOverlay() {
  return render(
    <IndividualsOverlay ontologyId="o1" ontologyName="Alpha" onClose={jest.fn()} />,
  );
}

test("lists individuals with type + provenance count", async () => {
  apiGet.mockResolvedValue({
    data: [
      {
        _key: "i1",
        label: "Acme Corp",
        type_label: "Organization",
        type_key: "Org",
        provenance: [{ doc_id: "d1" }, { doc_id: "d2" }],
      },
      { _key: "i2", label: "Bob", type_label: "Person", type_key: "Per", provenance: [] },
    ],
  });
  renderOverlay();

  expect(await screen.findByTestId("individual-i1")).toHaveTextContent("Acme Corp");
  expect(screen.getByTestId("individual-type-i1")).toHaveTextContent("Organization");
  expect(screen.getByTestId("individual-i1")).toHaveTextContent("📎 2");
  expect(apiGet.mock.calls[0][0]).toBe("/api/v1/ontology/o1/individuals?limit=500");
});

test("empty state when no individuals", async () => {
  apiGet.mockResolvedValue({ data: [] });
  renderOverlay();
  expect(await screen.findByTestId("individuals-empty")).toBeInTheDocument();
});

test("surfaces an error", async () => {
  apiGet.mockRejectedValue(new Error("boom"));
  renderOverlay();
  expect(await screen.findByTestId("individuals-error")).toHaveTextContent("boom");
});

test("approve posts curate action and shows an approved badge", async () => {
  apiGet.mockResolvedValue({
    data: [{ _key: "i1", label: "Acme", type_label: "Org", provenance: [] }],
  });
  renderOverlay();
  fireEvent.click(await screen.findByTestId("individual-approve-i1"));

  await waitFor(() =>
    expect(apiPost).toHaveBeenCalledWith("/api/v1/ontology/individuals/i1/curate", {
      action: "approve",
    }),
  );
  expect(await screen.findByTestId("individual-status-i1")).toHaveTextContent("approved");
});

test("reject soft-deletes the row from the live list", async () => {
  apiGet.mockResolvedValue({
    data: [
      { _key: "i1", label: "Acme", type_label: "Org", provenance: [] },
      { _key: "i2", label: "Bob", type_label: "Person", provenance: [] },
    ],
  });
  renderOverlay();
  fireEvent.click(await screen.findByTestId("individual-reject-i1"));

  await waitFor(() =>
    expect(apiPost).toHaveBeenCalledWith("/api/v1/ontology/individuals/i1/curate", {
      action: "reject",
    }),
  );
  await waitFor(() => expect(screen.queryByTestId("individual-i1")).not.toBeInTheDocument());
  expect(screen.getByTestId("individual-i2")).toBeInTheDocument();
});

test("edit posts the new label and updates the row", async () => {
  apiGet.mockResolvedValue({
    data: [{ _key: "i1", label: "Acme", type_label: "Org", provenance: [] }],
  });
  renderOverlay();
  fireEvent.click(await screen.findByTestId("individual-edit-i1"));
  fireEvent.change(screen.getByTestId("individual-edit-input-i1"), {
    target: { value: "Acme, Inc." },
  });
  fireEvent.click(screen.getByTestId("individual-edit-save-i1"));

  await waitFor(() =>
    expect(apiPost).toHaveBeenCalledWith("/api/v1/ontology/individuals/i1/curate", {
      action: "edit",
      label: "Acme, Inc.",
    }),
  );
  expect(await screen.findByTestId("individual-i1")).toHaveTextContent("Acme, Inc.");
});
