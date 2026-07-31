"""LLM CQ suggestion + VSPO pitfall lint (Stream 22 CQ-PR2, PRD §6.19 FR-19.2).

Two capabilities, kept honest about automated-CQ unreliability:

* :func:`lint_cq` — a **deterministic** VSPO-style pitfall check (no LLM) that
  flags malformed competency questions (not a question, too vague, compound,
  binary yes/no, no domain term). Used both on suggestions and on human-typed CQs.
* :func:`suggest_cqs` — an LLM proposes candidate CQs from a purpose statement +
  sample source text + the ontology's class labels (NeOn-GPT-style). Suggestions
  are returned as ``status="proposed"`` and **never persisted** here — every CQ
  requires human acceptance (PRD §6.19: automated CQs are unreliable), so the API
  returns them for the curator to accept/edit in the Requirements overlay.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from arango.database import StandardDatabase

from app.db.client import get_db
from app.db.temporal_constants import NEVER_EXPIRES
from app.db.utils import run_aql

log = logging.getLogger(__name__)

# Interrogatives that open a well-formed competency question.
_INTERROGATIVES = {"what", "which", "who", "whom", "whose", "where", "when", "how", "why"}
# Yes/no openers — a CQ answerable by yes/no is a weak coverage signal (VSPO).
_BINARY_OPENERS = {"is", "are", "was", "were", "do", "does", "did", "can", "could", "has", "have"}
_STOPWORDS = (
    _INTERROGATIVES
    | _BINARY_OPENERS
    | {
        "a",
        "an",
        "the",
        "of",
        "for",
        "to",
        "in",
        "on",
        "and",
        "or",
        "by",
        "with",
        "that",
        "this",
        "these",
        "those",
        "all",
        "any",
        "each",
        "every",
        "list",
    }
)
_WORD_RE = re.compile(r"[A-Za-z0-9]+")

# VSPO pitfall codes (severity: error blocks a good CQ; warning/info advise).
PITFALL_NOT_A_QUESTION = "CQ001"
PITFALL_TOO_SHORT = "CQ002"
PITFALL_COMPOUND = "CQ003"
PITFALL_BINARY = "CQ004"
PITFALL_NO_DOMAIN_TERM = "CQ005"


def lint_cq(text: str) -> list[dict[str, str]]:
    """Return VSPO-style pitfalls for one competency question (deterministic).

    Each pitfall is ``{code, severity, message}``. An empty list means the CQ
    looks well-formed. Never raises — this runs on every keystroke in the UI.
    """
    pitfalls: list[dict[str, str]] = []
    s = str(text or "").strip()
    if not s:
        return [
            {
                "code": PITFALL_TOO_SHORT,
                "severity": "error",
                "message": "Competency question is empty.",
            }
        ]

    tokens = _WORD_RE.findall(s.lower())
    first = tokens[0] if tokens else ""

    # CQ001 — not phrased as a question.
    if not s.endswith("?") and first not in _INTERROGATIVES and first not in _BINARY_OPENERS:
        pitfalls.append(
            {
                "code": PITFALL_NOT_A_QUESTION,
                "severity": "warning",
                "message": "Not a question — start with what/which/who and end with '?'.",
            }
        )

    # CQ002 — too short / vague to be answerable.
    if len(tokens) < 4:
        pitfalls.append(
            {
                "code": PITFALL_TOO_SHORT,
                "severity": "warning",
                "message": "Too short — name the entities and relationship involved.",
            }
        )

    # CQ003 — compound (multiple questions in one). Atomic CQs are testable.
    if s.count("?") > 1 or re.search(r"\b(and|or)\b", s.lower()):
        pitfalls.append(
            {
                "code": PITFALL_COMPOUND,
                "severity": "info",
                "message": "Looks compound — split 'and'/'or' clauses into separate atomic CQs.",
            }
        )

    # CQ004 — binary yes/no question (weak coverage signal).
    if first in _BINARY_OPENERS:
        pitfalls.append(
            {
                "code": PITFALL_BINARY,
                "severity": "info",
                "message": "Yes/no question — prefer 'which/what' to enumerate entities.",
            }
        )

    # CQ005 — no domain term (only stop/interrogative words) -> nothing to ground.
    domain_terms = [t for t in tokens if t not in _STOPWORDS and len(t) >= 3]
    if not domain_terms:
        pitfalls.append(
            {
                "code": PITFALL_NO_DOMAIN_TERM,
                "severity": "warning",
                "message": "No domain term to ground — reference a class or property.",
            }
        )

    return pitfalls


def _class_labels(db: StandardDatabase, ontology_id: str, limit: int = 200) -> list[str]:
    if not db.has_collection("ontology_classes"):
        return []
    return list(
        run_aql(
            db,
            """
            FOR c IN ontology_classes
              FILTER c.ontology_id == @oid AND c.expired == @never AND c.label != null
              SORT c.label ASC
              LIMIT @n
              RETURN c.label
            """,
            bind_vars={"oid": ontology_id, "never": NEVER_EXPIRES, "n": limit},
        )
    )


_SUGGEST_SYSTEM_PROMPT = (
    "You are an ontology engineer proposing competency questions (CQs) — the "
    "questions a domain ontology must be able to answer. Given a purpose "
    "statement, the ontology's existing class labels, and optional sample source "
    "text, propose distinct, ATOMIC, answerable CQs. Each CQ must be a single "
    "question that references domain concepts (not yes/no). Respond with ONLY a "
    "JSON array of objects like "
    '[{"text": "Which suppliers ship a given product?", "priority": "high"}]. '
    "priority is one of high|medium|low. No prose, no code fences."
)


def _parse_suggestions(raw: str) -> list[dict[str, Any]]:
    text = raw.strip()
    if text.startswith("```"):
        text = "\n".join(ln for ln in text.splitlines() if not ln.strip().startswith("```")).strip()
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        log.warning("CQ suggestion output was not valid JSON")
        return []
    if not isinstance(data, list):
        return []
    out: list[dict[str, Any]] = []
    for item in data:
        if isinstance(item, dict) and str(item.get("text") or "").strip():
            out.append(item)
    return out


async def suggest_cqs(
    db: StandardDatabase | None = None,
    *,
    ontology_id: str,
    purpose: str | None = None,
    sample_texts: list[str] | None = None,
    n: int = 6,
    model: str | None = None,
) -> list[dict[str, Any]]:
    """Propose candidate CQs for an ontology (LLM). Returns ``status="proposed"``
    suggestions, each linted — NEVER persisted (human acceptance required).

    ``purpose`` defaults to the ontology's requirements-spec purpose when omitted.
    Returns ``[]`` on any LLM/parse failure (best-effort assistance).
    """
    if db is None:
        db = get_db()

    if purpose is None:
        from app.db import requirements_repo

        spec = requirements_repo.get_requirements(db, ontology_id)
        purpose = str((spec or {}).get("purpose") or "").strip()

    labels = _class_labels(db, ontology_id)
    sample = "\n".join(t.strip() for t in (sample_texts or []) if t.strip())[:4000]

    try:
        from langchain_core.messages import HumanMessage, SystemMessage

        from app.extraction.agents.extractor import _get_llm

        llm = _get_llm(model or "")
        user = (
            f"Purpose: {purpose or '(not provided)'}\n"
            f"Existing ontology classes: {json.dumps(labels)}\n"
            f"Propose up to {n} competency questions."
            + (f"\nSample source text:\n{sample}" if sample else "")
        )
        resp = await llm.ainvoke(
            [SystemMessage(content=_SUGGEST_SYSTEM_PROMPT), HumanMessage(content=user)]
        )
        raw = resp.content if isinstance(resp.content, str) else str(resp.content)
    except Exception:
        log.warning("CQ suggestion failed for ontology %s", ontology_id, exc_info=True)
        return []

    suggestions: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in _parse_suggestions(raw)[:n]:
        cq_text = str(item["text"]).strip()
        key = cq_text.lower()
        if key in seen:
            continue
        seen.add(key)
        priority = str(item.get("priority") or "medium").strip().lower()
        if priority not in {"high", "medium", "low"}:
            priority = "medium"
        suggestions.append(
            {
                "text": cq_text,
                "priority": priority,
                "status": "proposed",
                "pitfalls": lint_cq(cq_text),
            }
        )
    return suggestions
