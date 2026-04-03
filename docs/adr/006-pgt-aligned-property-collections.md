# ADR-006: Align Property Storage with ArangoRDF PGT Collection Model

**Status:** Accepted
**Date:** 2026-04-02
**Decision Makers:** Arthur Keen, AOE team
**Context Branch:** `object-centric-ux`

## Context

AOE has two paths for getting ontology data into ArangoDB:

1. **LLM Extraction Pipeline** — Extracts classes and properties from documents, stores them in `ontology_classes` and `ontology_properties` collections.
2. **ArangoRDF PGT Import** — Imports OWL/TTL files via ArangoRDF's Property Graph Transformation, which creates type-based collections (`owl_Class`, `owl_ObjectProperty`, `owl_DatatypeProperty`, etc.).

These two paths produce **incompatible schemas**:

| Aspect | Extraction Pipeline | ArangoRDF PGT |
|--------|-------------------|---------------|
| Classes | `ontology_classes` (single collection) | `owl_Class` (own collection) |
| Object Properties | `ontology_properties` (mixed with datatypes, `rdf_type` field differentiates) | `owl_ObjectProperty` (own collection) |
| Datatype Properties | `ontology_properties` (same collection) | `owl_DatatypeProperty` (own collection) |
| Domain/Range | String fields on property document (`domain_class`, `range`) | `rdfs_domain` and `rdfs_range` edge collections |
| Inter-class edges | `related_to` edge (denormalized shortcut) | Traversal via `rdfs_domain` → Property → `rdfs_range` |

### Problems with Current Approach

1. **Schema mismatch** — Imported and extracted ontologies live in different collections, making unified queries impossible without UNION across collection sets.

2. **Semantic incorrectness** — OWL 2 defines `owl:ObjectProperty` and `owl:DatatypeProperty` as distinct types, not subtypes of a generic "property." Mixing them in one collection loses this type distinction.

3. **Domain/Range as string fields** — Storing `domain_class: "Customer"` and `range: "xsd:string"` as strings instead of graph edges means you can't traverse from a property to its domain/range class without string matching. This defeats the purpose of a graph database.

4. **LLM extraction confusion** — The prompt asks for a single `properties` array containing both attributes and relationships. The LLM conflates them because the schema doesn't structurally distinguish them. Developers are confused about what constitutes a "property."

5. **`related_to` is a workaround** — The `related_to` edge was created as a shortcut for inter-class relationships because the proper `domain→ObjectProperty→range` traversal path doesn't exist.

## Decision

**Align the extraction pipeline's storage model with ArangoRDF PGT's collection-per-type pattern, using AOE's own collection naming convention.**

### New Collection Schema

#### Vertex Collections

| Collection | Contents | Key Fields |
|-----------|----------|-----------|
| `ontology_classes` | `owl:Class` instances (unchanged) | `_key`, `uri`, `label`, `description`, `ontology_id`, `confidence`, `rdf_type`, `status`, `created`, `expired` |
| `ontology_object_properties` | `owl:ObjectProperty` instances (inter-class relationships) | `_key`, `uri`, `label`, `description`, `ontology_id`, `confidence`, `status`, `created`, `expired` |
| `ontology_datatype_properties` | `owl:DatatypeProperty` instances (class attributes) | `_key`, `uri`, `label`, `description`, `ontology_id`, `range_datatype` (e.g., `xsd:string`), `confidence`, `status`, `created`, `expired` |

#### Edge Collections

| Collection | From | To | Purpose |
|-----------|------|-----|---------|
| `subclass_of` | `ontology_classes` | `ontology_classes` | `rdfs:subClassOf` hierarchy (unchanged) |
| `rdfs_domain` | `ontology_object_properties` OR `ontology_datatype_properties` | `ontology_classes` | Links a property to its domain class |
| `rdfs_range_class` | `ontology_object_properties` | `ontology_classes` | Links an object property to its range class |
| `rdfs_range_datatype` | `ontology_datatype_properties` | (literal, stored as field) | N/A — datatype range stored as field on the property document |
| `equivalent_class` | `ontology_classes` | `ontology_classes` | `owl:equivalentClass` (unchanged) |
| `extends_domain` | `ontology_classes` | `ontology_classes` | AOE-specific cross-tier extension (unchanged) |
| `extracted_from` | `ontology_classes` | `documents` | Provenance (unchanged) |

**Note:** `has_property` and `related_to` edge collections become **redundant** and are removed:
- `has_property` is replaced by `rdfs_domain` (the property-to-class link IS the domain edge)
- `related_to` is replaced by the `rdfs_domain → ObjectProperty → rdfs_range_class` traversal path

### Extraction Prompt Changes

The extraction prompt schema splits `properties` into `attributes` and `relationships`:

```json
{
  "classes": [
    {
      "uri": "namespace#Customer",
      "label": "Customer",
      "description": "...",
      "parent_uri": "...",
      "attributes": [
        {
          "uri": "namespace#customerName",
          "label": "Customer Name",
          "description": "...",
          "range": "xsd:string",
          "confidence": 0.9
        }
      ],
      "relationships": [
        {
          "uri": "namespace#holds",
          "label": "holds",
          "description": "Customer holds one or more Accounts",
          "target_class_uri": "namespace#Account",
          "confidence": 0.95
        }
      ]
    }
  ]
}
```

### PGT Import Mapping

When importing via ArangoRDF PGT, the post-import step maps PGT collections to AOE collections:

| PGT Collection | AOE Collection |
|---------------|---------------|
| `owl_Class` | `ontology_classes` |
| `owl_ObjectProperty` | `ontology_object_properties` |
| `owl_DatatypeProperty` | `ontology_datatype_properties` |
| `rdfs_subClassOf` | `subclass_of` |
| `rdfs_domain` | `rdfs_domain` |
| `rdfs_range` | `rdfs_range_class` (for object properties) or field update (for datatype properties) |

### Graph Traversal Patterns

**"What relationships does Customer have?"**
```aql
FOR prop IN ontology_object_properties
  FOR e IN rdfs_domain
    FILTER e._to == "ontology_classes/Customer" AND e.expired == NEVER_EXPIRES
    FILTER prop._id == e._from AND prop.expired == NEVER_EXPIRES
    FOR range_edge IN rdfs_range_class
      FILTER range_edge._from == prop._id
      LET target = DOCUMENT(range_edge._to)
      RETURN { property: prop.label, target_class: target.label }
```

**"What attributes does Customer have?"**
```aql
FOR prop IN ontology_datatype_properties
  FOR e IN rdfs_domain
    FILTER e._to == "ontology_classes/Customer" AND e.expired == NEVER_EXPIRES
    FILTER prop._id == e._from AND prop.expired == NEVER_EXPIRES
    RETURN { attribute: prop.label, datatype: prop.range_datatype }
```

## Impact

### Files Affected

| Area | Changes Required |
|------|-----------------|
| **Extraction prompt** | Split `properties` into `attributes` + `relationships` |
| **Pydantic models** | New `ExtractedAttribute`, `ExtractedRelationship` models replacing `ExtractedProperty` |
| **Consistency checker** | Merge attributes and relationships separately across passes |
| **Materialization** | Write to `ontology_object_properties` + `ontology_datatype_properties` + `rdfs_domain` + `rdfs_range_class` |
| **Quality metrics** | Update queries — `has_property` → `rdfs_domain`, connectivity uses `rdfs_range_class` instead of `related_to` |
| **Confidence scoring** | `_structural_score` queries new edge collections |
| **Graph visualization** | Render object properties as labeled edges between classes (using `rdfs_domain`/`rdfs_range_class` traversal) |
| **Import bridge** | Map PGT collections to AOE collections post-import |
| **Migrations** | Create new collections, migrate existing data |
| **Named graphs** | Update edge definitions |
| **API endpoints** | Update class detail, edge listing, export |
| **Tests** | Update all property-related tests |

### Migration Path

1. Create new collections (`ontology_object_properties`, `ontology_datatype_properties`, `rdfs_domain`, `rdfs_range_class`)
2. Migrate existing `ontology_properties` data:
   - `rdf_type == "owl:ObjectProperty"` → `ontology_object_properties` + create `rdfs_domain` and `rdfs_range_class` edges
   - `rdf_type == "owl:DatatypeProperty"` → `ontology_datatype_properties` + create `rdfs_domain` edge
3. Migrate existing `has_property` edges → `rdfs_domain` edges
4. Remove `related_to` edges (replaced by domain→range traversal)
5. Drop old `ontology_properties`, `has_property`, `related_to` collections

## Consequences

### Positive
- Unified schema between imported and extracted ontologies
- Structurally correct OWL representation
- Graph-native domain/range traversal (no string matching)
- Cleaner extraction prompt (attributes vs relationships are explicit)
- No more `_is_object_property()` inference heuristics
- Entity resolution can match object properties across ontologies
- Export produces cleaner OWL (domain/range are proper triples, not reconstructed from strings)

### Negative
- Significant refactor (~20 files, migration required)
- Queries become slightly more complex (2 hops for property lookup instead of 1)
- Existing extracted ontologies need data migration
- Temporary dual-schema support during migration period

### Neutral
- Collection count increases (but each collection is more focused)
- Named graph definitions need updating
- ArangoDB Visualizer themes/queries need updating

## Alternatives Considered

1. **Tag-and-filter** — Keep `ontology_properties` but add better tagging. Rejected: papering over a structural problem.
2. **Use PGT collection names directly** (`owl_Class`, `owl_ObjectProperty`). Rejected: we want AOE-controlled naming that's clearer for non-RDF developers.
3. **Normalize PGT output into current schema on import** — copy PGT collections into `ontology_properties`. Rejected: loses the structural distinction and requires ongoing mapping.
