# ArangoDB Graph Visualizer Customizations

This directory contains JSON asset definitions for the ArangoDB Graph Visualizer, tailored to OWL/RDFS/SKOS ontology graphs in the AOE platform.

## Contents

| Directory | File | Purpose |
|-----------|------|---------|
| `themes/` | `ontology_theme.json` | Node type colors, icons, and edge styles for ontology collections |
| `actions/` | `ontology_actions.json` | Right-click canvas actions (AQL traversals for ontology exploration) |
| `queries/` | `ontology_queries.json` | Saved AQL queries for common ontology operations |

## Installation

Assets are installed into ArangoDB's internal collections (`_graphThemeStore`, `_canvasActions`, `_editor_saved_queries`, `_queries`, `_viewpoints`, `_viewpointActions`, `_viewpointQueries`) by the install script:

```bash
# Using app.config.settings (from project root):
python scripts/setup/install_visualizer.py

# Standalone with explicit connection:
python scripts/setup/install_visualizer.py --host http://localhost:8530 --db ontology_generator --password changeme

# Prune theme to only collections in the graph:
python scripts/setup/install_visualizer.py --prune
```

All operations are idempotent — safe to run repeatedly.

## Theme Node Types

- **ontology_classes** — Blue (`#3B82F6`), with conditional rules for SKOS Concepts, OWL Restrictions, Tier 2 locals, and curation status (pending/approved/rejected)
- **ontology_properties** — Purple (`#8B5CF6`), with DatatypeProperty variant in teal
- **ontology_constraints** — Orange (`#F97316`)
- **ontology_registry** — Gold (`#EAB308`)
- **documents** — Gray (`#6B7280`) for provenance traversals
- **chunks** — Light gray (`#9CA3AF`) for provenance traversals

## Canvas Actions (9 actions)

Right-click context menu actions for ontology graph exploration. All traversal queries filter current edges (`expired == 9223372036854775807`).

## Saved Queries (11 queries)

Pre-built AQL queries including hierarchy views, orphan detection, cross-tier analysis, temporal snapshots, and curation status queries.
