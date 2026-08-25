"""Schema extraction from external ArangoDB databases (graph schema → ontology).

Two paths, picked automatically:

1. **Direct (built-in, default)** — connect to the target ArangoDB, walk its
   named graphs + loose collections, and emit OWL/Turtle directly:
     * Document collection           → ``owl:Class``
     * Edge collection (in a graph)  → ``owl:ObjectProperty`` with
       ``rdfs:domain`` / ``rdfs:range`` resolved from the graph's edge
       definition (``from`` / ``to`` vertex collections).
     * Loose edge collection         → ``owl:ObjectProperty`` without
       domain / range (no graph context to resolve them).
     * Sampled scalar fields         → ``owl:DatatypeProperty`` with
       ``rdfs:domain`` set to the collection's class and ``rdfs:range``
       inferred from the sampled value's XSD type.
     * Selected existing ontologies  → ``owl:imports`` triples on the
       generated ontology resource (PR 1 S.10 — wires to AOE's
       ``imports`` edges via the standard post-import sync).
     * Per-class provenance          → after the OWL is imported, every
       generated class is stamped with ``source_db`` + ``source_collection``
       so curators can trace back to the originating ArangoDB collection.

2. **schema_analyzer-driven (optional enhancement)** — when the optional
   ``arangodb-schema-analyzer`` library is installed, ``_run_schema_mapper_extract``
   delegates extraction + OWL export to it. This path is preserved for
   backward compatibility but is **no longer the primary mode** — the
   library was person-record-focused historically and the direct path
   now provides richer ontology-class semantics (named-graph awareness,
   provenance, auto-imports).

This module is **graph-schema extraction**, distinct from the
document → chunk → LangGraph pipeline.
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum
from typing import Any, Literal, cast

from pydantic import BaseModel, Field

from app.db.client import get_db
from app.db.temporal_constants import NEVER_EXPIRES
from app.db.utils import run_aql
from app.services.ontology_import import import_from_file

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


class SchemaExtractionConfig(BaseModel):
    """Connection and options for schema extraction from an external ArangoDB."""

    target_host: str = Field(..., description="ArangoDB host URL (e.g. http://host:8530)")
    target_db: str = Field(..., description="Database name to introspect")
    target_user: str = Field(default="root", description="ArangoDB username")
    target_password: str = Field(default="", description="ArangoDB password")
    verify_tls: bool = Field(
        default=True,
        description="Verify TLS certificates when using HTTPS (python-arango verify_override).",
    )
    extraction_source: Literal["arango_graph_schema"] = Field(
        default="arango_graph_schema",
        description=(
            "Reverse-engineer from live graph schema; document-based extraction uses other APIs."
        ),
    )
    sample_limit_per_collection: int = Field(
        default=5,
        ge=0,
        description="Documents/edges to sample per collection for schema_analyzer snapshot.",
    )
    # Stream 5 PR 1 S.7 + S.8: named-graph-aware direct extraction. When
    # ``graph_names`` is None we walk *every* named graph plus loose
    # collections; when set, only the listed graphs are extracted (loose
    # collections still emit as classless objects unless ``include_loose``
    # is also False).
    graph_names: list[str] | None = Field(
        default=None,
        description=(
            "Optional list of named graphs to extract. When None, all named graphs are walked. "
            "Loose collections (not in any graph) are included by default; set "
            "``include_loose=False`` to skip them."
        ),
    )
    include_loose: bool = Field(
        default=True,
        description=(
            "When False, loose collections (not in any named graph) are skipped. "
            "Has no effect on the schema_analyzer path."
        ),
    )
    # Stream 5 PR 1 S.8: scalar field sampling. The direct path samples
    # ``field_sample_limit`` documents per collection, infers an XSD
    # type from the value, and emits an ``owl:DatatypeProperty``. Set
    # ``sample_fields=False`` for a pure topology-only extraction.
    sample_fields: bool = Field(
        default=True,
        description="When False, do not sample documents for datatype properties.",
    )
    field_sample_limit: int = Field(
        default=10,
        ge=0,
        le=1000,
        description="Documents to sample per collection when inferring field XSD types.",
    )
    # Stream 5 PR 3 S.9: index + schema-validation -> SHACL constraints.
    # When True (default), the direct extractor reads every document
    # collection's schema validation rule and unique indexes and emits
    # SHACL ``sh:NodeShape`` + ``sh:PropertyShape`` triples into the
    # generated TTL. Those triples are picked up by the standard PR 3
    # SHACL importer during ``import_from_file`` so they land in
    # ``ontology_constraints`` with no separate post-import step. Set
    # ``False`` for a constraint-free reverse-engineering pass.
    extract_constraints: bool = Field(
        default=True,
        description=(
            "When True, reverse-engineer SHACL constraints from each "
            "document collection's schema validation rule (required / "
            "type / pattern / enum) and unique indexes (one-field unique "
            "-> sh:maxCount 1). Constraints land in ``ontology_constraints`` "
            "via the standard SHACL import pass."
        ),
    )
    # Stream 5 PR 1 S.10: auto-imports. Each entry is the ``ontology_id``
    # (registry ``_key``) of an existing AOE ontology to import. The
    # generated TTL embeds ``owl:imports <ontology_uri>`` triples and the
    # standard ``sync_owl_imports_edges`` pass wires the actual edges
    # post-import.
    imports: list[str] = Field(
        default_factory=list,
        description=(
            "List of existing AOE ontology IDs to import. Each becomes an "
            "``owl:imports`` triple on the generated ontology resource; the standard "
            "post-import sync wires the ``imports`` edges to the registry."
        ),
    )
    # FR-9.14 — labeled property graph (LPG) extraction. When ``lpg_mode`` is
    # True, entity/relationship *types* are read from a discriminator FIELD on a
    # single vertex/edge collection (the "one Node + one relations collection"
    # pattern) instead of one-class-per-collection: classes come from the DISTINCT
    # values of ``vertex_type_field`` and object properties from the DISTINCT
    # values of ``edge_label_field`` (domain/range inferred from sampled
    # endpoints). When the fields are None they are auto-detected. Default off, so
    # the collection-per-type mapping (FR-9.10) is unchanged.
    lpg_mode: bool = Field(
        default=False,
        description="Treat the source as a labeled property graph (types in a field, FR-9.14).",
    )
    vertex_type_field: str | None = Field(
        default=None,
        description="LPG: field on vertex docs holding the class label (auto-detect when None).",
    )
    edge_label_field: str | None = Field(
        default=None,
        description="LPG: field on edge docs holding the predicate label (auto-detect when None).",
    )
    # FR-9.15 — label formatting applied to derived class/property labels.
    label_format: Literal["raw", "title_case", "snake_case", "camel_case"] = Field(
        default="raw",
        description="Format applied to derived class/property labels (FR-9.15).",
    )
    use_llm_inference: bool = Field(
        default=False,
        description="Use LLM for semantic enrichment (requires provider SDK + API key in env).",
    )
    llm_provider: str | None = Field(
        default=None,
        description="When use_llm_inference: provider id, e.g. openai, anthropic, openrouter.",
    )
    llm_model: str | None = Field(
        default=None,
        description="Optional model name; default is provider default in schema_analyzer.",
    )
    ontology_id: str | None = Field(
        default=None,
        description="Ontology ID for the imported result; auto-generated if omitted",
    )
    ontology_label: str | None = Field(
        default=None,
        description="Human-readable label for the extracted ontology",
    )


# ---------------------------------------------------------------------------
# Run tracking
# ---------------------------------------------------------------------------


class ExtractionStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class _ExtractionRun:
    run_id: str
    config: SchemaExtractionConfig
    status: ExtractionStatus = ExtractionStatus.PENDING
    started_at: float | None = None
    completed_at: float | None = None
    error: str | None = None
    result: dict[str, Any] = field(default_factory=dict)


_runs: dict[str, _ExtractionRun] = {}


_SchemaAnalyzerComponents = tuple[
    Any,
    Callable[..., Any],
    Callable[..., Any],
    Callable[..., Any],
]


# ---------------------------------------------------------------------------
# schema_analyzer integration (optional dependency)
# ---------------------------------------------------------------------------


def _try_import_schema_mapper() -> _SchemaAnalyzerComponents | None:
    """Return (AgenticSchemaAnalyzer, export_owl, fingerprint_fn, snapshot_fn) or None."""
    try:
        from schema_analyzer import AgenticSchemaAnalyzer
        from schema_analyzer.owl_export import export_conceptual_model_as_owl_turtle
        from schema_analyzer.snapshot import fingerprint_physical_schema, snapshot_physical_schema

        return (
            AgenticSchemaAnalyzer,
            export_conceptual_model_as_owl_turtle,
            fingerprint_physical_schema,
            snapshot_physical_schema,
        )
    except ImportError:
        log.warning(
            "schema_analyzer (arangodb-schema-analyzer) not installed; "
            "schema extraction will use stub implementation"
        )
        return None


def _run_schema_mapper_extract(
    config: SchemaExtractionConfig,
    mapper: _SchemaAnalyzerComponents,
) -> tuple[str, dict[str, Any]]:
    analyzer_cls, export_owl, fingerprint_fn, snapshot_fn = mapper
    from arango.client import ArangoClient

    client = ArangoClient(hosts=config.target_host, verify_override=config.verify_tls)
    try:
        db = client.db(
            config.target_db,
            username=config.target_user,
            password=config.target_password,
        )
        snap = snapshot_fn(
            db,
            sample_limit_per_collection=config.sample_limit_per_collection,
            include_samples_in_snapshot=False,
        )
        phys_fp = fingerprint_fn(snap, include_samples=False)

        if config.use_llm_inference and config.llm_provider:
            analyzer = analyzer_cls(llm_provider=config.llm_provider, model=config.llm_model)
        elif config.use_llm_inference:
            analyzer = analyzer_cls(llm_provider="openai", model=config.llm_model)
        else:
            analyzer = analyzer_cls(llm_provider=None, api_key=None)

        analysis = analyzer.analyze_physical_schema(
            db,
            sample_limit_per_collection=config.sample_limit_per_collection,
            include_samples_in_snapshot=False,
            _snapshot=snap,
        )
        ttl = export_owl(analysis)
        meta = analysis.metadata.model_dump(by_alias=True)
        provenance: dict[str, Any] = {
            "physical_schema_fingerprint": phys_fp,
            "extraction_source": config.extraction_source,
            "schema_analyzer_metadata": meta,
        }
        return ttl, provenance
    finally:
        client.close()


# ---------------------------------------------------------------------------
# Stream 5 PR 1 — Named-graph discovery (S.6)
# ---------------------------------------------------------------------------


def _connect_target(config: SchemaExtractionConfig) -> tuple[Any, Any]:
    """Open a python-arango client + db handle for the target instance.

    Returns ``(client, db)``. The caller is responsible for calling
    ``client.close()`` -- usually via a try/finally. Kept private because
    the connection lifecycle is interleaved with extraction state.
    """
    from arango.client import ArangoClient

    client = ArangoClient(hosts=config.target_host, verify_override=config.verify_tls)
    connect_kwargs: dict[str, Any] = {"username": config.target_user}
    if config.target_password:
        connect_kwargs["password"] = config.target_password
    db = client.db(config.target_db, **connect_kwargs)
    return client, db


def list_named_graphs(config: SchemaExtractionConfig) -> dict[str, Any]:
    """Discover named graphs + loose collections on the target ArangoDB.

    Returns the shape the schema-extraction UI binds to (Stream 5 S.11):

    ::

        {
          "target_host": "http://host:8529",
          "target_db": "social",
          "graphs": [
            {
              "name": "social_graph",
              "edge_definitions": [
                {"edge_collection": "follows",
                 "from_vertex_collections": ["users"],
                 "to_vertex_collections": ["users"]}
              ],
              "vertex_collections": ["users", "posts"],
              "orphan_collections": []
            },
            ...
          ],
          "loose_collections": [
            {"name": "logs", "type": "document", "count": 12345}
          ]
        }

    "Loose" = collection that is not part of any named graph. They are
    surfaced separately so the UI can show "extract this graph, plus
    these standalone collections" -- a strict-graph-only fetch would
    hide e.g. an audit log collection the user actually wants in the
    ontology.

    Raises whatever the underlying python-arango call raises (network,
    auth) -- API layer maps these to 4xx/5xx.
    """
    client, db = _connect_target(config)
    try:
        # ``db.graphs()`` returns a list[dict] like
        #   [{"name": "...", "edge_definitions": [...], "orphan_collections": [...]}, ...]
        # The edge-definition shape uses the same `from_vertex_collections`
        # / `to_vertex_collections` keys we already use elsewhere.
        graphs_raw = cast("list[dict[str, Any]]", db.graphs())
        graphs: list[dict[str, Any]] = []
        in_graph: set[str] = set()
        for g in graphs_raw:
            edge_defs = list(g.get("edge_definitions") or [])
            vertex_cols: set[str] = set()
            for ed in edge_defs:
                vertex_cols.update(ed.get("from_vertex_collections") or [])
                vertex_cols.update(ed.get("to_vertex_collections") or [])
                edge_col = ed.get("edge_collection")
                if edge_col:
                    in_graph.add(edge_col)
            orphans = list(g.get("orphan_collections") or [])
            vertex_cols.update(orphans)
            in_graph.update(vertex_cols)
            graphs.append(
                {
                    "name": g.get("name"),
                    "edge_definitions": edge_defs,
                    "vertex_collections": sorted(vertex_cols),
                    "orphan_collections": sorted(orphans),
                }
            )

        # Anything not covered by a named graph is "loose". Type 2 = document,
        # type 3 = edge. We surface count too because the UI uses it to dim
        # collections that are likely test/log scratch (count == 0 or very
        # large) so the curator can choose to skip them.
        all_cols = cast("list[dict[str, Any]]", db.collections())
        loose: list[dict[str, Any]] = []
        for c in all_cols:
            if c.get("system"):
                continue
            name = c["name"]
            if name in in_graph:
                continue
            try:
                count_val = db.collection(name).count()
            except Exception:
                # A count() failure (eg permissions on a single collection)
                # should not abort discovery. Surface as None so the UI can
                # show "unknown" rather than crash the page.
                count_val = None
            loose.append(
                {
                    "name": name,
                    "type": "edge" if _col_is_edge(c.get("type")) else "document",
                    "count": count_val,
                }
            )
        loose.sort(key=lambda x: x["name"])

        return {
            "target_host": config.target_host,
            "target_db": config.target_db,
            "graphs": graphs,
            "loose_collections": loose,
            # FR-9.14: suggest LPG mode + prefill the discriminator fields when a
            # vertex collection encodes entity types in a field.
            "lpg": _lpg_discovery_hint(db, graphs, loose),
        }
    finally:
        client.close()


def _lpg_discovery_hint(
    db: Any, graphs: list[dict[str, Any]], loose: list[dict[str, Any]]
) -> dict[str, Any]:
    """Detect a labeled-property-graph shape for the discovery response (FR-9.14).

    Suggests LPG mode when a vertex collection carries a *categorical* type field
    (>=2 distinct values), and prefills the vertex type field + edge label field.
    """
    vertex_cols: set[str] = set()
    edge_cols: set[str] = set()
    for gd in graphs:
        vertex_cols.update(gd.get("vertex_collections") or [])
        for ed in gd.get("edge_definitions") or []:
            if ed.get("edge_collection"):
                edge_cols.add(ed["edge_collection"])
    for c in loose:
        (edge_cols if c.get("type") == "edge" else vertex_cols).add(c["name"])

    vt_field: str | None = None
    sample_types: list[str] = []
    for col in sorted(vertex_cols):
        f = _lpg_detect_field(db, col, LPG_VERTEX_TYPE_CANDIDATES, tier1=LPG_TIER1_TYPE_FIELDS)
        if not f:
            continue
        vals = sorted(set(_lpg_distinct_values(db, col, f, cap=25)))
        if vals:  # a detected type field is the LPG signal (>=1 class)
            vt_field, sample_types = f, vals[:12]
            break

    edge_field: str | None = None
    for col in sorted(edge_cols):
        f = _lpg_detect_field(db, col, LPG_EDGE_LABEL_CANDIDATES, tier1=LPG_TIER1_EDGE_FIELDS)
        if f:
            edge_field = f
            break

    return {
        "suggested": vt_field is not None,
        "vertex_type_field": vt_field,
        "edge_label_field": edge_field,
        "sample_types": sample_types,
        "candidate_vertex_fields": list(LPG_VERTEX_TYPE_CANDIDATES),
        "candidate_edge_fields": list(LPG_EDGE_LABEL_CANDIDATES),
    }


# ---------------------------------------------------------------------------
# Stream 5 PR 1 — Direct extraction (S.7 + S.8) with provenance + auto-imports
# ---------------------------------------------------------------------------


# Order matters: bool is a subclass of int in Python, so check it first.
def _infer_xsd_type(value: Any) -> str | None:
    """Map a sampled Python value to an XSD type IRI.

    Returns ``None`` for nulls, lists, dicts, or anything we can't
    confidently classify. Callers should skip emitting a datatype
    property when the inference is None (silent uncertainty is better
    than a wrong-typed ontology assertion).
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return "http://www.w3.org/2001/XMLSchema#boolean"
    if isinstance(value, int):
        return "http://www.w3.org/2001/XMLSchema#integer"
    if isinstance(value, float):
        return "http://www.w3.org/2001/XMLSchema#decimal"
    if isinstance(value, str):
        # Heuristic: an ISO-8601 date/datetime string maps to xsd:date
        # (no time component) or xsd:dateTime (has a "T" separator).
        # Anything else stays a string. We deliberately do NOT call
        # dateutil/parser here -- a permissive parser misclassifies
        # things like "1.0" or "Jan" as dates. Strict ISO 8601 only.
        #
        # CRITICAL ORDER: on Python 3.11+, ``datetime.fromisoformat``
        # ALSO accepts a bare date string ("2026-05-19") and returns
        # midnight. We don't want that -- a bare date is xsd:date,
        # not xsd:dateTime. So we check for the "T" separator first
        # and only attempt the dateTime parse when one is present.
        if "T" in value:
            try:
                datetime.fromisoformat(value)
                return "http://www.w3.org/2001/XMLSchema#dateTime"
            except ValueError:
                pass
        try:
            date.fromisoformat(value)
            return "http://www.w3.org/2001/XMLSchema#date"
        except ValueError:
            pass
        return "http://www.w3.org/2001/XMLSchema#string"
    # Lists / dicts: too ambiguous for a single XSD type. A future PR can
    # emit rdf:List for arrays of scalars and recurse for nested objects.
    return None


def _sample_collection_fields(
    db: Any,
    collection: str,
    sample_limit: int,
) -> dict[str, str]:
    """Sample ``sample_limit`` documents and infer ``{field: xsd_type}``.

    Reserved meta-fields (``_key``, ``_id``, ``_rev``, ``_from``, ``_to``)
    are skipped -- they are ArangoDB plumbing, not user data, and an
    ontology that asserts ``owl:DatatypeProperty :_key`` would be
    misleading.

    When multiple sampled values yield different inferred types for the
    same field (eg one doc has ``count: 3``, another has ``count: "n/a"``)
    we fall back to ``xsd:string`` -- the safest superset.
    """
    if sample_limit <= 0:
        return {}

    # AQL is cheaper + bypasses the python-arango cursor batching quirks
    # that show up with very small LIMITs on a server-side sample. The
    # ``KEEP`` strips meta-fields server-side instead of post-filtering
    # in Python.
    docs = list(
        run_aql(
            db,
            "FOR doc IN @@col LIMIT @lim RETURN UNSET(doc, '_key', '_id', '_rev', '_from', '_to')",
            bind_vars={"@col": collection, "lim": sample_limit},
        )
    )

    field_types: dict[str, str] = {}
    for doc in docs:
        if not isinstance(doc, dict):
            continue
        for k, v in doc.items():
            xsd = _infer_xsd_type(v)
            if xsd is None:
                continue
            prior = field_types.get(k)
            if prior is None:
                field_types[k] = xsd
            elif prior != xsd:
                # Mixed types -> fall back to string. This is conservative
                # but truthful: the curator will see "this field has
                # heterogeneous types" and can refine in the UI.
                field_types[k] = "http://www.w3.org/2001/XMLSchema#string"
    return field_types


# ---------------------------------------------------------------------------
# Stream 5 PR 3 S.9 -- ArangoDB constraints -> SHACL
# ---------------------------------------------------------------------------

# Maps JSON Schema ``type`` values to XSD IRIs. JSON Schema's ``type`` is
# the closest analogue we have to a datatype declaration in ArangoDB
# schema validation; ``format`` overrides ``type`` for string-shaped
# date / date-time / URI specialisations (matches PR 3's SHACL importer
# which writes ``sh:datatype`` as the IRI string -- order matters here).
_JSONSCHEMA_TO_XSD: dict[str, str] = {
    "string": "http://www.w3.org/2001/XMLSchema#string",
    "integer": "http://www.w3.org/2001/XMLSchema#integer",
    "number": "http://www.w3.org/2001/XMLSchema#decimal",
    "boolean": "http://www.w3.org/2001/XMLSchema#boolean",
}

# Standard JSON Schema ``format`` keywords that narrow ``type: string``
# to a more specific XSD primitive. We only map the ones a sensible
# ArangoDB user would put in a schema rule; obscure formats (e.g.
# ``uuid``, ``email``) are left as ``xsd:string`` rather than invented.
_JSONSCHEMA_FORMAT_TO_XSD: dict[str, str] = {
    "date": "http://www.w3.org/2001/XMLSchema#date",
    "date-time": "http://www.w3.org/2001/XMLSchema#dateTime",
    "time": "http://www.w3.org/2001/XMLSchema#time",
    "uri": "http://www.w3.org/2001/XMLSchema#anyURI",
}


def _jsonschema_type_to_xsd(spec: dict[str, Any]) -> str | None:
    """Map one JSON Schema property spec to an XSD IRI, or ``None`` if
    the spec describes a shape we don't model (array / object / no type).

    ``format`` wins over ``type`` for the recognised specialisations so
    ``{type: "string", format: "date-time"}`` becomes ``xsd:dateTime``,
    not ``xsd:string`` -- the curator declared the more specific type
    and we respect it.

    Returns ``None`` for arrays / nested objects / typeless specs; the
    caller treats this as "no datatype constraint to emit".
    """
    if not isinstance(spec, dict):
        return None
    fmt = spec.get("format")
    if isinstance(fmt, str) and fmt in _JSONSCHEMA_FORMAT_TO_XSD:
        return _JSONSCHEMA_FORMAT_TO_XSD[fmt]
    t = spec.get("type")
    if isinstance(t, str):
        return _JSONSCHEMA_TO_XSD.get(t)
    # JSON Schema permits ``type`` to be an array (union). We pick the
    # first non-null entry -- a union of (string|null) is the common
    # "optional" idiom and ``xsd:string`` is the right call for it.
    if isinstance(t, list):
        for entry in t:
            if isinstance(entry, str) and entry != "null":
                return _JSONSCHEMA_TO_XSD.get(entry)
    return None


def _collect_schema_validation_constraints(
    rule: dict[str, Any] | None,
) -> dict[str, list[tuple[str, Any]]]:
    """Walk a JSON Schema ``rule`` block, return per-field SHACL constraint
    tuples in the wire shape PR 3's importer expects.

    Each tuple is ``(restriction_type, restriction_value)`` where
    ``restriction_type`` is one of the PR 3 string tokens
    (``"sh:minCount"`` / ``"sh:datatype"`` / ``"sh:pattern"`` /
    ``"sh:in"``). The orchestrator that emits SHACL triples maps these
    to predicate IRIs.

    Recognised JSON Schema constructs (v1):

    * ``required: ["field1", ...]`` -> per field: ``sh:minCount 1``.
    * ``properties: {field: {type, format, pattern, enum}}``:
      * ``type`` / ``format`` -> ``sh:datatype <xsd>``.
      * ``pattern`` -> ``sh:pattern "<regex>"``.
      * ``enum: [...]`` -> ``sh:in [...]`` (stored as ``list[str]``).

    Constructs NOT yet mapped (warn-skipped at the caller because this
    helper is pure; the caller logs once per collection):

    * ``minimum`` / ``maximum`` -> would need ``sh:minInclusive`` /
      ``sh:maxInclusive`` which PR 3's importer doesn't yet recognise.
    * ``minLength`` / ``maxLength`` -> ditto for ``sh:minLength``.
    * ``additionalProperties`` -> SHACL ``sh:closed``, deferred.
    * Nested ``properties`` on object-typed fields -> needs path-based
      constraints; deferred.

    The caller is responsible for resolving each field to a property
    URI; this helper deliberately knows nothing about URIs so it can
    be unit-tested with pure dicts.
    """
    if not isinstance(rule, dict):
        return {}

    out: dict[str, list[tuple[str, Any]]] = {}

    required_raw = rule.get("required")
    required: set[str] = set()
    if isinstance(required_raw, list):
        required = {r for r in required_raw if isinstance(r, str)}

    for field_name in required:
        out.setdefault(field_name, []).append(("sh:minCount", 1))

    properties = rule.get("properties")
    if isinstance(properties, dict):
        for field_name, spec in properties.items():
            if not isinstance(field_name, str) or not isinstance(spec, dict):
                continue
            xsd = _jsonschema_type_to_xsd(spec)
            if xsd:
                out.setdefault(field_name, []).append(("sh:datatype", xsd))
            pattern = spec.get("pattern")
            if isinstance(pattern, str) and pattern:
                out.setdefault(field_name, []).append(("sh:pattern", pattern))
            enum = spec.get("enum")
            if isinstance(enum, list) and enum:
                # SHACL sh:in expects a list of values; we stringify so
                # PR 3's importer can store them as the ``list[str]``
                # shape it normalises everything else to.
                out.setdefault(field_name, []).append(("sh:in", [str(v) for v in enum]))

    return out


def _collect_unique_index_fields(indexes: list[dict[str, Any]] | None) -> set[str]:
    """Return the field names that carry a single-field unique index.

    A single-field unique index on ``email`` is the most defensible
    mapping to ``sh:maxCount 1`` (each subject has at most one email).
    Multi-field unique indexes (``unique on (firstName, lastName)``)
    don't have a clean per-property SHACL equivalent -- they're a
    composite-key uniqueness constraint, which SHACL would express via
    a custom ``sh:sparql`` shape. We deliberately skip those in v1
    rather than emit a misleading single-field constraint.

    ``primary`` indexes (auto-created on ``_key``) and ``edge``
    indexes (auto-created on ``_from`` / ``_to``) are filtered out --
    they are ArangoDB plumbing, not user-declared constraints, and
    emitting ``sh:maxCount 1`` on ``_key`` would be both redundant
    and noisy.
    """
    if not isinstance(indexes, list):
        return set()

    out: set[str] = set()
    for idx in indexes:
        if not isinstance(idx, dict):
            continue
        if idx.get("type") in {"primary", "edge"}:
            continue
        if not idx.get("unique"):
            continue
        fields = idx.get("fields")
        if not isinstance(fields, list) or len(fields) != 1:
            continue
        field = fields[0]
        if isinstance(field, str) and not field.startswith("_"):
            out.add(field)
    return out


def _read_collection_validation_and_indexes(
    db: Any,
    col_name: str,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """Best-effort fetch of one collection's schema validation rule + indexes.

    Either call can fail (collection deleted under us, permission
    denied, python-arango version drift); both failures are caught and
    surfaced as ``(None, [])`` with a structured warning so the
    extraction never aborts on constraint-fetching IO.
    """
    rule: dict[str, Any] | None = None
    indexes: list[dict[str, Any]] = []
    try:
        col = db.collection(col_name)
    except Exception:
        log.warning(
            "could not resolve collection for constraint extraction",
            extra={"collection": col_name},
            exc_info=True,
        )
        return None, []

    try:
        props = col.properties()
        if isinstance(props, dict):
            schema = props.get("schema")
            if isinstance(schema, dict):
                # ArangoDB places the JSON Schema under ``schema.rule``.
                # Some older driver versions returned the rule at the
                # top level; we accept both.
                candidate = schema.get("rule") if isinstance(schema.get("rule"), dict) else schema
                if isinstance(candidate, dict):
                    rule = candidate
    except Exception:
        log.warning(
            "could not read collection properties for constraint extraction",
            extra={"collection": col_name},
            exc_info=True,
        )

    try:
        raw_indexes = col.indexes()
        if isinstance(raw_indexes, list):
            indexes = [i for i in raw_indexes if isinstance(i, dict)]
    except Exception:
        log.warning(
            "could not read collection indexes for constraint extraction",
            extra={"collection": col_name},
            exc_info=True,
        )

    return rule, indexes


def _emit_collection_shacl_shapes(
    g: Any,
    db: Any,
    *,
    col_name: str,
    class_uri: Any,
    field_props: dict[str, Any],
    ns: Any,
    sh_ns: Any,
    aoe_ns: Any,
    config: SchemaExtractionConfig,
    bnode_factory: Any,
    collection_factory: Any,
) -> int:
    """Emit a ``sh:NodeShape`` for one document collection.

    Walks the collection's schema validation rule + indexes, groups the
    resulting constraint tuples per field, and emits one
    ``sh:PropertyShape`` per constrained field carrying all of its
    constraints. Returns the number of (field-level) constraints
    emitted (not the count of PropertyShapes).

    The shape is exactly what PR 3's SHACL importer recognises, so
    rows land in ``ontology_constraints`` with
    ``constraint_type="sh:PropertyShape"`` and
    ``import_source="shacl_shape"`` after ``import_from_file`` runs.

    Fields mentioned in the schema rule or a unique index but NOT in
    ``field_props`` (because the sampler didn't see them) trigger an
    extra ``owl:DatatypeProperty`` declaration on the fly so the
    ``sh:path`` target always exists. Without this, a fresh table
    whose schema declares ``required: ["email"]`` but has no data yet
    would import a NodeShape whose ``sh:path`` referenced a phantom
    property.
    """
    from rdflib import OWL, RDF, RDFS, Literal, URIRef

    rule, indexes = _read_collection_validation_and_indexes(db, col_name)

    schema_constraints = _collect_schema_validation_constraints(rule)
    unique_fields = _collect_unique_index_fields(indexes)

    # Merge: schema validation constraints + unique-index -> sh:maxCount 1.
    # We keep ``unique_fields`` separate first so the warn-skip list
    # below knows the difference between a schema-side miss and an
    # index-side miss.
    by_field: dict[str, list[tuple[str, Any]]] = {f: list(v) for f, v in schema_constraints.items()}
    for field_name in unique_fields:
        by_field.setdefault(field_name, []).append(("sh:maxCount", 1))

    if not by_field:
        return 0

    constraints_emitted = 0
    shape_iri = URIRef(str(class_uri) + "Shape")
    g.add((shape_iri, RDF.type, sh_ns.NodeShape))
    g.add((shape_iri, sh_ns.targetClass, class_uri))
    g.add((shape_iri, aoe_ns.sourceDb, Literal(config.target_db)))
    g.add((shape_iri, aoe_ns.sourceCollection, Literal(col_name)))

    for field_name, tuples in by_field.items():
        # Resolve the property URI. If the sampler didn't see this
        # field, mint one now so the SHACL ``sh:path`` lands somewhere
        # declared. Datatype comes from the schema rule (if it had a
        # ``sh:datatype`` constraint); otherwise leave rdfs:range
        # unset -- a downstream curator can fix it once data lands.
        prop_uri = field_props.get(field_name)
        if prop_uri is None:
            prop_uri = ns[f"{col_name}.{field_name}"]
            g.add((prop_uri, RDF.type, OWL.DatatypeProperty))
            g.add((prop_uri, RDFS.label, Literal(field_name)))
            g.add((prop_uri, RDFS.domain, class_uri))
            g.add((prop_uri, aoe_ns.sourceDb, Literal(config.target_db)))
            g.add((prop_uri, aoe_ns.sourceCollection, Literal(col_name)))
            g.add((prop_uri, aoe_ns.sourceField, Literal(field_name)))
            for kind, value in tuples:
                if kind == "sh:datatype" and isinstance(value, str):
                    g.add((prop_uri, RDFS.range, URIRef(value)))
                    break
            field_props[field_name] = prop_uri

        pshape = bnode_factory()
        g.add((shape_iri, sh_ns.property, pshape))
        g.add((pshape, sh_ns.path, prop_uri))

        for kind, value in tuples:
            if kind == "sh:minCount" and isinstance(value, int):
                g.add((pshape, sh_ns.minCount, Literal(value)))
                constraints_emitted += 1
            elif kind == "sh:maxCount" and isinstance(value, int):
                g.add((pshape, sh_ns.maxCount, Literal(value)))
                constraints_emitted += 1
            elif kind == "sh:datatype" and isinstance(value, str):
                g.add((pshape, sh_ns.datatype, URIRef(value)))
                constraints_emitted += 1
            elif kind == "sh:pattern" and isinstance(value, str):
                g.add((pshape, sh_ns.pattern, Literal(value)))
                constraints_emitted += 1
            elif kind == "sh:in" and isinstance(value, list) and value:
                head = bnode_factory()
                collection_factory(g, head, [Literal(v) for v in value])
                g.add((pshape, sh_ns["in"], head))
                constraints_emitted += 1
            else:
                # Future-proofing: a kind we know how to collect but
                # not yet emit (none today, but warn loudly if PR 3
                # adds a new kind to ``_collect_schema_validation_constraints``
                # without updating this dispatcher).
                log.warning(
                    "unknown SHACL constraint kind from schema extraction; skipped",
                    extra={
                        "collection": col_name,
                        "field": field_name,
                        "kind": kind,
                    },
                )

    log.info(
        "emitted SHACL NodeShape from collection metadata",
        extra={
            "collection": col_name,
            "constraints": constraints_emitted,
            "fields": len(by_field),
        },
    )
    return constraints_emitted


def _direct_extract_schema(
    config: SchemaExtractionConfig,
    db: Any | None = None,
) -> tuple[str, dict[str, str]]:
    """Named-graph-aware direct extraction without ``schema_analyzer``.

    Returns ``(ttl_content, uri_to_collection)`` -- the second value is
    the URI → source collection map used downstream to stamp per-class
    provenance (S.4). Kept as a pair so the caller does not have to
    re-parse the TTL to recover the mapping.

    When ``db`` is provided (tests), uses it directly; otherwise opens
    + closes its own connection via :func:`_connect_target`.
    """
    from rdflib import OWL, RDF, RDFS, XSD, BNode, Graph, Literal, Namespace, URIRef
    from rdflib.collection import Collection

    own_connection = db is None
    client = None
    if own_connection:
        client, db = _connect_target(config)
    # After this point ``db`` is guaranteed non-None, but mypy cannot
    # narrow ``Any | None`` across the conditional assignment. The
    # assert is purely a type-narrowing hint -- the runtime check is
    # also a useful belt-and-braces in case a future caller passes
    # ``None`` and skips the connect branch by accident.
    assert db is not None

    try:
        ns_str = f"http://aoe.example.org/schema/{config.target_db}#"
        ns = Namespace(ns_str)
        aoe_ns = Namespace("http://aoe.example.org/vocab#")
        sh_ns = Namespace("http://www.w3.org/ns/shacl#")
        g = Graph()
        g.bind("owl", OWL)
        g.bind("rdfs", RDFS)
        g.bind("rdf", RDF)
        g.bind("xsd", XSD)
        g.bind("schema", ns)
        g.bind("aoe", aoe_ns)
        g.bind("sh", sh_ns)

        # Ontology resource + auto-imports (S.10). Each `imports` entry is
        # an existing AOE ontology_id; we expand it to the standard AOE
        # ontology URI scheme so `sync_owl_imports_edges` can resolve it
        # against the registry post-import.
        ont_uri = URIRef(ns_str.rstrip("#"))
        g.add((ont_uri, RDF.type, OWL.Ontology))
        g.add((ont_uri, RDFS.label, Literal(f"Schema of {config.target_db}")))
        for imported_id in config.imports:
            imported_uri = URIRef(f"http://example.org/ontology/{imported_id}")
            g.add((ont_uri, OWL.imports, imported_uri))

        # We re-walk the topology inline (rather than calling
        # list_named_graphs) because that function opens its own
        # connection -- here we already hold one via _connect_target.
        # The walk logic mirrors list_named_graphs so the UI preview
        # and the actual extraction agree on what they will produce.
        graphs_raw = cast("list[dict[str, Any]]", db.graphs())
        all_cols = cast("list[dict[str, Any]]", db.collections())
        col_types: dict[str, Any] = {c["name"]: c.get("type", 2) for c in all_cols}

        # Filter graphs if config.graph_names was set.
        if config.graph_names is not None:
            wanted = set(config.graph_names)
            graphs_to_walk = [g_def for g_def in graphs_raw if g_def.get("name") in wanted]
        else:
            graphs_to_walk = list(graphs_raw)

        in_graph_cols: set[str] = set()
        in_graph_edges: set[str] = set()
        uri_to_collection: dict[str, str] = {}

        def _class_for(col: str) -> URIRef:
            uri = ns[col]
            uri_to_collection[str(uri)] = col
            if (uri, RDF.type, OWL.Class) not in g:
                g.add((uri, RDF.type, OWL.Class))
                g.add((uri, RDFS.label, Literal(col)))
                g.add((uri, RDFS.comment, Literal(f"Document collection: {col}")))
                # Provenance annotations (S.4) -- redundant with the
                # post-import stamping (which is the source of truth on
                # the AOE side), but embedding them in the TTL means
                # exported / re-imported ontologies keep provenance.
                g.add((uri, aoe_ns.sourceDb, Literal(config.target_db)))
                g.add((uri, aoe_ns.sourceCollection, Literal(col)))
            return uri

        # Walk each (selected) named graph.
        for g_def in graphs_to_walk:
            for ed in g_def.get("edge_definitions") or []:
                edge_col = ed.get("edge_collection")
                if not edge_col:
                    continue
                in_graph_edges.add(edge_col)
                from_cols = list(ed.get("from_vertex_collections") or [])
                to_cols = list(ed.get("to_vertex_collections") or [])
                for c in from_cols + to_cols:
                    in_graph_cols.add(c)
                    _class_for(c)

                obj_uri = ns[edge_col]
                uri_to_collection[str(obj_uri)] = edge_col
                g.add((obj_uri, RDF.type, OWL.ObjectProperty))
                g.add((obj_uri, RDFS.label, Literal(edge_col)))
                g.add(
                    (
                        obj_uri,
                        RDFS.comment,
                        Literal(f"Edge collection from graph '{g_def.get('name')}': {edge_col}"),
                    )
                )
                # Multi-from / multi-to edge definitions: emit one
                # rdfs:domain / rdfs:range triple per vertex collection.
                # Owl semantics treat multiple rdfs:domain as the
                # intersection in some readings, but the more common
                # interpretation in tooling is the union, which is what
                # the user expects from a graph schema.
                for fc in from_cols:
                    g.add((obj_uri, RDFS.domain, _class_for(fc)))
                for tc in to_cols:
                    g.add((obj_uri, RDFS.range, _class_for(tc)))
                g.add((obj_uri, aoe_ns.sourceDb, Literal(config.target_db)))
                g.add((obj_uri, aoe_ns.sourceCollection, Literal(edge_col)))

            for orphan in g_def.get("orphan_collections") or []:
                in_graph_cols.add(orphan)
                _class_for(orphan)

        # Loose collections (not in any walked graph). Document collections
        # become classes; edge collections become object properties with no
        # domain/range (we don't have one to assert).
        if config.include_loose:
            for c in all_cols:
                if c.get("system"):
                    continue
                name = c["name"]
                if name in in_graph_cols or name in in_graph_edges:
                    continue
                if _col_is_edge(col_types.get(name)):
                    obj_uri = ns[name]
                    uri_to_collection[str(obj_uri)] = name
                    g.add((obj_uri, RDF.type, OWL.ObjectProperty))
                    g.add((obj_uri, RDFS.label, Literal(name)))
                    g.add(
                        (
                            obj_uri,
                            RDFS.comment,
                            Literal(f"Loose edge collection (no graph context): {name}"),
                        )
                    )
                    g.add((obj_uri, aoe_ns.sourceDb, Literal(config.target_db)))
                    g.add((obj_uri, aoe_ns.sourceCollection, Literal(name)))
                else:
                    _class_for(name)

        # Datatype properties from sampled fields (S.8). One pass per
        # document collection that ended up emitted as a class. We
        # keep the (col_name -> {field -> prop_uri}) mapping in scope
        # so the constraint emission below (S.9) can resolve each
        # SHACL ``sh:path`` to the same property URI a sampled field
        # would have produced -- two passes that mention the same
        # field share one property.
        col_to_field_props: dict[str, dict[str, URIRef]] = {}
        if config.sample_fields:
            class_uris = list(g.subjects(RDF.type, OWL.Class))
            for cls_uri in class_uris:
                col_name = uri_to_collection.get(str(cls_uri))
                if not col_name:
                    continue
                if _col_is_edge(col_types.get(col_name)):
                    continue
                try:
                    fields = _sample_collection_fields(db, col_name, config.field_sample_limit)
                except Exception:
                    log.warning(
                        "field sampling failed; skipping datatype properties",
                        extra={"collection": col_name},
                        exc_info=True,
                    )
                    continue
                for fname, xsd_iri in fields.items():
                    # Field URI: scope to the source collection so two
                    # collections with a `name` field do not collide on a
                    # single :name property. The local name becomes
                    # `<Collection>.<field>` which round-trips cleanly
                    # through rdflib's Turtle serializer.
                    prop_uri = ns[f"{col_name}.{fname}"]
                    g.add((prop_uri, RDF.type, OWL.DatatypeProperty))
                    g.add((prop_uri, RDFS.label, Literal(fname)))
                    g.add((prop_uri, RDFS.domain, cls_uri))
                    g.add((prop_uri, RDFS.range, URIRef(xsd_iri)))
                    g.add((prop_uri, aoe_ns.sourceDb, Literal(config.target_db)))
                    g.add((prop_uri, aoe_ns.sourceCollection, Literal(col_name)))
                    g.add((prop_uri, aoe_ns.sourceField, Literal(fname)))
                    col_to_field_props.setdefault(col_name, {})[fname] = prop_uri

        # Stream 5 PR 3 S.9 -- index + schema-validation -> SHACL.
        # Runs after sampling so it can reuse the field -> property
        # URI map sampling built. Fields mentioned in schema validation
        # or unique indexes but NOT sampled (eg required field with no
        # data yet) get a brand-new ``owl:DatatypeProperty`` so the
        # SHACL ``sh:path`` always lands on a declared property.
        #
        # Emission shape (one NodeShape per class):
        #
        #   :CustomerShape a sh:NodeShape ;
        #       sh:targetClass :Customer ;
        #       sh:property [ sh:path :Customer.email ;
        #                     sh:minCount 1 ;
        #                     sh:datatype xsd:string ;
        #                     sh:pattern "..." ] .
        #
        # This is exactly the shape PR 3's SHACL importer recognises
        # so the constraints land in ``ontology_constraints`` with
        # ``constraint_type="sh:PropertyShape"`` and the right
        # ``import_source="shacl_shape"`` provenance marker.
        constraints_emitted = 0
        if config.extract_constraints:
            class_uris = list(g.subjects(RDF.type, OWL.Class))
            for cls_uri in class_uris:
                col_name = uri_to_collection.get(str(cls_uri))
                if not col_name or _col_is_edge(col_types.get(col_name)):
                    continue
                constraints_emitted += _emit_collection_shacl_shapes(
                    g,
                    db,
                    col_name=col_name,
                    class_uri=URIRef(str(cls_uri)),
                    field_props=col_to_field_props.setdefault(col_name, {}),
                    ns=ns,
                    sh_ns=sh_ns,
                    aoe_ns=aoe_ns,
                    config=config,
                    bnode_factory=BNode,
                    collection_factory=Collection,
                )

        ttl = g.serialize(format="turtle")
        log.info(
            "direct schema extraction complete",
            extra={
                "target_db": config.target_db,
                "triples": len(g),
                "graphs_walked": len(graphs_to_walk),
                "classes": sum(1 for _ in g.subjects(RDF.type, OWL.Class)),
                "object_properties": sum(1 for _ in g.subjects(RDF.type, OWL.ObjectProperty)),
                "datatype_properties": sum(1 for _ in g.subjects(RDF.type, OWL.DatatypeProperty)),
                "shacl_constraints_emitted": constraints_emitted,
            },
        )
        return ttl, uri_to_collection
    finally:
        if own_connection and client is not None:
            client.close()


# ---------------------------------------------------------------------------
# FR-9.14 / FR-9.15 -- labeled property graph (single-collection) extraction
# ---------------------------------------------------------------------------

# Candidate discriminator fields, in preference order, for auto-detection.
# ``type`` first: it is the arango-cypher-py / Neo4j-export convention for the
# LABEL-style type field. ``label``/``name`` come LAST because in most LPGs they
# hold the entity's *display name* (high cardinality) — the opposite of a type
# discriminator, which is what made the first cut extract one "class" per entity.
# ``entityType`` (camelCase) is the FinReflectKG / arango-cypher-py Tier-1 name;
# it was previously missing so a graph using it fell through to the fallback.
LPG_VERTEX_TYPE_CANDIDATES = (
    "type",
    "_type",
    "entityType",
    "@type",
    "entity_type",
    "category",
    "kind",
    "label",
)
LPG_EDGE_LABEL_CANDIDATES = (
    "type",
    "relation",
    "relationship",
    "relType",
    "predicate",
    "label",
)

# Tier-1 fields are unambiguously *type* discriminators (matches arango-cypher-py's
# ``_TIER1_TYPE_FIELDS``): we accept them on field COVERAGE alone. Tier-2 names
# (everything else — ``label``, ``category``, ``name`` …) can equally hold a
# free-text display name, so they must ALSO pass a low-cardinality + "class-like
# value" test before we trust them as a discriminator.
LPG_TIER1_TYPE_FIELDS = ("type", "_type", "entityType", "@type", "entity_type")
LPG_TIER1_EDGE_FIELDS = ("type", "relation", "relationship", "relType", "predicate")

# Edges may carry their endpoint *types* directly (arango-cypher-py's
# GENERIC_WITH_TYPE convention), avoiding a per-edge DOCUMENT() lookup.
LPG_EDGE_FROM_TYPE_FIELDS = ("_fromType", "fromType", "_from_type")
LPG_EDGE_TO_TYPE_FIELDS = ("_toType", "toType", "_to_type")

# A discriminator value that looks like an identifier / free text (contains a
# dot, slash, or whitespace) is not a class name. Used to reject Tier-2 fields.
_LPG_CLASS_LIKE_RE = re.compile(r"^[^\s./\\]+$")


def _col_is_edge(type_val: Any) -> bool:
    """True when a python-arango collection ``type`` denotes an edge collection.

    ``db.collections()`` reports the type as the string ``"edge"`` on current
    python-arango, while older drivers / other endpoints returned the integer
    ``3``. Accepting BOTH is essential: comparing only against ``3`` silently
    reclassifies every edge collection as a vertex collection, which produced
    one class-per-collection and zero object properties (the FinReflectKG bug).
    """
    return bool(type_val == 3 or type_val == "edge")


def _format_label(value: str, fmt: str) -> str:
    """Apply FR-9.15 label formatting to a raw discriminator value."""
    s = str(value).strip()
    if not s or fmt == "raw":
        return s
    # Insert a space at camelCase boundaries, then split on any non-alphanumeric.
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", s)
    parts = [p for p in re.split(r"[^A-Za-z0-9]+", spaced) if p]
    if not parts:
        return s
    if fmt == "title_case":
        return " ".join(p[:1].upper() + p[1:].lower() for p in parts)
    if fmt == "snake_case":
        return "_".join(p.lower() for p in parts)
    if fmt == "camel_case":
        return parts[0].lower() + "".join(p[:1].upper() + p[1:].lower() for p in parts[1:])
    return s


def _lpg_localname(value: str) -> str:
    """Namespace-safe local name for a class/predicate IRI from a raw value."""
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", str(value).strip()).strip("_")
    return cleaned or "value"


def _lpg_distinct_values(db: Any, col: str, field: str, *, cap: int = 5000) -> list[str]:
    """ALL distinct non-empty values of ``field`` across ``col`` — a full COLLECT.

    This is a full aggregation, NOT a sample: every entity/relationship *type*
    present in the graph must become a class/predicate (this is what
    arango-cypher-py does, and what the previous 500-row LIMIT sample got wrong on
    large graphs). ``cap`` is only a pathological-cardinality backstop; when it is
    hit we log so a silently-truncated type set is visible rather than mistaken
    for the complete set.
    """
    rows = list(
        run_aql(
            db,
            "FOR d IN @@col FILTER d[@f] != null COLLECT v = d[@f] LIMIT @cap RETURN v",
            bind_vars={"@col": col, "f": field, "cap": cap + 1},
        )
    )
    if len(rows) > cap:
        log.warning(
            "LPG distinct value set hit cardinality cap; type set truncated",
            extra={"collection": col, "field": field, "cap": cap},
        )
        rows = rows[:cap]
    return [str(v) for v in rows if v is not None and str(v).strip()]


def _lpg_field_stats(db: Any, col: str, field: str, *, sample: int = 2000) -> tuple[int, int, int]:
    """Return ``(sampled, present, num_distinct)`` for ``field`` over ``col``.

    ``sampled`` = docs looked at, ``present`` = those with a non-null value,
    ``num_distinct`` = distinct non-null values among them. The object keys avoid
    the AQL reserved word ``distinct`` (using it as an unquoted key is a syntax
    error — the previous version raised on every call, so detection always fell
    through to the collection-name fallback).
    """
    rows = list(
        run_aql(
            db,
            """
            LET vals = (FOR d IN @@col LIMIT @sample RETURN d[@f])
            LET present = vals[* FILTER CURRENT != null]
            RETURN {
              sampled: LENGTH(vals),
              present: LENGTH(present),
              num_distinct: LENGTH(UNIQUE(present))
            }
            """,
            bind_vars={"@col": col, "f": field, "sample": sample},
        )
    )
    if not rows or not isinstance(rows[0], dict):
        return (0, 0, 0)
    r = rows[0]
    return (
        int(r.get("sampled") or 0),
        int(r.get("present") or 0),
        int(r.get("num_distinct") or 0),
    )


def _lpg_values_class_like(db: Any, col: str, field: str, *, cap: int = 50) -> bool:
    """True when a Tier-2 field's values all look like class names (not free text).

    Rejects the entity *display name* / identifier fields (values with spaces,
    dots, slashes, or absurd length) so ``label``/``name`` is only trusted as a
    type discriminator when it actually holds class-like tokens.
    """
    vals = _lpg_distinct_values(db, col, field, cap=cap)
    if not vals:
        return False
    return all(bool(_LPG_CLASS_LIKE_RE.match(v)) and len(v) <= 60 for v in vals)


def _lpg_detect_field(
    db: Any, col: str, candidates: tuple[str, ...], *, tier1: tuple[str, ...] = ()
) -> str | None:
    """Pick a categorical *type* discriminator field, not an identifier.

    Mirrors arango-cypher-py's two-tier detector:

    * **Tier-1** (``tier1`` — ``type``/``_type``/``entityType``/``relation`` …):
      accepted on COVERAGE alone. These names are unambiguously type fields, so a
      high distinct count (many entity types) must NOT disqualify them — that was
      the bug that collapsed a rich graph into a single collection-named class.
    * **Tier-2** (everything else — ``label``/``category``/``name`` …): must also
      be low-cardinality (``distinct <= max(50, present/2)``) and hold class-like
      values, so a high-cardinality display-name field is never mistaken for a
      type (one class per entity).

    The first candidate (in preference order) that qualifies wins.
    """
    for f in candidates:
        try:
            sampled, present, distinct = _lpg_field_stats(db, col, f)
        except Exception:
            log.debug(
                "LPG field stats failed; skipping candidate",
                extra={"collection": col, "field": f},
                exc_info=True,
            )
            continue
        if sampled == 0 or present == 0 or distinct < 1:
            continue
        if present / sampled < 0.6:  # field must be broadly present to be a type
            continue
        if f in tier1:
            return f
        # Tier-2: guard against free-text / high-cardinality display names.
        if distinct < 2 or distinct > max(50, present // 2):
            continue
        if not _lpg_values_class_like(db, col, f):
            continue
        return f
    return None


def _lpg_extract_schema(
    config: SchemaExtractionConfig,
    db: Any | None = None,
) -> tuple[str, dict[str, str]]:
    """Labeled-property-graph extraction (FR-9.14): types live in a field.

    Classes are the DISTINCT values of the vertex type field; object properties
    are the DISTINCT values of the edge label field, with rdfs:domain/range
    inferred from sampled endpoint types. Returns ``(ttl, uri_to_collection)``
    like :func:`_direct_extract_schema`.
    """
    from rdflib import OWL, RDF, RDFS, XSD, Graph, Literal, Namespace, URIRef

    own_connection = db is None
    client = None
    if own_connection:
        client, db = _connect_target(config)
    assert db is not None

    try:
        ns = Namespace(f"http://aoe.example.org/schema/{config.target_db}#")
        aoe_ns = Namespace("http://aoe.example.org/vocab#")
        g = Graph()
        g.bind("owl", OWL)
        g.bind("rdfs", RDFS)
        g.bind("rdf", RDF)
        g.bind("xsd", XSD)
        g.bind("schema", ns)
        g.bind("aoe", aoe_ns)

        ont_uri = URIRef(str(ns).rstrip("#"))
        g.add((ont_uri, RDF.type, OWL.Ontology))
        g.add((ont_uri, RDFS.label, Literal(f"Schema of {config.target_db} (LPG)")))
        for imported_id in config.imports:
            g.add((ont_uri, OWL.imports, URIRef(f"http://example.org/ontology/{imported_id}")))

        # Resolve the vertex + edge collections in scope from the selected named
        # graphs' edge definitions (+ loose collections). Mirrors the direct
        # walk's topology discovery, but here each collection is an LPG store.
        graphs_raw = cast("list[dict[str, Any]]", db.graphs())
        all_cols = cast("list[dict[str, Any]]", db.collections())
        col_types = {c["name"]: c.get("type", 2) for c in all_cols}
        if config.graph_names is not None:
            wanted = set(config.graph_names)
            graphs_to_walk = [gd for gd in graphs_raw if gd.get("name") in wanted]
        else:
            graphs_to_walk = list(graphs_raw)

        vertex_cols: set[str] = set()
        edge_cols: set[str] = set()
        for gd in graphs_to_walk:
            for ed in gd.get("edge_definitions") or []:
                if ed.get("edge_collection"):
                    edge_cols.add(ed["edge_collection"])
                vertex_cols.update(ed.get("from_vertex_collections") or [])
                vertex_cols.update(ed.get("to_vertex_collections") or [])
            vertex_cols.update(gd.get("orphan_collections") or [])
        in_graph = vertex_cols | edge_cols
        if config.include_loose:
            for c in all_cols:
                if c.get("system") or c["name"] in in_graph:
                    continue
                (edge_cols if _col_is_edge(col_types.get(c["name"])) else vertex_cols).add(
                    c["name"]
                )

        type_field = config.vertex_type_field
        edge_field = config.edge_label_field
        uri_to_collection: dict[str, str] = {}
        # value (raw) -> class URI, shared across vertex collections so an edge
        # endpoint's type resolves to its class regardless of which collection.
        value_to_class: dict[str, URIRef] = {}

        # --- Classes: DISTINCT type-field values per vertex collection ---------
        for col in sorted(vertex_cols):
            tf = type_field or _lpg_detect_field(
                db, col, LPG_VERTEX_TYPE_CANDIDATES, tier1=LPG_TIER1_TYPE_FIELDS
            )
            if not tf:
                # No discriminator: fall back to one class for the collection.
                cls_uri = ns[_lpg_localname(col)]
                _lpg_add_class(
                    g, cls_uri, _format_label(col, config.label_format), col, ns, aoe_ns, config
                )
                uri_to_collection[str(cls_uri)] = col
                continue
            for raw in _lpg_distinct_values(db, col, tf):
                cls_uri = ns[_lpg_localname(raw)]
                _lpg_add_class(
                    g, cls_uri, _format_label(raw, config.label_format), col, ns, aoe_ns, config
                )
                g.add((cls_uri, aoe_ns.lpgTypeValue, Literal(raw)))
                g.add((cls_uri, aoe_ns.lpgTypeField, Literal(tf)))
                uri_to_collection[str(cls_uri)] = col
                value_to_class[raw] = cls_uri

            # Datatype properties per type (fields differ by type in an LPG).
            if config.sample_fields:
                _lpg_sample_datatype_props(g, db, col, tf, value_to_class, ns, aoe_ns, config)

        # --- Object properties: DISTINCT edge-label values per edge collection -
        for col in sorted(edge_cols):
            lf = edge_field or _lpg_detect_field(
                db, col, LPG_EDGE_LABEL_CANDIDATES, tier1=LPG_TIER1_EDGE_FIELDS
            )
            tf = type_field or _lpg_detect_field(
                db,
                next(iter(sorted(vertex_cols)), col),
                LPG_VERTEX_TYPE_CANDIDATES,
                tier1=LPG_TIER1_TYPE_FIELDS,
            )
            if not lf:
                # No label field: one object property for the whole edge collection.
                obj_uri = ns[_lpg_localname(col)]
                g.add((obj_uri, RDF.type, OWL.ObjectProperty))
                g.add((obj_uri, RDFS.label, Literal(_format_label(col, config.label_format))))
                g.add((obj_uri, aoe_ns.sourceDb, Literal(config.target_db)))
                g.add((obj_uri, aoe_ns.sourceCollection, Literal(col)))
                uri_to_collection[str(obj_uri)] = col
                continue
            pred_domains, pred_ranges = _lpg_sample_predicates(db, col, lf, tf)
            for pred in sorted(pred_domains):
                obj_uri = ns[_lpg_localname(pred)]
                g.add((obj_uri, RDF.type, OWL.ObjectProperty))
                g.add((obj_uri, RDFS.label, Literal(_format_label(pred, config.label_format))))
                g.add((obj_uri, aoe_ns.lpgLabelValue, Literal(pred)))
                g.add((obj_uri, aoe_ns.sourceDb, Literal(config.target_db)))
                g.add((obj_uri, aoe_ns.sourceCollection, Literal(col)))
                for dv in sorted(pred_domains[pred]):
                    dom = value_to_class.get(dv) or ns[_lpg_localname(dv)]
                    g.add((obj_uri, RDFS.domain, dom))
                for rv in sorted(pred_ranges.get(pred, set())):
                    rng = value_to_class.get(rv) or ns[_lpg_localname(rv)]
                    g.add((obj_uri, RDFS.range, rng))
                uri_to_collection[str(obj_uri)] = col

        ttl = g.serialize(format="turtle")
        log.info(
            "LPG schema extraction complete",
            extra={
                "target_db": config.target_db,
                "vertex_collections": sorted(vertex_cols),
                "edge_collections": sorted(edge_cols),
                "classes": sum(1 for _ in g.subjects(RDF.type, OWL.Class)),
                "object_properties": sum(1 for _ in g.subjects(RDF.type, OWL.ObjectProperty)),
                "label_format": config.label_format,
            },
        )
        return ttl, uri_to_collection
    finally:
        if own_connection and client is not None:
            client.close()


def _lpg_add_class(
    g: Any, cls_uri: Any, label: str, col: str, ns: Any, aoe_ns: Any, config: Any
) -> None:
    from rdflib import OWL, RDF, RDFS, Literal

    if (cls_uri, RDF.type, OWL.Class) in g:
        return
    g.add((cls_uri, RDF.type, OWL.Class))
    g.add((cls_uri, RDFS.label, Literal(label)))
    g.add((cls_uri, aoe_ns.sourceDb, Literal(config.target_db)))
    g.add((cls_uri, aoe_ns.sourceCollection, Literal(col)))


def _lpg_detect_endpoint_type_fields(db: Any, edge_col: str) -> tuple[str | None, str | None]:
    """Find the edge fields that carry endpoint types (``_fromType``/``_toType``)."""
    present = {str(k) for k in _lpg_edge_field_names(db, edge_col)}
    from_f = next((f for f in LPG_EDGE_FROM_TYPE_FIELDS if f in present), None)
    to_f = next((f for f in LPG_EDGE_TO_TYPE_FIELDS if f in present), None)
    return from_f, to_f


def _lpg_edge_field_names(db: Any, edge_col: str, *, sample: int = 50) -> set[str]:
    rows = run_aql(
        db,
        "FOR e IN @@col LIMIT @sample RETURN ATTRIBUTES(e, true)",
        bind_vars={"@col": edge_col, "sample": sample},
    )
    names: set[str] = set()
    for r in rows:
        if isinstance(r, list):
            names.update(str(x) for x in r)
    return names


def _lpg_sample_predicates(
    db: Any, edge_col: str, label_field: str, type_field: str | None, *, scan: int = 200_000
) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """``(predicate -> from-type set, predicate -> to-type set)`` for an edge collection.

    Two passes, mirroring arango-cypher-py:

    1. **Predicate set — FULL ``COLLECT``, never sampled.** Every relationship
       type in the collection becomes an object property, so a graph with more
       distinct predicates than any sample window is represented completely.
    2. **Endpoint (domain/range) resolution.** Endpoint types are read from the
       edge's own ``_fromType`` / ``_toType`` fields when present (the
       GENERIC_WITH_TYPE convention — no per-edge lookup); otherwise they fall
       back to ``DOCUMENT(e._from)[type_field]``. This pass groups by
       ``(predicate, from-type, to-type)`` and is bounded by ``scan`` edges only
       to cap DOCUMENT() cost on very large graphs; the predicate *set* from pass
       1 is authoritative regardless of this bound.
    """
    domains: dict[str, set[str]] = {}
    ranges: dict[str, set[str]] = {}

    # Pass 1: authoritative, complete predicate set (full COLLECT).
    for pred in _lpg_distinct_values(db, edge_col, label_field):
        domains.setdefault(pred, set())
        ranges.setdefault(pred, set())

    from_f, to_f = _lpg_detect_endpoint_type_fields(db, edge_col)
    if not type_field and not (from_f and to_f):
        # No way to resolve endpoint types; predicates already surfaced above.
        return domains, ranges

    # Pass 2: endpoint aggregation. Prefer the edge-carried endpoint type; only
    # fall back to a per-edge DOCUMENT() lookup when that field is absent and a
    # vertex type field is known. ``@tf`` is bound only when a DOCUMENT branch
    # references it (ArangoDB rejects unreferenced bind vars).
    if from_f:
        f_expr = f"e[{_aql_str(from_f)}]"
    elif type_field:
        f_expr = "DOCUMENT(e._from)[@tf]"
    else:
        f_expr = "null"
    if to_f:
        t_expr = f"e[{_aql_str(to_f)}]"
    elif type_field:
        t_expr = "DOCUMENT(e._to)[@tf]"
    else:
        t_expr = "null"
    bind: dict[str, Any] = {"@col": edge_col, "scan": scan, "lf": label_field}
    if type_field and (not from_f or not to_f):
        bind["tf"] = type_field
    rows = run_aql(
        db,
        f"FOR e IN @@col LIMIT @scan "
        f"  FILTER e[@lf] != null "
        f"  COLLECT pred = e[@lf], f = {f_expr}, t = {t_expr} WITH COUNT INTO n "
        f"  RETURN {{pred: pred, f: f, t: t, n: n}}",
        bind_vars=bind,
    )
    for r in rows:
        pred = str(r.get("pred") or "").strip()
        if not pred:
            continue
        domains.setdefault(pred, set())
        ranges.setdefault(pred, set())
        if r.get("f"):
            domains[pred].add(str(r["f"]))
        if r.get("t"):
            ranges[pred].add(str(r["t"]))
    return domains, ranges


def _aql_str(field: str) -> str:
    """Quote a field name as an AQL string literal (fields here are our own
    constants / detected attribute names, never user free-text)."""
    return '"' + str(field).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _lpg_sample_datatype_props(
    g: Any,
    db: Any,
    col: str,
    type_field: str,
    value_to_class: dict[str, Any],
    ns: Any,
    aoe_ns: Any,
    config: Any,
    *,
    max_types: int = 40,
) -> None:
    """Per-type field sampling -> datatype properties (domain = the type's class)."""
    from rdflib import OWL, RDF, RDFS, Literal, URIRef

    types = _lpg_distinct_values(db, col, type_field, cap=max_types)
    for raw in types:
        cls_uri = value_to_class.get(raw)
        if cls_uri is None:
            continue
        docs = list(
            run_aql(
                db,
                "FOR d IN @@col FILTER d[@tf] == @t LIMIT @lim "
                "RETURN UNSET(d, '_key', '_id', '_rev', '_from', '_to')",
                bind_vars={
                    "@col": col,
                    "tf": type_field,
                    "t": raw,
                    "lim": config.field_sample_limit,
                },
            )
        )
        field_types: dict[str, str] = {}
        for doc in docs:
            if not isinstance(doc, dict):
                continue
            for k, v in doc.items():
                if k == type_field:
                    continue
                xsd = _infer_xsd_type(v)
                if xsd is None:
                    continue
                if field_types.setdefault(k, xsd) != xsd:
                    field_types[k] = "http://www.w3.org/2001/XMLSchema#string"
        local = _lpg_localname(raw)
        for fname, xsd_iri in field_types.items():
            prop_uri = ns[f"{local}.{fname}"]
            g.add((prop_uri, RDF.type, OWL.DatatypeProperty))
            g.add((prop_uri, RDFS.label, Literal(fname)))
            g.add((prop_uri, RDFS.domain, cls_uri))
            g.add((prop_uri, RDFS.range, URIRef(xsd_iri)))
            g.add((prop_uri, aoe_ns.sourceDb, Literal(config.target_db)))
            g.add((prop_uri, aoe_ns.sourceCollection, Literal(col)))
            g.add((prop_uri, aoe_ns.sourceField, Literal(fname)))


def _stub_extract_schema(config: SchemaExtractionConfig) -> str:
    """Back-compat alias retained for callers/tests that don't need the
    URI → collection map. Equivalent to ``_direct_extract_schema(config)[0]``.

    Internally the new path is named-graph-aware; the function name is
    kept so existing imports + tests continue to work unchanged.
    """
    ttl, _ = _direct_extract_schema(config)
    return ttl


# ---------------------------------------------------------------------------
# Stream 5 PR 1 — Per-class provenance stamping (S.4)
# ---------------------------------------------------------------------------


def _stamp_per_class_provenance(
    db: Any,
    *,
    ontology_id: str,
    source_db: str,
    source_host: str,
    uri_to_collection: dict[str, str],
) -> int:
    """Stamp ``source_db`` / ``source_collection`` / ``source_host`` on every
    class created by this import.

    The stamping is **best-effort**: any class created by this import
    (matched by ``ontology_id``) that has a URI in ``uri_to_collection``
    gets the provenance fields. Classes without a URI in the map (e.g.
    from imported ontologies pulled in transitively) are left alone.

    Returns the number of classes stamped. Failures are logged but
    swallowed -- a provenance bug must never break the extraction write
    path.
    """
    if not db.has_collection("ontology_classes"):
        return 0

    stamped = 0
    try:
        # One bulk AQL pass so we avoid the N+1 pattern of per-class UPDATE.
        # The ``uri_to_collection`` map is materialised as bind data so the
        # server can look up each match without round-tripping.
        result = list(
            run_aql(
                db,
                """
                FOR cls IN ontology_classes
                  FILTER cls.ontology_id == @oid
                  FILTER cls.expired == @never
                  LET sc = @uri_map[cls.uri]
                  FILTER sc != null
                  UPDATE cls WITH {
                    source_db: @sdb,
                    source_collection: sc,
                    source_host: @shost
                  } IN ontology_classes
                  RETURN 1
                """,
                bind_vars={
                    "oid": ontology_id,
                    "uri_map": uri_to_collection,
                    "sdb": source_db,
                    "shost": source_host,
                    "never": NEVER_EXPIRES,
                },
            )
        )
        stamped = len(result)
        log.info(
            "stamped per-class provenance",
            extra={
                "ontology_id": ontology_id,
                "source_db": source_db,
                "stamped_count": stamped,
            },
        )
    except Exception:
        log.warning(
            "per-class provenance stamping failed; classes will lack source metadata",
            extra={"ontology_id": ontology_id, "source_db": source_db},
            exc_info=True,
        )
    return stamped


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def extract_schema(config: SchemaExtractionConfig) -> dict[str, Any]:
    """Extract schema from an external ArangoDB and import as an ontology.

    Pipeline:

    1. Create a run record (in-memory, lost on process restart -- OK for
       MVP; an async refactor will move this to ``schema_extraction_runs``
       or similar).
    2. Connect to the target DB.
    3. Extract OWL/TTL:
         - If ``schema_analyzer`` is installed → use its analyzer.
         - Else → direct named-graph-aware extraction (default path
           since PR 1; covers S.7 + S.8 + S.10).
    4. Import via the standard AOE pipeline (``import_from_file``).
       The ``owl:imports`` triples embedded in step 3 are wired to AOE
       ``imports`` edges by ``sync_owl_imports_edges``.
    5. Post-import: stamp per-class provenance (``source_db``,
       ``source_collection``, ``source_host``) from the URI → collection
       map built in step 3.
    6. Return the run summary.

    Returns:
        Dict with ``run_id``, status, import stats, ``provenance``
        (run-level), and ``provenance_stamped`` (per-class count).
    """
    run_id = uuid.uuid4().hex[:12]
    ontology_id = config.ontology_id or f"schema_{config.target_db}_{run_id}"
    run = _ExtractionRun(run_id=run_id, config=config)
    _runs[run_id] = run

    run.status = ExtractionStatus.RUNNING
    run.started_at = time.time()

    try:
        mapper = _try_import_schema_mapper()
        uri_to_collection: dict[str, str] = {}
        provenance: dict[str, Any]
        if config.lpg_mode:
            # FR-9.14: types live in a field, not in collection names. This is a
            # fundamentally different mapping than the analyzer / collection-per-
            # type paths, so LPG mode takes precedence over both.
            ttl_content, uri_to_collection = _lpg_extract_schema(config)
            provenance = {
                "mode": "lpg",
                "extraction_source": config.extraction_source,
                "graphs_filter": list(config.graph_names) if config.graph_names else None,
                "vertex_type_field": config.vertex_type_field,
                "edge_label_field": config.edge_label_field,
                "label_format": config.label_format,
                "auto_imports": list(config.imports),
            }
        elif mapper is not None:
            ttl_content, provenance = _run_schema_mapper_extract(config, mapper)
            # schema_analyzer doesn't currently surface a URI → collection
            # map, so per-class provenance stamping is a no-op on this path.
            # When the analyzer is bypassed (the default), the direct path
            # below populates the map.
        else:
            ttl_content, uri_to_collection = _direct_extract_schema(config)
            provenance = {
                "mode": "direct",
                "extraction_source": config.extraction_source,
                "graphs_filter": list(config.graph_names) if config.graph_names else None,
                "include_loose": config.include_loose,
                "auto_imports": list(config.imports),
                "field_sampling": config.sample_fields,
            }

        db = get_db()
        import_result = import_from_file(
            file_content=ttl_content.encode("utf-8"),
            filename=f"{config.target_db}_schema.ttl",
            ontology_id=ontology_id,
            db=db,
            ontology_label=config.ontology_label or f"Schema: {config.target_db}",
        )

        # S.4: per-class provenance stamping. Only fires for the direct
        # path (uri_to_collection populated). Failures are swallowed so a
        # provenance bug cannot break the extraction write path.
        provenance_stamped = 0
        if uri_to_collection:
            provenance_stamped = _stamp_per_class_provenance(
                db,
                ontology_id=ontology_id,
                source_db=config.target_db,
                source_host=config.target_host,
                uri_to_collection=uri_to_collection,
            )

        run.status = ExtractionStatus.COMPLETED
        run.completed_at = time.time()
        run.result = import_result

        log.info(
            "schema extraction completed",
            extra={
                "run_id": run_id,
                "ontology_id": ontology_id,
                "target_db": config.target_db,
                "extraction_source": config.extraction_source,
                "provenance_stamped": provenance_stamped,
            },
        )

        return {
            "run_id": run_id,
            "status": run.status.value,
            "ontology_id": ontology_id,
            "import_stats": import_result,
            "provenance": provenance,
            "provenance_stamped": provenance_stamped,
        }

    except Exception as exc:
        run.status = ExtractionStatus.FAILED
        run.completed_at = time.time()
        run.error = str(exc)
        log.exception(
            "schema extraction failed",
            extra={"run_id": run_id, "target_db": config.target_db},
        )
        raise


def get_extraction_status(run_id: str) -> dict[str, Any]:
    """Get the status of an async schema extraction run.

    Returns:
        Dict with run_id, status, timing, and result (if completed).

    Raises:
        ValueError: If the run_id is not found.
    """
    run = _runs.get(run_id)
    if run is None:
        raise ValueError(f"Schema extraction run '{run_id}' not found")

    result: dict[str, Any] = {
        "run_id": run.run_id,
        "status": run.status.value,
        "target_db": run.config.target_db,
        "target_host": run.config.target_host,
        "extraction_source": run.config.extraction_source,
        "started_at": run.started_at,
        "completed_at": run.completed_at,
    }

    if run.status == ExtractionStatus.COMPLETED:
        result["import_stats"] = run.result
    if run.error:
        result["error"] = run.error

    return result
