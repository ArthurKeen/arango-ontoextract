/**
 * An unmeasured class must not be labelled with a percentage.
 *
 * Reading `cls.confidence ?? 0` labelled every class of every imported
 * ontology "0%" — BFO rendered as 36 classes at 0%, stating a measurement
 * that was never taken and reading as the worst possible score. The node is
 * already painted off the red/amber/green ramp; the label should say nothing
 * rather than say zero.
 */

jest.mock("sigma/rendering", () => ({
  __esModule: true,
  NodeCircleProgram: class {},
  EdgeArrowProgram: class {},
  EdgeRectangleProgram: class {},
}));
jest.mock("@sigma/edge-curve", () => ({
  __esModule: true,
  EdgeCurvedArrowProgram: class {},
  indexParallelEdgesIndex: () => {},
}));
jest.mock("@sigma/node-border", () => ({
  __esModule: true,
  createNodeBorderProgram: () => class {},
}));
jest.mock("sigma", () => ({ __esModule: true, default: class {} }));

import { displayNodeLabel } from "../SigmaCanvas";
import type { OntologyClass } from "@/types/curation";

const cls = (confidence: number | null | undefined): OntologyClass =>
  ({ _key: "c", label: "continuant", confidence }) as unknown as OntologyClass;

describe("displayNodeLabel in the confidence lens", () => {
  it("appends a percentage to a measured class", () => {
    expect(displayNodeLabel(cls(0.92), "confidence")).toBe("continuant 92%");
  });

  it("still shows a genuine zero", () => {
    // Measured-and-zero is a real result and must remain visible as one.
    expect(displayNodeLabel(cls(0), "confidence")).toBe("continuant 0%");
  });

  it.each([[null], [undefined], [NaN]])(
    "says nothing rather than 0%% for %p",
    (value) => {
      expect(displayNodeLabel(cls(value as number | null), "confidence")).toBe(
        "continuant",
      );
    },
  );

  it("never appends outside the confidence lens", () => {
    expect(displayNodeLabel(cls(0.92), "semantic")).toBe("continuant");
  });
});
