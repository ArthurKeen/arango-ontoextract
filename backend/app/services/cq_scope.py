"""Competency-question term scoping (Stream 22 CQ-PR7, PRD §6.19 FR-19.9).

Ties the three use-case capabilities together: the CQ *term set* (the ontology
entities a use case's competency questions reference) scopes which alignment
correspondences (§6.17) and which A-box individuals (§6.18) actually matter — a
use-case-scoped master + selective A-box.

The term set is derived *lexically* (deterministic, no LLM/embedding cost): a
class is CQ-relevant when a token of its label appears in the union of CQ texts,
formalized queries, and expected-answer shapes. This is a coarse-but-honest
priority signal — the same philosophy as ``serialize_cq_scope_context`` (a
priority signal, not an exclusive whitelist) — that can be refined later with the
embedding / LLM machinery. Callers must treat an EMPTY result as "no scope
available" and fall back to unscoped behaviour, never as "scope everything out".
"""

from __future__ import annotations

import logging
import re
from typing import Any

from arango.database import StandardDatabase

from app.db import requirements_repo
from app.db.client import get_db
from app.db.temporal_constants import NEVER_EXPIRES
from app.db.utils import run_aql

log = logging.getLogger(__name__)

_WORD_RE = re.compile(r"[a-z0-9]+")

# Tokens shorter than this are dropped from both CQ text and labels so a
# stop-word ("of", "a", "id") can't make an unrelated class look CQ-relevant.
_MIN_TOKEN_LEN = 3


def _tokens(text: Any) -> set[str]:
    return {t for t in _WORD_RE.findall(str(text or "").lower()) if len(t) >= _MIN_TOKEN_LEN}


def cq_text_tokens(db: StandardDatabase | None, ontology_id: str) -> set[str]:
    """Union of word tokens across an ontology's CQ texts + queries + answer shapes.

    Returns ``set()`` when the ontology has no requirements spec or no CQs.
    """
    if db is None:
        db = get_db()
    spec = requirements_repo.get_requirements(db, ontology_id)
    if not spec:
        return set()
    toks: set[str] = set()
    for cq in requirements_repo.iter_competency_questions(spec):
        toks |= _tokens(cq.get("text"))
        toks |= _tokens(cq.get("query"))
        toks |= _tokens(cq.get("expected_answer_shape"))
    return toks


def cq_relevant_class_keys(db: StandardDatabase | None, ontology_id: str) -> set[str]:
    """Keys of the ontology's live classes referenced by its competency questions.

    A class is CQ-relevant when any token of its label (>= 3 chars) appears in the
    CQ token set. Deterministic and lexical. Returns ``set()`` when there are no
    CQs or no matching classes — callers MUST read empty as "no CQ scope" and fall
    back to unscoped behaviour rather than filtering everything out.
    """
    if db is None:
        db = get_db()
    cq_toks = cq_text_tokens(db, ontology_id)
    if not cq_toks or not db.has_collection("ontology_classes"):
        return set()
    rows = run_aql(
        db,
        """
        FOR c IN ontology_classes
          FILTER c.ontology_id == @oid AND c.expired == @never
          RETURN {key: c._key, label: c.label}
        """,
        bind_vars={"oid": ontology_id, "never": NEVER_EXPIRES},
    )
    keys: set[str] = set()
    for r in rows:
        if _tokens(r.get("label")) & cq_toks:
            keys.add(str(r.get("key")))
    return keys


def cq_alignment_scope(
    db: StandardDatabase | None, source_ontology_ids: list[str]
) -> dict[str, set[str]] | None:
    """Build a ``generate_candidates`` scope from each source's CQ-relevant classes.

    Returns ``{ontology_id: {class_key, ...}}`` for scoping alignment to
    correspondences touching a CQ-relevant class, or ``None`` when NO source has
    any CQ-relevant class (so the caller aligns everything instead of nothing).
    """
    if db is None:
        db = get_db()
    scope: dict[str, set[str]] = {}
    total = 0
    for oid in dict.fromkeys(source_ontology_ids):
        keys = cq_relevant_class_keys(db, oid)
        scope[oid] = keys
        total += len(keys)
    if total == 0:
        log.info("[cq_scope] no CQ-relevant classes across sources; alignment stays unscoped")
        return None
    return scope
