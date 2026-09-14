"""Import a CSI v1 document as an AOE ontology (CSI -> OWL -> ``import_from_file``).

CSI v1 (Conceptual Schema Interchange) is the artifact the portfolio exchanges:
``r2g`` emits it forward from relational schemas (deriving through
``relational-schema-analyzer``), ``arangodb-schema-analyzer`` emits it in reverse
from a live ArangoDB, and the contextual-data-fabric catalog consumes it. Until
now AOE could see none of that: it extracted its own ontologies over the same
databases and could not read what the fabric queries. This module is the read
side of the round trip (CDF unified-architecture paper, sequence step 3): a CSI
document becomes an AOE ontology with provenance that keeps every correspondence
the document carries as **data**, not as a naming convention.

What is recorded, per element:

    * entity                 -> ``owl:Class``; ``aoe:sourceDb`` / ``aoe:sourceCollection``
                                from ``arangoPhysicalMapping.entities.<E>`` (style,
                                collection, and for ``LABEL`` style the discriminator
                                ``aoe:lpgTypeField`` / ``aoe:lpgTypeValue``)
    * entity property        -> ``owl:DatatypeProperty`` with ``rdfs:domain``; the
                                physical field name from
                                ``arangoPhysicalMapping.entities.<E>.properties.<p>.field``
                                is stamped as ``aoe:sourceField`` (this is the
                                property->column correspondence the paper's break 3
                                says AOE never kept)
    * relationship           -> ``owl:ObjectProperty`` with ``rdfs:domain`` / ``rdfs:range``
                                from ``fromEntity`` / ``toEntity``; edge collection and
                                ``GENERIC_WITH_TYPE`` discriminator recorded likewise
    * ``joinKeys``           -> ``aoe:joinKey`` on the bound properties
    * document provenance    -> producer, direction, source, ``generatedAt`` and the
                                bitemporal stamps (``transactionTime``, ``validTime``,
                                ``validTimeSource``, ``predecessorFingerprint``) as
                                annotations on the ontology resource

The OWL vocabulary and namespaces mirror :mod:`app.services.relational_schema_extraction`
so the Turtle flows through the same ``import_from_file`` pipeline and the same
per-class provenance stamping.

Type detection is **not** performed here. Which field holds an entity's type is a fact
about the database and is the analyzer's job (paper Q-5); when the CSI says an entity is
``LABEL``-style, this module records the analyzer's answer and does not second-guess it.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from pydantic import BaseModel, Field

from app.db.client import get_db
from app.services.ontology_import import import_from_file
from app.services.schema_extraction import _stamp_per_class_provenance

log = logging.getLogger(__name__)

CSI_VERSION = "1"

#: Endpoint marker the analyzers emit when a relationship's domain or range could
#: not be resolved to one entity. No ``rdfs:domain`` / ``rdfs:range`` is asserted.
UNRESOLVED_ENDPOINT = "Any"

#: CSI property ``type`` values (as emitted by ``arangodb-schema-analyzer``) to XSD local
#: names. Anything unknown, or absent (``r2g`` emits names only), is ``xsd:string``.
_CSI_TYPE_TO_XSD: dict[str, str] = {
    "string": "string",
    "integer": "integer",
    "int": "integer",
    "long": "integer",
    "number": "decimal",
    "decimal": "decimal",
    "float": "double",
    "double": "double",
    "boolean": "boolean",
    "bool": "boolean",
    "datetime": "dateTime",
    "timestamp": "dateTime",
    "date": "date",
    "array": "string",
    "object": "string",
    "json": "string",
}

_BITEMPORAL_KEYS: tuple[str, ...] = (
    "transactionTime",
    "validTimeSource",
    "predecessorFingerprint",
)


class CsiValidationError(ValueError):
    """The document is not a CSI v1 document this importer can read."""


class CsiImportConfig(BaseModel):
    """A CSI v1 document plus the options the import needs."""

    document: dict[str, Any] = Field(
        ..., description="A CSI v1 document as emitted by r2g, arangodb-schema-analyzer or RSA."
    )
    db_label: str | None = Field(
        default=None,
        description="Logical source name for the ontology namespace + provenance; "
        "defaults to provenance.source.ref, then provenance.source.kind.",
    )
    source_host: str = Field(default="", description="Host recorded in provenance.")
    imports: list[str] = Field(default_factory=list, description="AOE ontology IDs to import.")
    ontology_id: str | None = Field(default=None)
    ontology_label: str | None = Field(default=None)


# ── Validation ───────────────────────────────────────────────────────────────


def validate_csi_document(doc: Any) -> list[str]:
    """Return the structural problems that would stop this importer; empty when readable.

    Checks the three required blocks and the shapes this module dereferences. When the
    authoritative ``arangodb-schema-analyzer`` package is importable, its JSON-Schema
    validator runs as well and its messages are appended — AOE does not depend on the
    analyzer, so that is best-effort.
    """
    errors: list[str] = []
    if not isinstance(doc, dict):
        return ["document must be a JSON object"]
    if str(doc.get("csiVersion", "")) != CSI_VERSION:
        errors.append(f"csiVersion must be {CSI_VERSION!r} (got {doc.get('csiVersion')!r})")
    cm = doc.get("conceptualModel")
    if not isinstance(cm, dict):
        errors.append("conceptualModel must be an object")
    else:
        entities = cm.get("entities")
        if not isinstance(entities, list) or not entities:
            errors.append("conceptualModel.entities must be a non-empty array")
        else:
            for i, ent in enumerate(entities):
                if not isinstance(ent, dict) or not str(ent.get("name", "")).strip():
                    errors.append(f"conceptualModel.entities[{i}].name must be a non-empty string")
        rels = cm.get("relationships")
        if not isinstance(rels, list):
            errors.append("conceptualModel.relationships must be an array")
        else:
            for i, rel in enumerate(rels):
                if not isinstance(rel, dict):
                    errors.append(f"conceptualModel.relationships[{i}] must be an object")
                    continue
                for key in ("type", "fromEntity", "toEntity"):
                    if not str(rel.get(key, "")).strip():
                        errors.append(
                            f"conceptualModel.relationships[{i}].{key} must be a non-empty string"
                        )
    pm = doc.get("arangoPhysicalMapping")
    if not isinstance(pm, dict):
        errors.append("arangoPhysicalMapping must be an object")
    prov = doc.get("provenance")
    if not isinstance(prov, dict):
        errors.append("provenance must be an object")
    if errors:
        return errors
    try:  # authoritative validator, when present
        from schema_analyzer.csi import (
            validate_csi as _analyzer_validate,  # type: ignore[import-not-found,unused-ignore]
        )

        extra = _analyzer_validate(doc)
        if isinstance(extra, list):
            errors.extend(str(e) for e in extra)
    except ImportError:
        pass
    except Exception as exc:  # the analyzer's validator must never make AOE fail closed
        log.debug("analyzer CSI validation unavailable: %s", exc)
    return errors


# ── Pure builder ─────────────────────────────────────────────────────────────


def _default_db_label(doc: dict[str, Any]) -> str:
    source = (doc.get("provenance") or {}).get("source") or {}
    ref = str(source.get("ref") or "").strip()
    kind = str(source.get("kind") or "").strip()
    return ref or kind or "csi"


def _local(name: str) -> str:
    """URI local name for a conceptual name: keep letters, digits, underscore and dot."""
    return "".join(ch if (ch.isalnum() or ch in "_.") else "_" for ch in str(name).strip()) or "_"


def build_csi_owl(
    doc: dict[str, Any],
    *,
    db_label: str,
    imports: list[str] | None = None,
) -> tuple[str, dict[str, str]]:
    """Map a CSI v1 document to OWL Turtle + a URI -> physical-collection map.

    Pure function: no database access. Raises :class:`CsiValidationError` when the
    document is not readable (see :func:`validate_csi_document`).
    """
    from rdflib import OWL, RDF, RDFS, XSD, Graph, Literal, Namespace, URIRef

    problems = validate_csi_document(doc)
    if problems:
        raise CsiValidationError("; ".join(problems))

    imports = imports or []
    ns_str = f"http://aoe.example.org/schema/{db_label}#"
    ns = Namespace(ns_str)
    aoe_ns = Namespace("http://aoe.example.org/vocab#")
    g = Graph()
    g.bind("owl", OWL)
    g.bind("rdfs", RDFS)
    g.bind("rdf", RDF)
    g.bind("xsd", XSD)
    g.bind("schema", ns)
    g.bind("aoe", aoe_ns)

    cm: dict[str, Any] = doc["conceptualModel"]
    pm: dict[str, Any] = doc["arangoPhysicalMapping"]
    prov: dict[str, Any] = doc["provenance"]
    pm_entities: dict[str, Any] = pm.get("entities") or {}
    pm_rels: dict[str, Any] = pm.get("relationships") or {}

    ont_uri = URIRef(ns_str.rstrip("#"))
    g.add((ont_uri, RDF.type, OWL.Ontology))
    g.add((ont_uri, RDFS.label, Literal(f"Schema of {db_label} (CSI)")))
    for imported_id in imports:
        g.add((ont_uri, OWL.imports, URIRef(f"http://example.org/ontology/{imported_id}")))

    # --- Document provenance, incl. the bitemporal stamps -------------------
    g.add((ont_uri, aoe_ns.csiVersion, Literal(CSI_VERSION)))
    for key in ("producer", "producerVersion", "direction", "generatedAt", *_BITEMPORAL_KEYS):
        val = prov.get(key)
        if val is not None and str(val).strip():
            g.add((ont_uri, aoe_ns[f"csi{key[0].upper()}{key[1:]}"], Literal(str(val))))
    source = prov.get("source") or {}
    if isinstance(source, dict):
        for key in ("kind", "ref", "fingerprint"):
            val = source.get(key)
            if val is not None and str(val).strip():
                g.add((ont_uri, aoe_ns[f"csiSource{key.capitalize()}"], Literal(str(val))))
    valid_time = prov.get("validTime")
    if isinstance(valid_time, dict) and valid_time.get("from"):
        g.add((ont_uri, aoe_ns.csiValidFrom, Literal(str(valid_time["from"]))))
        if valid_time.get("to"):
            g.add((ont_uri, aoe_ns.csiValidTo, Literal(str(valid_time["to"]))))

    uri_to_collection: dict[str, str] = {}
    entity_names: set[str] = set()

    def _xsd(csi_type: Any) -> URIRef:
        return XSD[_CSI_TYPE_TO_XSD.get(str(csi_type or "").lower(), "string")]

    # --- Classes + datatype properties -------------------------------------
    for ent in cm["entities"]:
        name = str(ent["name"]).strip()
        entity_names.add(name)
        cls_uri = ns[_local(name)]
        raw_phys = pm_entities.get(name)
        phys: dict[str, Any] = raw_phys if isinstance(raw_phys, dict) else {}
        collection = str(phys.get("collectionName") or "").strip()
        style = str(phys.get("style") or "").strip()

        g.add((cls_uri, RDF.type, OWL.Class))
        g.add((cls_uri, RDFS.label, Literal(name)))
        g.add((cls_uri, RDFS.comment, Literal(f"CSI entity {name}")))
        g.add((cls_uri, aoe_ns.csiEntity, Literal(name)))
        g.add((cls_uri, aoe_ns.sourceDb, Literal(db_label)))
        if collection:
            g.add((cls_uri, aoe_ns.sourceCollection, Literal(collection)))
        if style:
            g.add((cls_uri, aoe_ns.csiMappingStyle, Literal(style)))
        if style == "LABEL":
            if phys.get("typeField"):
                g.add((cls_uri, aoe_ns.lpgTypeField, Literal(str(phys["typeField"]))))
            if phys.get("typeValue"):
                g.add((cls_uri, aoe_ns.lpgTypeValue, Literal(str(phys["typeValue"]))))
        for label in ent.get("labels") or []:
            if isinstance(label, str) and label.strip() and label != name:
                g.add((cls_uri, aoe_ns.csiLabel, Literal(label)))
        uri_to_collection[str(cls_uri)] = collection or name

        phys_props: dict[str, Any] = phys.get("properties") or {}
        for prop in ent.get("properties") or []:
            if not isinstance(prop, dict) or not str(prop.get("name", "")).strip():
                continue
            pname = str(prop["name"]).strip()
            prop_uri = ns[f"{_local(name)}.{_local(pname)}"]
            g.add((prop_uri, RDF.type, OWL.DatatypeProperty))
            g.add((prop_uri, RDFS.label, Literal(pname)))
            g.add((prop_uri, RDFS.domain, cls_uri))
            g.add((prop_uri, RDFS.range, _xsd(prop.get("type"))))
            g.add((prop_uri, aoe_ns.csiProperty, Literal(pname)))
            g.add((prop_uri, aoe_ns.sourceDb, Literal(db_label)))
            if collection:
                g.add((prop_uri, aoe_ns.sourceCollection, Literal(collection)))
            mapping = phys_props.get(pname)
            field = mapping.get("field") if isinstance(mapping, dict) else None
            if field:
                g.add((prop_uri, aoe_ns.sourceField, Literal(str(field))))

    # --- Join keys: mark the bound properties -------------------------------
    for jk in cm.get("joinKeys") or []:
        if not isinstance(jk, dict):
            continue
        key = str(jk.get("key") or jk.get("concept") or "").strip()
        concept = str(jk.get("concept") or "").strip()
        for binding in jk.get("bindings") or []:
            if not isinstance(binding, dict):
                continue
            ent_name = str(binding.get("entity") or "").strip()
            if not ent_name or not concept:
                continue
            prop_uri = ns[f"{_local(ent_name)}.{_local(concept)}"]
            if (prop_uri, RDF.type, OWL.DatatypeProperty) in g:
                g.add((prop_uri, aoe_ns.joinKey, Literal(key or concept)))

    # --- Object properties from relationships ------------------------------
    for rel in cm["relationships"]:
        rtype = str(rel["type"]).strip()
        from_e = str(rel["fromEntity"]).strip()
        to_e = str(rel["toEntity"]).strip()
        obj_uri = ns[_local(rtype)]
        raw_rel = pm_rels.get(rtype)
        phys_r: dict[str, Any] = raw_rel if isinstance(raw_rel, dict) else {}
        edge_collection = str(phys_r.get("edgeCollectionName") or "").strip()
        r_style = str(phys_r.get("style") or "").strip()

        g.add((obj_uri, RDF.type, OWL.ObjectProperty))
        g.add((obj_uri, RDFS.label, Literal(rtype)))
        g.add((obj_uri, RDFS.comment, Literal(f"CSI relationship {from_e} -> {to_e}")))
        g.add((obj_uri, aoe_ns.csiRelationship, Literal(rtype)))
        g.add((obj_uri, aoe_ns.sourceDb, Literal(db_label)))
        if edge_collection:
            g.add((obj_uri, aoe_ns.sourceCollection, Literal(edge_collection)))
        if r_style:
            g.add((obj_uri, aoe_ns.csiMappingStyle, Literal(r_style)))
        if r_style == "GENERIC_WITH_TYPE":
            if phys_r.get("typeField"):
                g.add((obj_uri, aoe_ns.lpgLabelField, Literal(str(phys_r["typeField"]))))
            if phys_r.get("typeValue"):
                g.add((obj_uri, aoe_ns.lpgLabelValue, Literal(str(phys_r["typeValue"]))))
        if from_e and from_e != UNRESOLVED_ENDPOINT and from_e in entity_names:
            g.add((obj_uri, RDFS.domain, ns[_local(from_e)]))
        if to_e and to_e != UNRESOLVED_ENDPOINT and to_e in entity_names:
            g.add((obj_uri, RDFS.range, ns[_local(to_e)]))
        uri_to_collection[str(obj_uri)] = edge_collection or rtype

    ttl = str(g.serialize(format="turtle"))
    log.info(
        "CSI import build complete",
        extra={
            "db_label": db_label,
            "producer": prov.get("producer"),
            "direction": prov.get("direction"),
            "triples": len(g),
            "classes": sum(1 for _ in g.subjects(RDF.type, OWL.Class)),
            "object_properties": sum(1 for _ in g.subjects(RDF.type, OWL.ObjectProperty)),
            "datatype_properties": sum(1 for _ in g.subjects(RDF.type, OWL.DatatypeProperty)),
        },
    )
    return ttl, uri_to_collection


# ── Preview + import ─────────────────────────────────────────────────────────


def _provenance_summary(doc: dict[str, Any]) -> dict[str, Any]:
    prov = doc.get("provenance") or {}
    source = prov.get("source") or {}
    return {
        "mode": "csi",
        "producer": prov.get("producer"),
        "producer_version": prov.get("producerVersion"),
        "direction": prov.get("direction"),
        "source_kind": source.get("kind") if isinstance(source, dict) else None,
        "source_ref": source.get("ref") if isinstance(source, dict) else None,
        "generated_at": prov.get("generatedAt"),
        "transaction_time": prov.get("transactionTime"),
        "valid_time": prov.get("validTime"),
        "valid_time_source": prov.get("validTimeSource"),
        "predecessor_fingerprint": prov.get("predecessorFingerprint"),
    }


def preview_csi_document(doc: Any) -> dict[str, Any]:
    """Read-only summary of what an import would create; never touches the database."""
    problems = validate_csi_document(doc)
    if problems:
        return {"valid": False, "errors": problems}
    cm = doc["conceptualModel"]
    entities = [str(e["name"]) for e in cm["entities"]]
    property_count = sum(len(e.get("properties") or []) for e in cm["entities"])
    relationships = [
        {"type": str(r["type"]), "from": str(r["fromEntity"]), "to": str(r["toEntity"])}
        for r in cm["relationships"]
    ]
    pm_block = doc["arangoPhysicalMapping"]
    pm_entities: dict[str, Any] = (
        (pm_block.get("entities") or {}) if isinstance(pm_block, dict) else {}
    )
    styles: dict[str, int] = {}
    for phys in pm_entities.values():
        if isinstance(phys, dict):
            style = str(phys.get("style") or "unmapped")
            styles[style] = styles.get(style, 0) + 1
    return {
        "valid": True,
        "errors": [],
        "db_label": _default_db_label(doc),
        "entities": entities,
        "entity_count": len(entities),
        "property_count": property_count,
        "relationships": relationships,
        "relationship_count": len(relationships),
        "join_keys": [
            str(jk.get("concept") or jk.get("key"))
            for jk in cm.get("joinKeys") or []
            if isinstance(jk, dict)
        ],
        "entity_mapping_styles": styles,
        "provenance": _provenance_summary(doc),
    }


def import_csi_document(config: CsiImportConfig) -> dict[str, Any]:
    """Build the ontology from a CSI document and import it into AOE.

    Mirrors :func:`app.services.relational_schema_extraction.extract_relational_schema`:
    build OWL -> ``import_from_file`` -> per-class provenance stamping. Raises
    :class:`CsiValidationError` (a ``ValueError``) for an unreadable document.
    """
    run_id = uuid.uuid4().hex[:12]
    started = time.time()
    doc = config.document
    db_label = (config.db_label or _default_db_label(doc)).strip() or "csi"
    ttl_content, uri_to_collection = build_csi_owl(doc, db_label=db_label, imports=config.imports)
    ontology_id = config.ontology_id or f"csi_{_local(db_label)}_{run_id}"
    prov = _provenance_summary(doc)

    db = get_db()
    import_result = import_from_file(
        file_content=ttl_content.encode("utf-8"),
        filename=f"{db_label}_csi.ttl",
        ontology_id=ontology_id,
        db=db,
        ontology_label=config.ontology_label or f"Schema: {db_label} (CSI)",
    )
    provenance_stamped = _stamp_per_class_provenance(
        db,
        ontology_id=ontology_id,
        source_db=db_label,
        source_host=config.source_host or str(prov.get("source_kind") or "csi"),
        uri_to_collection=uri_to_collection,
    )
    log.info(
        "CSI document imported",
        extra={"run_id": run_id, "ontology_id": ontology_id, "producer": prov.get("producer")},
    )
    return {
        "run_id": run_id,
        "status": "completed",
        "ontology_id": ontology_id,
        "import_stats": import_result,
        "provenance": {**prov, "db_label": db_label, "auto_imports": list(config.imports)},
        "provenance_stamped": provenance_stamped,
        "elapsed_ms": int((time.time() - started) * 1000),
    }
