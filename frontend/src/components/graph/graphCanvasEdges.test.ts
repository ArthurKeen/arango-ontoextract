import type { OntologyEdge } from "@/types/curation";
import {
  buildSyntheticRdfsRangeClassEdges,
  documentKey,
  getEdgeType,
  individualKeyFromNodeId,
  individualNodeId,
  RDFS_RANGE_CLASS_LABEL_FALLBACK,
} from "./graphCanvasEdges";

describe("graphCanvasEdges", () => {
  describe("getEdgeType", () => {
    it("prefers edge_type when present on API payload", () => {
      const edge = {
        _key: "e1",
        _from: "ontology_object_properties/p1",
        _to: "ontology_classes/B",
        type: "related_to",
        label: "",
      } as OntologyEdge;
      Object.assign(edge, { edge_type: "rdfs_range_class" });
      expect(getEdgeType(edge)).toBe("rdfs_range_class");
    });
  });

  describe("documentKey", () => {
    it("returns collection key segment", () => {
      expect(documentKey("ontology_classes/Customer")).toBe("Customer");
    });
  });

  describe("buildSyntheticRdfsRangeClassEdges", () => {
    const classKeys = new Set(["Person", "Account"]);

    it("WhenY_DomainAndRangeResolved_ShouldEmitLabeledClassToClassEdge", () => {
      const edges: OntologyEdge[] = [
        {
          _key: "d1",
          _from: "ontology_object_properties/holds",
          _to: "ontology_classes/Person",
          type: "rdfs_domain",
          label: "",
        },
        {
          _key: "r1",
          _from: "ontology_object_properties/holds",
          _to: "ontology_classes/Account",
          type: "rdfs_range_class",
          label: "holds",
        },
      ];
      const syn = buildSyntheticRdfsRangeClassEdges(edges, classKeys);
      expect(syn).toEqual([
        {
          edgeKey: "r1",
          sourceClassKey: "Person",
          targetClassKey: "Account",
          label: "holds",
        },
      ]);
    });

    it("WhenY_NoMatchingRdfsDomain_ShouldEmitNothing", () => {
      const edges: OntologyEdge[] = [
        {
          _key: "r1",
          _from: "ontology_object_properties/orphan",
          _to: "ontology_classes/Account",
          type: "rdfs_range_class",
          label: "x",
        },
      ];
      expect(buildSyntheticRdfsRangeClassEdges(edges, classKeys)).toEqual([]);
    });

    it("WhenY_EmptyPropertyLabel_ShouldUseOwlObjectPropertyFallback", () => {
      const edges: OntologyEdge[] = [
        {
          _key: "d1",
          _from: "ontology_object_properties/p",
          _to: "ontology_classes/Person",
          type: "rdfs_domain",
          label: "",
        },
        {
          _key: "r1",
          _from: "ontology_object_properties/p",
          _to: "ontology_classes/Account",
          type: "rdfs_range_class",
          label: "",
        },
      ];
      const syn = buildSyntheticRdfsRangeClassEdges(edges, classKeys);
      expect(syn[0]?.label).toBe(RDFS_RANGE_CLASS_LABEL_FALLBACK);
    });
  });

  describe("buildSyntheticRdfsRangeClassEdges — soft-typed ontologies", () => {
    // SOSA/SSN declares no rdfs:domain at all; it types properties with
    // schema:domainIncludes / rangeIncludes, whose multiple values mean a
    // union. `hasFeatureOfInterest` may be used FROM an Actuation, an
    // Observation or a Sampling, and may point AT a FeatureOfInterest or a
    // Sample — six distinct legitimate uses, all of which belong on the canvas.
    const sosaKeys = new Set([
      "Actuation",
      "Observation",
      "Sampling",
      "FeatureOfInterest",
      "Sample",
    ]);

    const hasFeatureOfInterest: OntologyEdge[] = [
      ...["Actuation", "Observation", "Sampling"].map((cls, i) => ({
        _key: `d${i}`,
        _from: "ontology_object_properties/hasFeatureOfInterest",
        _to: `ontology_classes/${cls}`,
        type: "rdfs_domain",
        label: "",
      })),
      ...["FeatureOfInterest", "Sample"].map((cls, i) => ({
        _key: `r${i}`,
        _from: "ontology_object_properties/hasFeatureOfInterest",
        _to: `ontology_classes/${cls}`,
        type: "rdfs_range_class",
        label: "has feature of interest",
      })),
    ] as OntologyEdge[];

    it("draws every domain, not just the last one seen", () => {
      const syn = buildSyntheticRdfsRangeClassEdges(
        hasFeatureOfInterest,
        sosaKeys,
      );

      expect(syn).toHaveLength(6);
      expect(new Set(syn.map((e) => e.sourceClassKey))).toEqual(
        new Set(["Actuation", "Observation", "Sampling"]),
      );
      expect(new Set(syn.map((e) => e.targetClassKey))).toEqual(
        new Set(["FeatureOfInterest", "Sample"]),
      );
      expect(syn.every((e) => e.label === "has feature of interest")).toBe(
        true,
      );
    });

    it("gives each pair a distinct key so siblings cannot collide", () => {
      const syn = buildSyntheticRdfsRangeClassEdges(
        hasFeatureOfInterest,
        sosaKeys,
      );

      expect(new Set(syn.map((e) => e.edgeKey)).size).toBe(syn.length);
    });

    it("leaves the single-domain key untouched", () => {
      // The common case must keep the exact key it had before multi-domain
      // support, so nothing keyed on it downstream shifts.
      const edges: OntologyEdge[] = [
        {
          _key: "d1",
          _from: "ontology_object_properties/observes",
          _to: "ontology_classes/Sensor",
          type: "rdfs_domain",
          label: "",
        },
        {
          _key: "r1",
          _from: "ontology_object_properties/observes",
          _to: "ontology_classes/ObservableProperty",
          type: "rdfs_range_class",
          label: "observes",
        },
      ];
      const syn = buildSyntheticRdfsRangeClassEdges(
        edges,
        new Set(["Sensor", "ObservableProperty"]),
      );

      expect(syn).toHaveLength(1);
      expect(syn[0].edgeKey).toBe("r1");
    });

    it("ignores a duplicate domain rather than drawing the edge twice", () => {
      const edges: OntologyEdge[] = [
        {
          _key: "d1",
          _from: "ontology_object_properties/p",
          _to: "ontology_classes/Observation",
          type: "rdfs_domain",
          label: "",
        },
        {
          _key: "d2",
          _from: "ontology_object_properties/p",
          _to: "ontology_classes/Observation",
          type: "rdfs_domain",
          label: "",
        },
        {
          _key: "r1",
          _from: "ontology_object_properties/p",
          _to: "ontology_classes/Sample",
          type: "rdfs_range_class",
          label: "p",
        },
      ];
      const syn = buildSyntheticRdfsRangeClassEdges(edges, sosaKeys);

      expect(syn).toHaveLength(1);
    });

    it("skips a domain whose class is filtered out of the canvas", () => {
      const syn = buildSyntheticRdfsRangeClassEdges(
        hasFeatureOfInterest,
        new Set(["Observation", "FeatureOfInterest", "Sample"]),
      );

      expect(new Set(syn.map((e) => e.sourceClassKey))).toEqual(
        new Set(["Observation"]),
      );
      expect(syn).toHaveLength(2);
    });
  });

  describe("individual node ids (FR-18.13)", () => {
    it("namespaces an individual key", () => {
      expect(individualNodeId("i1")).toBe("ind:i1");
    });

    it("round-trips through individualKeyFromNodeId", () => {
      expect(individualKeyFromNodeId(individualNodeId("i1"))).toBe("i1");
    });

    it("returns null for a class node id", () => {
      // A class named "i1" must not be mistaken for individual "i1".
      expect(individualKeyFromNodeId("i1")).toBeNull();
      expect(individualKeyFromNodeId("Person")).toBeNull();
    });

    it("preserves a key that itself contains the delimiter", () => {
      expect(individualKeyFromNodeId(individualNodeId("ind:odd"))).toBe(
        "ind:odd",
      );
    });
  });
});
