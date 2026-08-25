"""Compute and enrich top-level confidence/label for ontology edges.

Two helpers live here:

* ``compute_edge_confidence`` -- aggregates per-evidence scores when the edge
  doc itself doesn't carry a top-level ``confidence``.
* ``enrich_rdfs_range_class_edges`` -- joins ``rdfs_range_class`` scaffolding
  edges with their owning ``ontology_object_properties`` vertex so the edge
  carries the property's real ``label``, ``description``, ``confidence`` and
  ``evidence``. This is what makes the canvas show a meaningful relationship
  name (e.g. "generates Risk Profile") instead of the structural fallback
  ``owl:ObjectProperty``, and what makes the confidence lens paint the edge.

Background: ontology relationships are stored in three coordinated documents
(see PRD §5.2 / §6.13.1):

* ``ontology_object_properties/<key>`` -- the *property* vertex carrying
  ``label, description, uri, confidence, evidence`` (the semantic content).
* ``rdfs_domain/<key>`` -- ``property -> domain class`` (typing edge).
* ``rdfs_range_class/<key>`` -- ``property -> range class`` (typing edge).

The ``rdfs_*`` edges are pure scaffolding; they do not carry the relationship
name or its evidence. A class-to-class link on the workspace canvas is built
by joining a matching ``rdfs_domain`` + ``rdfs_range_class`` pair, and the
display label/confidence has to come from the property vertex on the other
end of that pair. Doing the join in the backend keeps every client (canvas,
MCP, exports) consistent and avoids re-inventing it per UI.

Aggregation rules used by ``compute_edge_confidence``:

* Mean of per-evidence confidence, each clamped to [0, 1] -- matches what
  the curation dashboard shows for class confidence and is more forgiving of
  one stray low-confidence evidence record than ``max`` would be of one
  stray high one.
* An explicit top-level ``confidence`` always wins, preserving
  forward-compatibility with future writers.
"""

from __future__ import annotations

from typing import Any


def compute_edge_confidence(edge: dict[str, Any]) -> float | None:
    """Return an aggregated confidence in [0, 1] for ``edge``, or ``None``.

    Resolution order:

    1. If ``edge["confidence"]`` is a finite number in [0, 1], use it as-is.
    2. Else, mean of every numeric ``evidence_confidence`` in
       ``edge["evidence"]`` (each clamped to [0, 1]).
    3. Else, ``None`` — caller decides between fallback color and "Imported"
       label.

    The function is total: it never raises on malformed input. Non-numeric
    evidence entries are skipped silently rather than poisoning the mean.
    """
    explicit = edge.get("confidence")
    if isinstance(explicit, (int, float)) and not isinstance(explicit, bool):
        v = float(explicit)
        if v == v and v >= 0.0:
            return _clamp01(v)

    evidence = edge.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        return None

    total = 0.0
    n = 0
    for item in evidence:
        if not isinstance(item, dict):
            continue
        ec = item.get("evidence_confidence")
        if isinstance(ec, bool):  # bool is a subclass of int — reject explicitly
            continue
        if not isinstance(ec, (int, float)):
            continue
        f = float(ec)
        if f != f:  # NaN
            continue
        total += _clamp01(f)
        n += 1

    if n == 0:
        return None
    return total / n


def _clamp01(v: float) -> float:
    if v < 0.0:
        return 0.0
    if v > 1.0:
        return 1.0
    return v


# Fields copied from the property vertex onto a rdfs_range_class edge.
# Edge-level fields (``_key``, ``_from``, ``_to``, ``ontology_id``, ``edge_type``,
# ``created``, ``expired``, ``_rev``, ``_id``) are intentionally never overwritten:
# the edge is its own document with its own identity.
_PROPERTY_FIELDS_TO_LIFT = (
    "label",
    "description",
    "uri",
    "confidence",
    "evidence",
)


def _inverse_property_ids(properties_by_id: dict[str, Any]) -> dict[str, str]:
    """Map property ``_id`` -> its ``owl:inverseOf`` partner's ``_id``.

    The property document stores the partner as a URI (that is what the source
    file states). The canvas pairs edges by ``_from``, which is an ``_id``, so
    the URI is resolved here once rather than per edge.
    """
    id_by_uri = {
        prop["uri"]: pid
        for pid, prop in properties_by_id.items()
        if isinstance(prop, dict) and isinstance(prop.get("uri"), str)
    }
    out: dict[str, str] = {}
    for pid, prop in properties_by_id.items():
        if not isinstance(prop, dict):
            continue
        partner_id = id_by_uri.get(prop.get("inverse_of") or "")
        if partner_id and partner_id != pid:
            out[pid] = partner_id
    return out


def enrich_rdfs_range_class_edges(
    edges: list[dict[str, Any]],
    properties_by_id: dict[str, dict[str, Any]],
) -> None:
    """In-place: lift ``label``/``description``/``confidence``/``evidence`` from
    the property vertex onto each ``rdfs_range_class`` edge.

    Lookup: ``edge["_from"]`` is the full ``ontology_object_properties/<key>``
    id of the property vertex; ``properties_by_id[edge["_from"]]`` is the
    matching property doc.

    Existing non-empty fields on the edge are preserved (forward-compat with a
    future writer that already populates them). Edge-identity fields are
    never touched.

    No-op for any edge whose ``edge_type`` is not ``rdfs_range_class``.
    """
    inverse_ids = _inverse_property_ids(properties_by_id)

    for edge in edges:
        if edge.get("edge_type") != "rdfs_range_class":
            continue
        prop_id = edge.get("_from")
        if not isinstance(prop_id, str):
            continue
        prop = properties_by_id.get(prop_id)
        if not isinstance(prop, dict):
            continue
        # The partner property's id, so the canvas can recognise that this edge
        # and its mirror state one fact twice and draw it once.
        partner_id = inverse_ids.get(prop_id)
        if partner_id:
            edge["inverse_of_id"] = partner_id
        for field in _PROPERTY_FIELDS_TO_LIFT:
            if field not in prop:
                continue
            existing = edge.get(field)
            if existing in (None, "", [], {}):
                edge[field] = prop[field]


def mark_subsumption_flag(edge: dict[str, Any]) -> None:
    """Stamp ``subsumption_flagged`` on one edge in place (FR-2.20).

    Collapses the judge's verdict to the single bit the canvas renders: this
    ``subClassOf`` edge failed the "is every X a Y?" test and no curator has
    ruled on it yet. A ruling either way -- kept or detached -- clears the
    mark; the reasoning stays on the edge document for the detail panel and
    the review queue.

    Shared by both read paths (``/edges`` and the effective-graph ``/effective``
    the canvas actually loads) because two copies of this rule would drift, and
    a flag visible on one path but not the other is worse than no flag.
    """
    verdict = edge.get("subsumption_verdict")
    edge["subsumption_flagged"] = bool(
        isinstance(verdict, dict)
        and verdict.get("is_a") is False
        and not verdict.get("curator_decision")
    )
