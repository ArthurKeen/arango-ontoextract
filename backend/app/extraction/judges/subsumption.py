"""Subsumption judge — the "is every X a Y?" test (PRD §6.2 FR-2.20).

Why this exists, in numbers: of the 753 ``rdfs:subClassOf`` edges in the
1688-class JLR extraction, roughly 52% are not subsumption at all (§6.21). The
extractor has exactly one hierarchical relation available, so every association
it senses — part-of, has-attribute, documented-by — gets flattened into
``subClassOf``. Nothing in the pipeline currently asks whether the claim is true.

Two design choices worth stating:

* **Flag, never silently drop.** A wrong subclass edge and a missing one are
  both defects. An extractor that quietly discards its own output is harder to
  debug than one that reports, and a curator can act on a flagged edge but not
  on a vanished one.
* **Few-shot from THIS corpus.** The examples below are real failures observed
  in the JLR data, not invented ones. An abstract instruction ("check the edge
  is really subsumption") measurably underperforms showing the model the exact
  mistakes it made.

Once the upper ontology lands (FR-21.7) the judge can also name the relation the
kinds license. Until then it flags with a reason, which needs no modelling
decision and so is not blocked on that work.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from app.config import settings
from app.extraction.agents.extractor import _get_llm

log = logging.getLogger(__name__)

#: Real edges from the JLR extraction. Failures first — the model needs to see
#: what "wrong" looks like in this domain, where the wrong answers are plausible.
FEW_SHOT: list[dict[str, str]] = [
    # part-of masquerading as is-a: the dominant failure, ~most of the 52%
    {
        "child": "Airbag",
        "parent": "Supplementary Restraint System",
        "verdict": "no",
        "reason": "An airbag is a component OF the restraint system, not a kind of it.",
    },
    {
        "child": "Hose",
        "parent": "Portable Rinse System",
        "verdict": "no",
        "reason": "A hose is a part of the rinse system.",
    },
    {
        "child": "Smart Key Component",
        "parent": "Smart Key System",
        "verdict": "no",
        "reason": "The label says component: it is part of the system, not a kind of system.",
    },
    {
        "child": "Tyre",
        "parent": "Vehicle",
        "verdict": "no",
        "reason": "A tyre is fitted to a vehicle; it is not a kind of vehicle.",
    },
    {
        "child": "Roof Rack",
        "parent": "Vehicle",
        "verdict": "no",
        "reason": "An accessory mounted on a vehicle, not a kind of vehicle.",
    },
    # attribute / measurement mistaken for a subclass
    {
        "child": "Speed Rating",
        "parent": "Tyre",
        "verdict": "no",
        "reason": "A speed rating is a property of a tyre. Is every speed rating a tyre? No.",
    },
    # document about a thing, mistaken for the thing
    {
        "child": "Tyre Manufacturer Instructions",
        "parent": "Tyre",
        "verdict": "no",
        "reason": "A document describing tyres is not itself a tyre.",
    },
    # kind confusion: a capability is not a physical part
    {
        "child": "Safety Feature",
        "parent": "Vehicle Component",
        "verdict": "no",
        "reason": "A feature is a capability exposed to a user, not a physical component.",
    },
    # genuine subsumption — the model must not reject everything
    {
        "child": "Winter Tyre",
        "parent": "Tyre",
        "verdict": "yes",
        "reason": "Every winter tyre is a tyre.",
    },
    {
        "child": "Unleaded Fuel",
        "parent": "Fuel Type",
        "verdict": "yes",
        "reason": "Unleaded fuel is a kind of fuel type.",
    },
    {
        "child": "Child Seat",
        "parent": "Child Restraint",
        "verdict": "yes",
        "reason": "Every child seat is a child restraint.",
    },
]

_SYSTEM = (
    "You validate subsumption in an OWL ontology. For each candidate edge, answer "
    "ONE question: is EVERY instance of the child also an instance of the parent?\n\n"
    "Answer 'no' when the real relationship is any of:\n"
    "  part-of        — the child is a component or accessory of the parent\n"
    "  attribute-of   — the child is a property, measure, rating or setting of the parent\n"
    "  document-about — the child is a manual, label, record or instruction about the parent\n"
    "  process-on     — the child is a procedure, operation or maintenance action on the parent\n"
    "  feature-of     — the child is a capability the parent exposes, not a kind of it\n"
    "  unrelated      — no clear relationship\n\n"
    "Answer 'yes' ONLY for genuine subsumption. A shared word in the two labels is "
    "not evidence: 'Tyre Pressure' is not a kind of 'Tyre'.\n\n"
    'Return JSON only: {"verdicts": [{"child": str, "parent": str, '
    '"is_a": bool, "relation": str, "reason": str}]}'
)


def _few_shot_block() -> str:
    lines = ["Worked examples from this corpus:"]
    for ex in FEW_SHOT:
        lines.append(
            f"  is every «{ex['child']}» a «{ex['parent']}»? "
            f"{ex['verdict'].upper()} — {ex['reason']}"
        )
    return "\n".join(lines)


def build_prompt(edges: list[dict[str, str]]) -> str:
    """User prompt for a batch of candidate subclass edges."""
    listing = "\n".join(
        f"  {i + 1}. child=«{e['child']}» parent=«{e['parent']}»" for i, e in enumerate(edges)
    )
    return (
        f"{_few_shot_block()}\n\n"
        f"Now judge these {len(edges)} candidate subClassOf edges:\n{listing}\n\n"
        "Return one verdict per edge, in the same order."
    )


def _parse(text: str) -> list[dict[str, Any]]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```")[1]
        cleaned = cleaned[4:] if cleaned.startswith("json") else cleaned
    data = json.loads(cleaned)
    verdicts = data.get("verdicts", data if isinstance(data, list) else [])
    return [v for v in verdicts if isinstance(v, dict)]


async def judge_subsumption(
    edges: list[dict[str, str]],
    *,
    model_name: str | None = None,
    batch_size: int = 25,
) -> list[dict[str, Any]]:
    """Judge candidate subclass edges. Returns one verdict dict per input edge.

    Fails OPEN: if the judge errors or returns a malformed batch, those edges
    come back unjudged (``is_a=None``) rather than blocking extraction. A judge
    outage must not stop an ontology being extracted — it should only stop the
    extraction being trusted.
    """
    if not edges:
        return []
    resolved = model_name or settings.llm_extraction_model
    out: list[dict[str, Any]] = []

    for start in range(0, len(edges), batch_size):
        batch = edges[start : start + batch_size]
        try:
            llm = _get_llm(resolved)
            response = await llm.ainvoke(
                [SystemMessage(content=_SYSTEM), HumanMessage(content=build_prompt(batch))]
            )
            verdicts = _parse(str(response.content))
        except Exception:
            log.warning("subsumption judge failed for a batch of %d", len(batch), exc_info=True)
            verdicts = []

        for i, edge in enumerate(batch):
            v = verdicts[i] if i < len(verdicts) else {}
            out.append(
                {
                    "child": edge.get("child"),
                    "parent": edge.get("parent"),
                    "child_key": edge.get("child_key"),
                    "parent_key": edge.get("parent_key"),
                    # None means "not judged" — distinct from "judged and passed".
                    "is_a": v.get("is_a") if isinstance(v.get("is_a"), bool) else None,
                    "relation": v.get("relation") or "",
                    "reason": v.get("reason") or "",
                }
            )
    return out
