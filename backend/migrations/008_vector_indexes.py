"""008 — HNSW vector index on ``chunks.embedding`` for similarity search.

Used for RAG context retrieval and entity resolution vector blocking.
Dimension defaults to 1536 (OpenAI ``text-embedding-3-small``).
"""

from __future__ import annotations

import logging

from arango.database import StandardDatabase

log = logging.getLogger(__name__)

INDEX_NAME = "idx_chunks_embedding_hnsw"
EMBEDDING_DIMENSION = 1536


def up(db: StandardDatabase) -> None:
    col = db.collection("chunks")

    for idx in col.indexes():
        if idx.get("name") == INDEX_NAME:
            log.debug("vector index %s already exists", INDEX_NAME)
            return

    body = {
        "type": "inverted",
        "name": INDEX_NAME,
        "fields": [
            {
                "name": "embedding",
                "aql": False,
            },
        ],
        "features": ["approximation"],
        "params": {
            "vector": True,
            "dimension": EMBEDDING_DIMENSION,
            "metric": "cosine",
            "nLists": 10,
        },
    }
    try:
        resp = db._conn.post(
            "/_api/index?collection=chunks",
            data=body,
        )
        if resp.status_code in (200, 201):
            log.info("created HNSW vector index %s on chunks.embedding", INDEX_NAME)
            return
        log.warning(
            "vector index creation returned %d — may require ArangoDB 3.12+",
            resp.status_code,
        )
    except Exception as exc:
        log.warning(
            "vector index creation failed (ArangoDB version may not support it): %s",
            exc,
        )
