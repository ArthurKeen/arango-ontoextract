"""Read-time curated-label overlay (PRD §6.20 FR-20.4).

Extraction owns the ontology entity documents: it rebuilds ``_key``s from the
LLM's label and re-inserts with ``overwrite=True``, so anything written onto an
entity is reclaimed on the next run. A curated label therefore lives in
``label_decisions`` (which extraction never touches) and is merged back over the
extracted label **on read**, here.

Consequences worth knowing:

* The overlay is keyed on ``uri``. That is the only identifier stable across
  re-extraction — ``_key`` is rebuilt from the label, so renaming a concept in
  the source would change it.
* Applying the overlay also collapses the *resurrection duplicate*: when a
  curator edit has expired the original document and a later extraction revives
  that key (``overwrite=True`` resets ``expired``), both rows carry the same
  ``uri`` and so resolve to the same curated label.
* Every read path that shows a label to a human or exports one MUST go through
  ``apply_to_rows`` — a path that skips it silently serves the pre-curation
  label, which is the failure mode this feature exists to prevent.
"""

from __future__ import annotations

import logging
from typing import Any

from arango.database import StandardDatabase

from app.db import lexicon_repo

log = logging.getLogger(__name__)

# Fields the overlay is allowed to replace. Deliberately narrow: a decision is
# about what a concept is CALLED, not about its confidence, status or evidence.
OVERLAY_FIELDS = ("label", "description")


def apply_to_rows(
    rows: list[dict[str, Any]],
    decisions: dict[str, dict[str, Any]],
    *,
    uri_field: str = "uri",
) -> list[dict[str, Any]]:
    """Merge curated labels over extracted rows, in place-safe fashion.

    Rows without a matching decision are returned untouched (same object), so the
    overlay costs nothing on ontologies with no curation. A curated row gains
    ``curated_label=True`` plus attribution so the UI can mark it and a curator
    can tell a decision from an extraction artefact.

    ``description`` is only overridden when the decision actually carries one —
    a decision that renamed a concept without rewriting its description must not
    blank the extracted description.
    """
    if not decisions or not rows:
        return rows
    out: list[dict[str, Any]] = []
    for row in rows:
        uri = row.get(uri_field)
        decision = decisions.get(str(uri)) if uri else None
        if decision is None:
            out.append(row)
            continue
        merged = dict(row)
        merged["extracted_label"] = row.get("label")
        merged["label"] = decision.get("label")
        if decision.get("description"):
            merged["description"] = decision["description"]
        merged["curated_label"] = True
        merged["curated_by"] = decision.get("decided_by")
        merged["curated_at"] = decision.get("decided_at")
        out.append(merged)
    return out


def apply_for_ontology(
    db: StandardDatabase | None,
    ontology_id: str | None,
    rows: list[dict[str, Any]],
    *,
    uri_field: str = "uri",
) -> list[dict[str, Any]]:
    """Fetch the live decisions for an ontology and overlay them onto ``rows``.

    Fails open: if the lexicon collection is missing or the lookup errors, the
    extracted rows are returned unchanged. A curated label that fails to apply is
    a degraded read; an exception here would take down the whole canvas.
    """
    if not rows:
        return rows
    try:
        decisions = lexicon_repo.live_decisions_by_uri(db, ontology_id=ontology_id)
    except Exception:  # pragma: no cover — defensive, see docstring
        log.warning("label overlay lookup failed; serving extracted labels", exc_info=True)
        return rows
    return apply_to_rows(rows, decisions, uri_field=uri_field)


def resolved_label(db: StandardDatabase | None, *, concept_uri: str, fallback: str) -> str:
    """The curated label for one concept, or ``fallback``.

    For single-entity paths where loading the whole decision map would be waste.
    """
    if not concept_uri:
        return fallback
    try:
        decision = lexicon_repo.get_live_decision(db, concept_uri=concept_uri)
    except Exception:  # pragma: no cover — defensive
        log.warning("label overlay lookup failed for %s", concept_uri, exc_info=True)
        return fallback
    if decision is None:
        return fallback
    return str(decision.get("label") or fallback)
