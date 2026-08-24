/**
 * Which ontology owns an entity, as opposed to which one is open.
 *
 * When an ontology imports another (Stream 1 H.12) the canvas renders the
 * imported classes and edges alongside the owned ones, but every single-entity
 * endpoint is scoped to the ontology in its path. Asking the importing
 * ontology for a class it merely imports returns 404 -- opening a "Vehicle
 * Ontology" that imports VSSo and selecting any node on the canvas produced
 * exactly that against ``GET /ontology/{open}/classes/{key}``.
 *
 * The effective-graph payload stamps ``source_ontology_id`` on every imported
 * row; owned entities do not carry it, so the open ontology is the correct
 * fallback. Note this applies to the CANVAS selection path only: the sidebar
 * lists owned classes exclusively and its own cross-ontology clicks switch the
 * active ontology before fetching.
 */
export function owningOntologyId(
  entity: { source_ontology_id?: string } | null | undefined,
  openOntologyId: string | null,
): string | null {
  return entity?.source_ontology_id || openOntologyId;
}
