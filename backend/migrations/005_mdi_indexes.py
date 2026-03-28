"""005 — MDI-prefixed persistent indexes on [created, expired].

Deployed on all versioned vertex and edge collections to accelerate
point-in-time temporal queries.

python-arango does not expose a dedicated ``add_mdi_prefixed_index`` method,
so we use the generic HTTP API via ``db._conn.post`` to create the
mdi-prefixed index type.  If the HTTP approach fails (e.g. ArangoDB version
does not support mdi-prefixed), we fall back to a regular persistent index
on the same fields.
"""

from __future__ import annotations

import logging

from arango.database import StandardDatabase
from arango.exceptions import IndexCreateError

log = logging.getLogger(__name__)

VERSIONED_COLLECTIONS = [
    "ontology_classes",
    "ontology_properties",
    "ontology_constraints",
    "subclass_of",
    "equivalent_class",
    "has_property",
    "extends_domain",
    "extracted_from",
    "related_to",
    "merge_candidate",
    "imports",
]


def _create_mdi_index(db: StandardDatabase, collection_name: str) -> None:
    """Attempt to create an mdi-prefixed index; fall back to persistent."""
    idx_name = f"idx_{collection_name}_mdi_temporal"
    col = db.collection(collection_name)

    for idx in col.indexes():
        if idx.get("name") == idx_name:
            log.debug("index %s already exists on %s", idx_name, collection_name)
            return

    body = {
        "type": "mdi-prefixed",
        "fields": ["created", "expired"],
        "fieldValueTypes": "double",
        "prefixFields": ["created"],
        "sparse": False,
        "name": idx_name,
    }
    try:
        resp = db._conn.post(
            f"/_api/index?collection={collection_name}",
            data=body,
        )
        if resp.status_code in (200, 201):
            log.info("created mdi-prefixed index %s on %s", idx_name, collection_name)
            return
    except Exception:
        pass

    try:
        col.add_persistent_index(
            fields=["created", "expired"],
            name=idx_name,
        )
        log.info(
            "created persistent (fallback) index %s on %s",
            idx_name,
            collection_name,
        )
    except IndexCreateError:
        log.debug("index %s already exists on %s (via fallback)", idx_name, collection_name)


def up(db: StandardDatabase) -> None:
    for name in VERSIONED_COLLECTIONS:
        _create_mdi_index(db, name)
