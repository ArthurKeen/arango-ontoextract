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

  const out: SyntheticRdfsRangeEdge[] = [];
  for (const edge of edges) {
    if (getEdgeType(edge) !== "rdfs_range_class") continue;
    const domainClassKeys = propertyIdToDomainClassKeys.get(edge._from);
    if (!domainClassKeys) continue;
    const rangeClassKey = documentKey(edge._to);
    if (!classKeySet.has(rangeClassKey)) continue;
    const label =
      (edge.label && edge.label.trim()) || RDFS_RANGE_CLASS_LABEL_FALLBACK;
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
      });
    }
  }
  return out;
}
