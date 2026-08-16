export type CurationStatus = "pending" | "approved" | "rejected";
export type CurationDecisionType = "approve" | "reject" | "edit" | "merge";
export type EdgeType =
  | "subclass_of"
  | "equivalent_class"
  | "has_property"
  | "rdfs_domain"
  | "rdfs_range_class"
  | "extends_domain"
  | "related_to"
  | "extracted_from"
  | "imports";

export interface OntologyClass extends CuratedLabelFields {
  _key: string;
  uri: string;
  label: string;
  description: string;
  rdf_type: string;
  confidence: number;
  status: CurationStatus;
  ontology_id: string;
  created: string;
  expired: string | null;
  /** Domain vs local tier — used by workspace "Source type" lens when present */
  tier?: string;
  /**
   * Effective-ontology annotation (Stream 1 H.12). Set when the class was
   * fetched via ``GET /api/v1/ontology/{id}/effective`` and originates in an
   * ontology *other than* the currently-open one. The canvas (H.15) renders
   * imported classes with a dashed border + dimmed fill; the class context
   * menu replaces destructive actions with "Open Source Ontology". When
   * absent (legacy per-ontology fetch path), the class is treated as owned.
   */
  source_ontology_id?: string;
  source_ontology_name?: string;
  is_imported?: boolean;
}

/**
 * A-box (assertion graph) types — FR-18.13 canvas rendering.
 *
 * Individuals are fetched on demand per class via
 * ``GET /api/v1/ontology/{id}/instance-graph?class_keys=...``, never as part of
 * the T-box graph load, so instance volume cannot swamp the canvas.
 */
export interface OntologyIndividual {
  _key: string;
  _id: string;
  label: string;
  uri?: string | null;
  status?: CurationStatus | null;
  provenance?: Array<Record<string, unknown>> | null;
  ontology_id?: string;
}

/** ``rdf_type`` edge: individual ``_from`` → ``ontology_classes`` ``_to``. */
export interface RdfTypeEdge {
  _key: string;
  _from: string;
  _to: string;
}

/** ``individual_assertion`` edge: individual → individual, carrying a predicate. */
export interface IndividualAssertion {
  _key: string;
  _from: string;
  _to: string;
  predicate?: string | null;
  provenance?: Array<Record<string, unknown>> | null;
}

export interface InstanceGraph {
  individuals: OntologyIndividual[];
  rdf_type_edges: RdfTypeEdge[];
  assertions: IndividualAssertion[];
  /** Class keys whose instance list hit the per-class cap. */
  truncated: string[];
}

/**
 * Curated-lexicon types — PRD §6.20.
 *
 * A collision is filed against a normalized label; the decision is recorded per
 * `concept_uri`, which is the only identifier stable across re-extraction.
 */
export interface CollisionOccurrence {
  concept_uri: string;
  concept_type?: string | null;
  ontology_id?: string | null;
  label?: string | null;
  description?: string | null;
  /** Which system this concept came from; only external producers can supply it. */
  source_system?: string | null;
  /** Example values — often settles the judgement faster than any description. */
  sample_values?: string[];
}

export interface LabelCollision {
  _key: string;
  scope: string;
  label: string;
  normalized_label: string;
  occurrences: CollisionOccurrence[];
  occurrence_count?: number;
  status: "open" | "resolved" | "dismissed";
  source: string;
  detected_at?: number;
  resolved_at?: number | null;
  resolved_by?: string | null;
}

export interface LabelDecision {
  concept_uri: string;
  label: string;
  description?: string | null;
  concept_type?: string | null;
  decided_by?: string | null;
  decided_at?: number | null;
}

/**
 * Annotations the read-time overlay adds to any class/property whose label was
 * curated (FR-20.4). ``label`` already carries the curated value; these say so,
 * and preserve what extraction called it.
 */
export interface CuratedLabelFields {
  curated_label?: boolean;
  extracted_label?: string | null;
  curated_by?: string | null;
  curated_at?: number | null;
}

export interface OntologyProperty extends CuratedLabelFields {
  _key: string;
  uri: string;
  label: string;
  description: string;
  domain_class: string;
  range_type: string;
  confidence: number;
  status: CurationStatus;
  ontology_id: string;
  created: string;
  expired: string | null;
}

export interface OntologyEdge {
  _key: string;
  _from: string;
  _to: string;
  type: EdgeType;
  label: string;
  confidence?: number;
  status?: CurationStatus;
  created?: string;
  expired?: string | null;
  /** Effective-ontology annotation (Stream 1 H.12). See ``OntologyClass`` notes. */
  source_ontology_id?: string;
  source_ontology_name?: string;
  is_imported?: boolean;
}

/**
 * Effective-ontology participating source — one entry per ontology in the
 * transitive ``owl:imports`` closure of the target ontology. ``_key`` is the
 * registry key. ``is_self`` is true for the target ontology row. ``depth`` is
 * the BFS distance via ``imports`` edges (0 for self). Returned by ``GET
 * /api/v1/ontology/{id}/effective`` (Stream 1 H.12).
 */
export interface EffectiveSource {
  _key: string;
  name: string;
  tier?: string | null;
  status?: string | null;
  is_self: boolean;
  depth: number;
}

export type EffectiveConflictKind =
  | "duplicate_uri"
  | "duplicate_label"
  | "subclass_cycle_via_import";

export interface EffectiveConflict {
  kind: EffectiveConflictKind;
  key: string;
  sources: {
    ontology_id: string;
    ontology_name: string;
    entity_key: string;
  }[];
  message: string;
}

/**
 * Wire shape of ``GET /api/v1/ontology/{id}/effective``. Each entity in
 * ``classes`` / ``edges`` / ``properties`` carries the standard summary
 * projection plus the optional ``source_ontology_id`` / ``source_ontology_name``
 * / ``is_imported`` annotation. ``conflicts`` surface merge-induced ambiguities
 * (Stream 1 H.13); ``etag`` powers ``If-None-Match`` revalidation.
 */
export interface EffectiveOntologyResponse {
  ontology_id: string;
  ontology_name: string;
  include: "summary" | "full";
  sources: EffectiveSource[];
  classes: OntologyClass[];
  edges: OntologyEdge[];
  properties: OntologyProperty[];
  conflicts: EffectiveConflict[];
  etag: string;
  truncated: boolean;
}

export interface CurationDecision {
  _key: string;
  run_id: string;
  entity_key: string;
  entity_type: "class" | "property" | "edge";
  decision: CurationDecisionType;
  curator_id: string;
  notes: string;
  created_at: string;
  before_state?: Record<string, unknown>;
  after_state?: Record<string, unknown>;
}

export interface StagingGraph {
  run_id: string;
  ontology_id?: string;
  classes: OntologyClass[];
  properties: OntologyProperty[];
  edges: OntologyEdge[];
}

export interface SourceChunk {
  _key: string;
  document_id: string;
  document_name: string;
  text: string;
  page?: number;
  section?: string;
  start_char?: number;
  end_char?: number;
}

export interface PromotionResult {
  promoted_classes: number;
  promoted_properties: number;
  promoted_edges: number;
  errors: string[];
}

export interface BatchDecisionRequest {
  entity_keys: string[];
  entity_type: "class" | "property" | "edge";
  decision: CurationDecisionType;
  notes?: string;
}

export interface DiffEntry {
  entity_key: string;
  entity_type: "class" | "property" | "edge";
  change_type: "added" | "removed" | "changed";
  label: string;
  fields_changed?: string[];
}

export interface StagingVsProductionDiff {
  added: DiffEntry[];
  removed: DiffEntry[];
  changed: DiffEntry[];
}

export interface OntologyRegistryEntry {
  _key: string;
  /** Display name; file-import entries may only have ``label`` until normalized server-side. */
  name?: string;
  label?: string;
  description?: string;
  tier: "domain" | "local";
  class_count: number;
  property_count: number;
  edge_count: number;
  last_updated?: string;
  updated_at?: string;
  created_at?: string;
  ontology_id: string;
  extraction_run_id?: string;
  source_document?: string;
  status: "draft" | "active" | "deprecated";
  tags?: string[];
  health_score?: number;
  /** Latest recorded release (denormalized on registry). */
  current_release_version?: string | null;
  current_release_description?: string | null;
  current_release_at?: string | null;
  /** Set after at least one release; absent means never released via this flow. */
  release_state?: "released" | string;
}

export interface SearchResult {
  _key: string;
  label?: string;
  name?: string;
  description?: string;
  ontology_id?: string;
  ontology_name?: string;
  tier?: string;
  status?: string;
  tags?: string[];
  confidence?: number;
  domain_class?: string;
  score: number;
  source: "registry" | "class" | "property";
}

export interface SearchResponse {
  query: string;
  results: {
    registry: SearchResult[];
    classes: SearchResult[];
    properties: SearchResult[];
  };
  counts: {
    registry: number;
    classes: number;
    properties: number;
  };
  offset: number;
  limit: number;
}

/* ── Quality Dashboard Types ─────────────────────────── */

export interface QualitySummary {
  ontology_count: number;
  total_classes: number;
  total_properties: number;
  avg_faithfulness: number | null;
  avg_semantic_validity: number | null;
  avg_completeness: number;
  avg_health_score: number | null;
  ontologies_with_cycles: number;
  total_orphans: number;
}

export interface SchemaMetrics {
  relationship_richness: number;
  attribute_richness: number;
  max_depth: number;
  annotation_completeness: number;
}

export interface OntologyScorecard {
  ontology_id: string;
  name: string;
  tier: string;
  health_score: number | null;
  avg_confidence: number | null;
  avg_faithfulness: number | null;
  avg_semantic_validity: number | null;
  completeness: number;
  connectivity: number;
  relationship_count: number;
  class_count: number;
  property_count: number;
  orphan_count: number;
  has_cycles: boolean;
  classes_without_properties: number;
  // Stream 15 SO.2. structural_integrity is 0-1 (UPM baseline 0.11→0.7);
  // island_* surface zero-degree "connects to nothing" classes. Optional so
  // older cached payloads / partial responses don't break the UI.
  structural_integrity?: number | null;
  island_count?: number;
  island_classes?: { key: string; label: string }[];
  estimated_cost: number | null;
  schema_metrics: SchemaMetrics | null;
}

export interface DashboardAlert {
  ontology_id: string;
  name: string;
  flag: string;
  severity: "red" | "yellow";
}

export interface QualityDashboard {
  summary: QualitySummary;
  ontologies: OntologyScorecard[];
  alerts: DashboardAlert[];
}

export interface QualitativeEvaluation {
  strengths: string[];
  weaknesses: string[];
  status?: string;
}

export interface ClassScore {
  _key: string;
  uri: string;
  label: string;
  confidence: number | null;
  faithfulness_score: number | null;
  semantic_validity_score: number | null;
}
