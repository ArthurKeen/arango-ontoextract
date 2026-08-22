"""033 — Expire document-furniture classes from existing ontologies (FR-2.18).

`Page 812`, `Figure 4`, `Table 12.3` are artefacts *of* a source document, not
concepts described *by* it. FR-2.18 rejects them at extraction; this sweeps the
ontologies extracted before that rule existed.

Two deliberate properties:

* **Temporal, not destructive.** Matches are expired via the standard temporal
  path, so they stay queryable as-of a prior time and the removal is auditable
  and reversible — the same contract curation rejection uses.
* **Reports before it acts.** Set ``DRY_RUN=1`` in the environment to log what
  would be expired and change nothing. Worth doing first on a large extraction:
  a 667-class manual ontology can carry a lot of furniture, and the count is
  the sanity check on the pattern.

The pattern lives with the filter agent (``is_structural_artifact``) rather than
being duplicated here, so extraction and this sweep can never disagree.
"""

from __future__ import annotations

import logging
import os

from arango.database import StandardDatabase

from app.db.temporal_constants import NEVER_EXPIRES
from app.db.utils import run_aql
from app.extraction.agents.filter import is_structural_artifact
from app.services.temporal import expire_entity

log = logging.getLogger(__name__)

_CLASSES = "ontology_classes"


def up(db: StandardDatabase) -> None:
    if not db.has_collection(_CLASSES):
        log.info("033: %s absent — nothing to sweep", _CLASSES)
        return

    dry_run = os.getenv("DRY_RUN", "").strip() not in ("", "0", "false", "False")

    rows = list(
        run_aql(
            db,
            f"FOR c IN {_CLASSES} FILTER c.expired == @never "
            "RETURN {key: c._key, label: c.label, ontology_id: c.ontology_id}",
            bind_vars={"never": NEVER_EXPIRES},
        )
    )
    matches = [r for r in rows if is_structural_artifact(str(r.get("label") or ""))]

    if not matches:
        log.info("033: scanned %d live classes, no document furniture found", len(rows))
        return

    by_ontology: dict[str, int] = {}
    for m in matches:
        oid = str(m.get("ontology_id") or "<none>")
        by_ontology[oid] = by_ontology.get(oid, 0) + 1

    log.warning(
        "033: %d of %d live classes look like document furniture (%s)",
        len(matches),
        len(rows),
        ", ".join(f"{k}={v}" for k, v in sorted(by_ontology.items())),
    )
    for m in matches[:25]:
        log.warning("033:   would expire %s (%s)", m["label"], m["key"])
    if len(matches) > 25:
        log.warning("033:   ... and %d more", len(matches) - 25)

    if dry_run:
        log.warning("033: DRY_RUN set — nothing expired. Unset it to apply.")
        return

    expired = 0
    for m in matches:
        try:
            expire_entity(db, collection=_CLASSES, key=m["key"])
            expired += 1
        except Exception as exc:  # pragma: no cover — one bad row must not abort the sweep
            log.warning("033: could not expire %s: %s", m["key"], exc)
    log.warning("033: expired %d document-furniture classes (recoverable via time travel)", expired)


def down(db: StandardDatabase) -> None:
    """Not reversed automatically.

    The sweep is temporal, so the classes still exist as prior versions — but
    un-expiring them would also resurrect furniture that a curator has since
    legitimately rejected. Recover individually via the time-travel API instead.
    """
    log.info("033: down() is a no-op; expired classes remain recoverable as-of a prior time")
