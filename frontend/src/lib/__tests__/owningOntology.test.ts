/**
 * Owning-ontology resolution for single-entity fetches (Stream 1 H.12).
 *
 * The canvas of an ontology that imports another renders both sets of nodes,
 * but the detail endpoints are scoped to the ontology in the path. Getting this
 * wrong is a 404 on every imported node the user clicks.
 */

import { owningOntologyId } from "../owningOntology";

describe("owningOntologyId", () => {
  it("routes an imported entity to the ontology that owns it", () => {
    expect(
      owningOntologyId({ source_ontology_id: "vsso" }, "ont_vehicle"),
    ).toBe("vsso");
  });

  it("routes an owned entity to the open ontology", () => {
    // Owned rows carry no source_ontology_id at all.
    expect(owningOntologyId({}, "ont_vehicle")).toBe("ont_vehicle");
  });

  it("falls back when the entity is missing entirely", () => {
    // The selected key can briefly outlive the class list during a reload;
    // that must not blank the fetch target.
    expect(owningOntologyId(undefined, "ont_vehicle")).toBe("ont_vehicle");
    expect(owningOntologyId(null, "ont_vehicle")).toBe("ont_vehicle");
  });

  it("treats an empty source id as absent rather than as an ontology", () => {
    expect(owningOntologyId({ source_ontology_id: "" }, "ont_vehicle")).toBe(
      "ont_vehicle",
    );
  });

  it("propagates a null open ontology instead of inventing one", () => {
    // Nothing open and nothing owning: the caller must not fetch, and the
    // render guard keys off exactly this null.
    expect(owningOntologyId(undefined, null)).toBeNull();
  });
});
