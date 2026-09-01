"""035 — Restore the catalog's declared tier on already-imported ontologies.

``tier: local`` means "authored here". A published third-party vocabulary is
not that. The catalog has always declared what each entry is — BFO, SKOS,
FOAF, PROV-O, OWL-Time and dcterms are ``core``; schema.org, SOSA/SSN, VSSo
and the FIBO modules are ``domain`` — but the importer hardcoded ``local`` and
overwrote it on every import, discarding the one field that distinguishes a
foundational standard from this organisation's own work.

The importer now passes the declared tier through. This repairs the entries
imported before that, matching them by registry ``_key`` against the catalog.

Deliberately narrow:

* Only registry entries whose ``_key`` is a known catalog id are touched. An
  ontology someone uploaded by hand IS local as far as the system knows, and
  a key collision with a catalog id is the user's own naming choice — so the
  match also requires the entry to have come from an import.
* Only the ``tier`` field is written. Nothing else about the entry is assumed
  to need repair.
* Entries already carrying the right tier are skipped, so re-running is free.

Set ``DRY_RUN=1`` to report what would change and write nothing.
"""

from __future__ import annotations

import logging
import os

from arango.database import StandardDatabase

from app.services.standard_ontology_catalog import load_catalog

log = logging.getLogger(__name__)

_REGISTRY = "ontology_registry"
_IMPORT_SOURCES = {"file_import", "url_import", "catalog_import"}
_VALID_TIERS = {"core", "domain"}


def up(db: StandardDatabase) -> None:
    if not db.has_collection(_REGISTRY):
        log.info("035: no %s collection; nothing to do", _REGISTRY)
        return

    declared = {
        entry["id"]: entry["tier"]
        for entry in load_catalog()
        if entry.get("id") and entry.get("tier") in _VALID_TIERS
    }
    if not declared:
        log.warning("035: catalog declares no usable tiers; nothing to do")
        return

    dry_run = os.environ.get("DRY_RUN") == "1"
    collection = db.collection(_REGISTRY)
    changed = 0

    for catalog_id, tier in sorted(declared.items()):
        entry = collection.get(catalog_id)
        if not isinstance(entry, dict):
            continue
        if entry.get("source") not in _IMPORT_SOURCES:
            log.info(
                "035: %s was not imported (source=%s); left alone", catalog_id, entry.get("source")
            )
            continue
        if entry.get("tier") == tier:
            continue

        log.warning("035: %s tier %r -> %r", catalog_id, entry.get("tier"), tier)
        if not dry_run:
            collection.update({"_key": catalog_id, "tier": tier})
        changed += 1

    verb = "would change" if dry_run else "changed"
    log.warning("035: %s %d registry tier(s)", verb, changed)


def down(db: StandardDatabase) -> None:
    """Not reversed.

    Reverting would rewrite ``local`` over a tier that is now correct, which is
    the bug this migration exists to fix.
    """
    log.info("035: down() is a no-op; reverting would restore the incorrect tier")
