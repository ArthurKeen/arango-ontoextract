import { documentKey } from "@/lib/arangoId";
import type { OntologyEdge } from "@/types/curation";

export { documentKey };

/** Property→class edges: not drawn as class↔class links (PGT / legacy). */
export const FILTERED_FROM_CLASS_GRAPH = new Set([
  "rdfs_domain",
  "has_property",
]);

/** Shown on synthetic domain→range edges when the API omits `edge.label`. */
export const RDFS_RANGE_CLASS_LABEL_FALLBACK = "owl:ObjectProperty";

/**
 * A-box node ids are namespaced (FR-18.13): an individual `_key` and a class
 * `_key` are drawn from different collections and could otherwise collide on a
 * single React Flow node id, silently dropping one of the two nodes.
 */
export const INDIVIDUAL_NODE_PREFIX = "ind:";

export function individualNodeId(individualKey: string): string {
  return `${INDIVIDUAL_NODE_PREFIX}${individualKey}`;
}

/** Inverse of {@link individualNodeId}; returns null for class node ids. */
export function individualKeyFromNodeId(nodeId: string): string | null {
  return nodeId.startsWith(INDIVIDUAL_NODE_PREFIX)
    ? nodeId.slice(INDIVIDUAL_NODE_PREFIX.length)
    : null;
}

export function getEdgeType(edge: OntologyEdge): string {
  return ((edge as unknown as Record<string, unknown>).edge_type ??
    edge.type) as string;
}

export function isRelationshipEdgeStyle(edgeType: string): boolean {
  return edgeType === "related_to" || edgeType === "rdfs_range_class";
}

export interface SyntheticRdfsRangeEdge {
  edgeKey: string;
  sourceClassKey: string;
  targetClassKey: string;
  label: string;
  /** Label of the `owl:inverseOf` partner, when this edge stands in for a
   *  mirrored pair. Nothing is hidden — the reverse reading is still nameable
   *  in the detail panel; it just is not drawn as a second arrow. */
  inverseLabel?: string;
}

/**
 * Does this label read as the passive half of an inverse pair?
 *
 * Purely a DISPLAY heuristic for choosing which of two equivalent directions to
 * draw — it decides nothing semantic, and when it cannot tell, a stable
 * tiebreak takes over so the canvas never flickers between renders.
 *
 * The convention it keys on is near-universal in published ontologies: the
 * active member is `hasX` / `madeX` / `observes`, the passive one is `isXOf` /
 * `madeByX` / `isObservedBy`. It picks the active member for all nine of
 * SOSA's inverse pairs.
 */
export function looksLikeInverseLabel(label: string): boolean {
  return /^(is|was|are|were)\b/i.test(label.trim()) || /\bby\b/i.test(label);
}

/**
 * Draw each object property as a class→class edge, by pairing its
 * `rdfs_domain` edges with its `rdfs_range_class` edges on the same property.
 *
 * A property can have SEVERAL domains and several ranges. That is the norm for
 * ontologies typed with schema.org's `domainIncludes`/`rangeIncludes`, whose
 * multiple values mean a union: SOSA's `hasFeatureOfInterest` may be used from
 * an Actuation, an Observation OR a Sampling, and may point at a
 * FeatureOfInterest OR a Sample. So every (domain, range) pair is a real,
 * distinct way the property can be used, and all of them are drawn.
 *
 * An earlier version kept one domain per property in a plain Map, which was
 * harmless while every property had exactly one — and silently dropped all but
 * the last as soon as a soft-typed ontology was imported.
 *
 * Edge keys are suffixed with the domain key so the cross product cannot
 * collide on a single graph edge id and lose siblings.
 */
export function buildSyntheticRdfsRangeClassEdges(
  edges: OntologyEdge[],
  classKeySet: Set<string>,
): SyntheticRdfsRangeEdge[] {
  const propertyIdToDomainClassKeys = new Map<string, string[]>();
  for (const edge of edges) {
    if (getEdgeType(edge) !== "rdfs_domain") continue;
    const key = documentKey(edge._to);
    const existing = propertyIdToDomainClassKeys.get(edge._from);
    if (existing) {
      if (!existing.includes(key)) existing.push(key);
    } else {
      propertyIdToDomainClassKeys.set(edge._from, [key]);
    }
  }

  // Label of each property, so a collapsed pair can still name its reverse.
  const labelByPropertyId = new Map<string, string>();
  for (const edge of edges) {
    if (getEdgeType(edge) !== "rdfs_range_class") continue;
    const label = edge.label && edge.label.trim();
    if (label) labelByPropertyId.set(edge._from, label);
  }

  const out: SyntheticRdfsRangeEdge[] = [];
  for (const edge of edges) {
    if (getEdgeType(edge) !== "rdfs_range_class") continue;
    const domainClassKeys = propertyIdToDomainClassKeys.get(edge._from);
    if (!domainClassKeys) continue;
    const rangeClassKey = documentKey(edge._to);
    if (!classKeySet.has(rangeClassKey)) continue;
    const label =
      (edge.label && edge.label.trim()) || RDFS_RANGE_CLASS_LABEL_FALLBACK;

    // An owl:inverseOf pair states one fact in both directions. Drawing both
    // doubles the edge count for no added information: SOSA ships 35 such
    // pairs. Draw the active reading and carry the passive one as a label.
    const partnerId = inverseOfPropertyId(edge);
    let inverseLabel: string | undefined;
    if (partnerId && propertyIdToDomainClassKeys.has(partnerId)) {
      const partnerLabel = labelByPropertyId.get(partnerId);
      const mine = String(edge._from);
      // Both halves reach this line; exactly one must yield. Prefer the active
      // label; when the heuristic cannot separate them, the lower property id
      // wins, which is stable across renders and across reloads.
      const partnerIsPassive = partnerLabel
        ? looksLikeInverseLabel(partnerLabel)
        : false;
      const mineIsPassive = looksLikeInverseLabel(label);
      const iYield =
        mineIsPassive !== partnerIsPassive ? mineIsPassive : mine > partnerId;
      if (iYield) continue;
      inverseLabel = partnerLabel;
    }

    for (const domainClassKey of domainClassKeys) {
      if (!classKeySet.has(domainClassKey)) continue;
      // A self-loop (domain and range the same class) is legitimate -- SOSA's
      // `hosts` goes Platform→Platform -- and the canvas drops it later.
      out.push({
        edgeKey:
          domainClassKeys.length > 1
            ? `${edge._key}:${domainClassKey}`
            : edge._key,
        sourceClassKey: domainClassKey,
        targetClassKey: rangeClassKey,
        label,
        ...(inverseLabel ? { inverseLabel } : {}),
      });
    }
  }
  return out;
}

/** The `owl:inverseOf` partner id the API lifted onto a range edge, if any. */
function inverseOfPropertyId(edge: OntologyEdge): string | null {
  const raw = (edge as unknown as Record<string, unknown>).inverse_of_id;
  return typeof raw === "string" && raw ? raw : null;
}
