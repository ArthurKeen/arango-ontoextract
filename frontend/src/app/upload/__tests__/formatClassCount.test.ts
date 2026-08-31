/**
 * The target-ontology picker rendered `{o.class_count} classes`, which printed
 * "( classes)" — an empty slot where the number belongs — for every IMPORTED
 * ontology, because only the extraction path ever wrote `class_count` to the
 * registry. The backend now derives the count; this keeps the UI honest if it
 * is ever absent again.
 */

import { classCountPhrase, formatClassCount } from "../formatClassCount";

describe("formatClassCount", () => {
  it("renders a plain count", () => {
    expect(formatClassCount(516)).toBe(" (516 classes)");
  });

  it("shows zero, because empty is a real answer", () => {
    // "Vehicle Ontology" is created empty and filled by a later extraction.
    // Zero tells the curator that; nothing at all does not.
    expect(formatClassCount(0)).toBe(" (0 classes)");
  });

  it("says one class, not one classes", () => {
    expect(formatClassCount(1)).toBe(" (1 class)");
  });

  it.each([[null], [undefined], [NaN]])(
    "renders nothing at all for %p rather than empty brackets",
    (value) => {
      expect(formatClassCount(value as number | null | undefined)).toBe("");
    },
  );
});

describe("classCountPhrase", () => {
  it("returns the bare phrase for embedding in a longer label", () => {
    // The Base Ontologies picker reads "Name (516 classes, local)" — it needs
    // the phrase without brackets, and must not slice up the formatted string.
    expect(classCountPhrase(516)).toBe("516 classes");
    expect(classCountPhrase(1)).toBe("1 class");
    expect(classCountPhrase(0)).toBe("0 classes");
  });

  it("returns null when unknown, so callers can say so in their own words", () => {
    expect(classCountPhrase(null)).toBeNull();
    expect(classCountPhrase(undefined)).toBeNull();
    expect(classCountPhrase(NaN)).toBeNull();
  });
});
