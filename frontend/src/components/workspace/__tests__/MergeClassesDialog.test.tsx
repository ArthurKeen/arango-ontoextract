import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import MergeClassesDialog from "../MergeClassesDialog";
import type { OntologyClass } from "@/types/curation";

const post = jest.fn();
jest.mock("@/lib/api-client", () => ({
  api: { post: (...a: unknown[]) => post(...a) },
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
 * Merge a selection into one class (FR-7.8.22).
 *
 * Two properties carry the weight: the CURATOR picks the survivor (the system
 * never guesses, because the surviving label is a domain judgement), and the
 * irreversibility is stated rather than implied — merge is the one destructive
 * set action without a one-click undo.
 */

function cls(key: string, label: string, confidence = 0.6): OntologyClass {
  return {
    _key: key,
    uri: `http://example.org/o#${key}`,
    label,
    description: "",
    rdf_type: "owl:Class",
    confidence,
    status: "pending",
    ontology_id: "o",
    created: "",
    expired: null,
  };
}

const CLASSES = [cls("A", "Tyre", 0.5), cls("B", "Tyre Type", 0.9), cls("C", "Tire", 0.7)];

function renderDialog(over: Record<string, unknown> = {}) {
  return render(
    <MergeClassesDialog
      classKeys={["A", "B", "C"]}
      classes={CLASSES}
      curatorId="anonymous"
      onClose={jest.fn()}
      onDone={jest.fn()}
      {...over}
    />,
  );
}

describe("MergeClassesDialog", () => {
  beforeEach(() => post.mockReset());

  it("pre-selects nothing — the survivor is the curator's choice", () => {
    // Defaulting to highest confidence would silently discard the label a
    // domain expert would have kept.
    renderDialog();
    expect(screen.getByTestId("merge-submit")).toBeDisabled();
  });

  it("states the irreversibility plainly", () => {
    renderDialog();
    expect(screen.getByTestId("merge-warning")).toHaveTextContent(/cannot be undone in one click/i);
    expect(screen.getByTestId("merge-warning")).toHaveTextContent(/no un-merge/i);
  });

  it("names the survivor and what is folded in before committing", () => {
    renderDialog();
    fireEvent.click(screen.getByTestId("merge-option-A").querySelector("input")!);
    const summary = screen.getByTestId("merge-summary");
    expect(summary).toHaveTextContent("Tyre");
    expect(summary).toHaveTextContent("Tyre Type");
    expect(summary).toHaveTextContent("Tire");
  });

  it("posts the non-survivors as sources and never the target", async () => {
    post.mockResolvedValue({ target_key: "A", expired_sources: ["B", "C"], edges_recreated: 7 });
    renderDialog();
    fireEvent.click(screen.getByTestId("merge-option-A").querySelector("input")!);
    fireEvent.click(screen.getByTestId("merge-submit"));
    await waitFor(() => expect(post).toHaveBeenCalled());
    const [, body] = post.mock.calls[0] as [string, Record<string, unknown>];
    expect(body.target_key).toBe("A");
    // Order follows the alphabetical display order, which is immaterial to a
    // merge — membership is what matters.
    expect([...(body.source_keys as string[])].sort()).toEqual(["B", "C"]);
    expect(body.source_keys).not.toContain("A");
  });

  it("reports what happened, including re-pointed relationships", async () => {
    post.mockResolvedValue({ target_key: "A", expired_sources: ["B", "C"], edges_recreated: 7 });
    renderDialog();
    fireEvent.click(screen.getByTestId("merge-option-A").querySelector("input")!);
    fireEvent.click(screen.getByTestId("merge-submit"));
    const res = await screen.findByTestId("merge-result");
    expect(res).toHaveTextContent("2 retired");
    expect(res).toHaveTextContent("7 relationships re-pointed");
  });

  it("surfaces a failure instead of closing as though it worked", async () => {
    post.mockRejectedValue(new Error("boom"));
    const onDone = jest.fn();
    renderDialog({ onDone });
    fireEvent.click(screen.getByTestId("merge-option-A").querySelector("input")!);
    fireEvent.click(screen.getByTestId("merge-submit"));
    expect(await screen.findByTestId("merge-error")).toBeInTheDocument();
    expect(onDone).not.toHaveBeenCalled();
  });
});
