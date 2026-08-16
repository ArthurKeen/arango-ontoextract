import { documentKey } from "@/lib/arangoId";
import type { OntologyEdge } from "@/types/curation";

export { documentKey };

/** Property→class edges: not drawn as class↔class links (PGT / legacy). */
export const FILTERED_FROM_CLASS_GRAPH = new Set(["rdfs_domain", "has_property"]);

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
  return ((edge as unknown as Record<string, unknown>).edge_type ?? edge.type) as string;
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
 * For each `rdfs_range_class` edge, resolve domain class via matching `rdfs_domain` on the same property `_from`.
 */
export function buildSyntheticRdfsRangeClassEdges(
  edges: OntologyEdge[],
  classKeySet: Set<string>,
): SyntheticRdfsRangeEdge[] {
  const propertyIdToDomainClassKey = new Map<string, string>();
  for (const edge of edges) {
    if (getEdgeType(edge) !== "rdfs_domain") continue;
    propertyIdToDomainClassKey.set(edge._from, documentKey(edge._to));
  }

  const out: SyntheticRdfsRangeEdge[] = [];
  for (const edge of edges) {
    if (getEdgeType(edge) !== "rdfs_range_class") continue;
    const domainClassKey = propertyIdToDomainClassKey.get(edge._from);
    if (!domainClassKey) continue;
    const rangeClassKey = documentKey(edge._to);
    if (!classKeySet.has(domainClassKey) || !classKeySet.has(rangeClassKey)) continue;
    const label =
      (edge.label && edge.label.trim()) || RDFS_RANGE_CLASS_LABEL_FALLBACK;
    out.push({
      edgeKey: edge._key,
      sourceClassKey: domainClassKey,
      targetClassKey: rangeClassKey,
      label,
    });
  }
  return out;
}
