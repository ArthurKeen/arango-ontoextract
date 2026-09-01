import { fireEvent, render, screen } from "@testing-library/react";

import ConfidenceThresholdSlider from "@/components/workspace/ConfidenceThresholdSlider";
import type { OntologyClass, OntologyEdge } from "@/types/curation";

function makeClass(key: string, confidence: number): OntologyClass {
  return {
    _key: key,
    label: key,
    uri: `http://ex.org#${key}`,
    ontology_id: "ont-1",
    status: "approved",
    rdf_type: "owl:Class",
    confidence,
    description: "",
    created: "2026-05-08",
    expired: null,
  } as OntologyClass;
}

function makeEdge(key: string, confidence: number | undefined): OntologyEdge {
  return {
    _key: key,
    _from: "ontology_classes/A",
    _to: "ontology_classes/B",
    type: "subclass_of",
    label: "subclass_of",
    confidence,
  } as OntologyEdge;
}

describe("ConfidenceThresholdSlider", () => {
  const classes: OntologyClass[] = [
    makeClass("hi", 0.9),
    makeClass("med", 0.6),
    makeClass("lo", 0.3),
    makeClass("zero", 0.0),
  ];
  const edges: OntologyEdge[] = [
    makeEdge("e_hi", 0.9),
    makeEdge("e_lo", 0.4),
    makeEdge("e_unk", undefined),
  ];

  it("at threshold 0 emits null sets and shows totals in the readout", () => {
    const onClasses = jest.fn();
    const onEdges = jest.fn();
    render(
      <ConfidenceThresholdSlider
        classes={classes}
        edges={edges}
        onVisibleClassesChange={onClasses}
        onVisibleEdgesChange={onEdges}
      />,
    );

    // First emission is the initial pass at threshold=0.
    expect(onClasses).toHaveBeenLastCalledWith(null);
    expect(onEdges).toHaveBeenLastCalledWith(null);
    const counts = screen.getByTestId("confidence-threshold-counts");
    expect(counts).toHaveTextContent("Showing 4 of 4 classes");
    expect(counts).toHaveTextContent("3 of 3 edges");
    expect(screen.getByTestId("confidence-threshold-value")).toHaveTextContent(
      "0%",
    );
  });

  it("dragging to 50% keeps >=0.5 and everything unmeasured", () => {
    const onClasses = jest.fn();
    const onEdges = jest.fn();
    render(
      <ConfidenceThresholdSlider
        classes={classes}
        edges={edges}
        onVisibleClassesChange={onClasses}
        onVisibleEdgesChange={onEdges}
      />,
    );

    fireEvent.change(screen.getByTestId("confidence-threshold-input"), {
      target: { value: "50" },
    });

    const lastClassesCall = onClasses.mock.calls.at(
      -1,
    )![0] as Set<string> | null;
    const lastEdgesCall = onEdges.mock.calls.at(-1)![0] as Set<string> | null;
    expect(lastClassesCall).not.toBeNull();
    expect(lastEdgesCall).not.toBeNull();
    expect([...lastClassesCall!].sort()).toEqual(["hi", "med"]);
    // ``e_unk`` has NO confidence and is exempt: a threshold filters things
    // that were measured, and nothing measured that edge. Every class of every
    // imported ontology is in this position, so hiding them made the slider
    // empty the canvas for BFO, SKOS and schema.org at the first notch.
    expect([...lastEdgesCall!].sort()).toEqual(["e_hi", "e_unk"]);

    const counts = screen.getByTestId("confidence-threshold-counts");
    expect(counts).toHaveTextContent("Showing 2 of 4 classes");
    expect(counts).toHaveTextContent("2 of 3 edges");
    expect(counts).toHaveTextContent(/not measured/i);
  });

  it("dragging to 100% leaves only the high-confidence class visible", () => {
    const onClasses = jest.fn();
    const onEdges = jest.fn();
    render(
      <ConfidenceThresholdSlider
        classes={classes}
        edges={edges}
        onVisibleClassesChange={onClasses}
        onVisibleEdgesChange={onEdges}
      />,
    );

    fireEvent.change(screen.getByTestId("confidence-threshold-input"), {
      target: { value: "100" },
    });

    const lastClassesCall = onClasses.mock.calls.at(
      -1,
    )![0] as Set<string> | null;
    expect([...lastClassesCall!].sort()).toEqual([]); // 0.9 < 1.0
    // Even at 100% the unmeasured edge stays: it is outside the filter's
    // remit at every setting, not merely below the bar.
    const lastEdgesCall = onEdges.mock.calls.at(-1)![0] as Set<string> | null;
    expect([...lastEdgesCall!].sort()).toEqual(["e_unk"]);
  });

  it("Reset button returns to 0% and re-emits null sets", () => {
    const onClasses = jest.fn();
    const onEdges = jest.fn();
    render(
      <ConfidenceThresholdSlider
        classes={classes}
        edges={edges}
        onVisibleClassesChange={onClasses}
        onVisibleEdgesChange={onEdges}
      />,
    );

    fireEvent.change(screen.getByTestId("confidence-threshold-input"), {
      target: { value: "70" },
    });
    fireEvent.click(screen.getByTestId("confidence-threshold-reset"));

    expect(screen.getByTestId("confidence-threshold-value")).toHaveTextContent(
      "0%",
    );
    expect(onClasses).toHaveBeenLastCalledWith(null);
    expect(onEdges).toHaveBeenLastCalledWith(null);
  });

  it("clicking a tick snaps the slider to that percent", () => {
    const onClasses = jest.fn();
    const onEdges = jest.fn();
    render(
      <ConfidenceThresholdSlider
        classes={classes}
        edges={edges}
        onVisibleClassesChange={onClasses}
        onVisibleEdgesChange={onEdges}
      />,
    );

    fireEvent.click(screen.getByTestId("confidence-threshold-tick-70"));

    expect(screen.getByTestId("confidence-threshold-value")).toHaveTextContent(
      "70%",
    );
    const lastClassesCall = onClasses.mock.calls.at(
      -1,
    )![0] as Set<string> | null;
    expect([...lastClassesCall!].sort()).toEqual(["hi"]);
  });

  it("on unmount it emits null so a lens switch doesn't leave the page filtering", () => {
    const onClasses = jest.fn();
    const onEdges = jest.fn();
    const { unmount } = render(
      <ConfidenceThresholdSlider
        classes={classes}
        edges={edges}
        onVisibleClassesChange={onClasses}
        onVisibleEdgesChange={onEdges}
      />,
    );

    fireEvent.change(screen.getByTestId("confidence-threshold-input"), {
      target: { value: "70" },
    });
    onClasses.mockClear();
    onEdges.mockClear();

    unmount();

    expect(onClasses).toHaveBeenLastCalledWith(null);
    expect(onEdges).toHaveBeenLastCalledWith(null);
  });
});

describe("an entity nothing measured is exempt from the threshold", () => {
  // Every class of every imported ontology has null confidence — BFO, SKOS,
  // FOAF, schema.org, VSSo, all of them. Treating that as 0 meant one notch on
  // the slider emptied the canvas for the entire third-party library.
  const importedClasses = [
    makeClass("Continuant", undefined as unknown as number),
    makeClass("Occurrent", undefined as unknown as number),
  ];
  const importedEdges = [makeEdge("bfo_e1", undefined)];

  function emit(pct: string) {
    const onClasses = jest.fn();
    const onEdges = jest.fn();
    render(
      <ConfidenceThresholdSlider
        classes={importedClasses}
        edges={importedEdges}
        onVisibleClassesChange={onClasses}
        onVisibleEdgesChange={onEdges}
      />,
    );
    fireEvent.change(screen.getByTestId("confidence-threshold-input"), {
      target: { value: pct },
    });
    return {
      classes: onClasses.mock.calls.at(-1)![0] as Set<string> | null,
      edges: onEdges.mock.calls.at(-1)![0] as Set<string> | null,
    };
  }

  it.each(["1", "50", "100"])(
    "keeps an unmeasured ontology fully visible at %s%%",
    (pct) => {
      const { classes: c, edges: e } = emit(pct);
      expect([...c!].sort()).toEqual(["Continuant", "Occurrent"]);
      expect([...e!]).toEqual(["bfo_e1"]);
    },
  );

  it("says the threshold did not apply, rather than implying it passed", () => {
    render(
      <ConfidenceThresholdSlider
        classes={importedClasses}
        edges={importedEdges}
        onVisibleClassesChange={jest.fn()}
        onVisibleEdgesChange={jest.fn()}
      />,
    );
    fireEvent.change(screen.getByTestId("confidence-threshold-input"), {
      target: { value: "80" },
    });

    const counts = screen.getByTestId("confidence-threshold-counts");
    expect(counts).toHaveTextContent("Showing 2 of 2 classes");
    expect(counts).toHaveTextContent(/3 not measured/);
  });
});
