/**
 * Focus-coverage reporting guard (FR-7.8.15).
 *
 * The canvas reports "N of M shown" upward and the parent stores it in state,
 * so every report re-renders the parent. The reducer effect that produces the
 * report re-runs whenever any of seven props changes identity — which a parent
 * re-render can easily cause. Reporting an equal-but-freshly-allocated object
 * each run therefore closes a cycle: report → render → effect → report. React
 * surfaces that as "Maximum update depth exceeded".
 *
 * The `null` case never looped, because `Object.is(null, null)` lets React bail
 * out of the update. This guard gives the populated case the same property.
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
jest.mock("sigma", () => ({ __esModule: true, default: class MockSigma {} }));

import { focusCoverageChanged } from "../SigmaCanvas";

describe("focusCoverageChanged", () => {
  it("is false for an equal-but-newly-allocated object", () => {
    // The whole point: this is the case that used to force a render every time
    // the effect ran, and the effect runs a lot.
    expect(
      focusCoverageChanged(
        { shown: 147, total: 160 },
        { shown: 147, total: 160 },
      ),
    ).toBe(false);
  });

  it("is false when both are null", () => {
    expect(focusCoverageChanged(null, null)).toBe(false);
  });

  it("is true when the shown count moves", () => {
    expect(
      focusCoverageChanged(
        { shown: 147, total: 160 },
        { shown: 148, total: 160 },
      ),
    ).toBe(true);
  });

  it("is true when the total moves", () => {
    // Same neighbourhood, bigger graph — the reading "147/160" is now wrong.
    expect(
      focusCoverageChanged(
        { shown: 147, total: 160 },
        { shown: 147, total: 900 },
      ),
    ).toBe(true);
  });

  it("is true when focus turns on", () => {
    expect(focusCoverageChanged(null, { shown: 3, total: 9 })).toBe(true);
  });

  it("is true when focus turns off", () => {
    // Must still report: otherwise the "N/M shown" badge outlives the focus
    // that produced it.
    expect(focusCoverageChanged({ shown: 3, total: 9 }, null)).toBe(true);
  });

  it("treats a zero-coverage focus as reportable, not as absence", () => {
    // 0 of 900 shown is a real and alarming reading; it is not "no focus".
    expect(focusCoverageChanged(null, { shown: 0, total: 900 })).toBe(true);
    expect(focusCoverageChanged({ shown: 0, total: 900 }, null)).toBe(true);
  });
});
