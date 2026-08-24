"""LangGraph node wrapping the subsumption judge (PRD §6.2 FR-2.20).

Sits between ``structural_gate`` and ``filter``, i.e. after the deterministic
link repairs and immediately before the human-in-the-loop curation breakpoint —
so a curator sees the flags at the moment they are deciding what to keep, and
nothing reaches the database unexamined.

Every design decision here is "fail open": no parent, judge disabled, LLM error,
short batch — all leave ``subsumption_verdict`` as ``None`` and the class
untouched. A judge that can block an extraction is worse than no judge.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from app.config import settings
from app.extraction.judges.subsumption import judge_subsumption
from app.extraction.state import ExtractionPipelineState, StepLog
from app.models.ontology import ExtractedClass

log = logging.getLogger(__name__)

#: Cap on the flagged-edge examples embedded in the step log. Counts are always
#: exact; only the enumerated list is truncated so a pathological run can't
#: bloat the persisted run stats.
_MAX_REPORT_ITEMS = 50


def _skip_log(start: float, reason: str) -> StepLog:
    return StepLog(
        step="subsumption_judge",
        status="skipped",
        started_at=start,
        completed_at=time.time(),
        duration_seconds=round(time.time() - start, 3),
        error=None,
        metadata={"reason": reason},
    )


def _parent_label(cls: ExtractedClass, by_uri: dict[str, str]) -> str:
    """Human-readable parent for the prompt: label if resolvable, else fragment."""
    uri = cls.parent_uri or ""
    return by_uri.get(uri) or uri.split("#")[-1].split("/")[-1] or uri


async def subsumption_judge_node(state: ExtractionPipelineState) -> dict[str, Any]:
    """Judge each candidate ``subClassOf`` edge and stamp a verdict on the class."""
    start = time.time()
    run_id = state.get("run_id", "")

    if not settings.subsumption_judge_enabled:
        return {"subsumption_report": None, "step_logs": [_skip_log(start, "disabled")]}

    result = state.get("consistency_result")
    classes: list[ExtractedClass] = list(getattr(result, "classes", []) or [])
    if not classes:
        return {"subsumption_report": None, "step_logs": [_skip_log(start, "no_input")]}

    by_uri = {c.uri: c.label for c in classes}
    candidates = [(i, c) for i, c in enumerate(classes) if c.parent_uri]
    if not candidates:
        return {"subsumption_report": None, "step_logs": [_skip_log(start, "no_subclass_edges")]}

    verdicts = await judge_subsumption(
        [
            {"child": c.label, "parent": _parent_label(c, by_uri), "child_key": str(i)}
            for i, c in candidates
        ],
        model_name=settings.subsumption_judge_model or None,
    )

    flagged: list[dict[str, Any]] = []
    judged = 0
    for (index, cls), verdict in zip(candidates, verdicts, strict=False):
        if verdict.get("is_a") is None:
            continue
        judged += 1
        stamped = {
            "is_a": bool(verdict["is_a"]),
            "relation": verdict.get("relation", ""),
            "reason": verdict.get("reason", ""),
        }
        classes[index] = cls.model_copy(update={"subsumption_verdict": stamped})
        if not stamped["is_a"]:
            flagged.append(
                {
                    "child": cls.label,
                    "parent": _parent_label(cls, by_uri),
                    "relation": stamped["relation"],
                    "reason": stamped["reason"],
                }
            )

    updated = result.model_copy(update={"classes": classes}) if result is not None else None
    report = {
        "status": "completed",
        "candidate_count": len(candidates),
        "judged_count": judged,
        "flagged_count": len(flagged),
        "flagged": flagged[:_MAX_REPORT_ITEMS],
    }

    duration = time.time() - start
    log.info(
        "subsumption_judge completed",
        extra={
            "run_id": run_id,
            "candidates": len(candidates),
            "judged": judged,
            "flagged": len(flagged),
            "duration_seconds": round(duration, 3),
        },
    )

    return {
        "consistency_result": updated,
        "subsumption_report": report,
        "current_step": "subsumption_judge",
        "step_logs": [
            StepLog(
                step="subsumption_judge",
                status="completed",
                started_at=start,
                completed_at=time.time(),
                duration_seconds=round(duration, 3),
                error=None,
                metadata={
                    "candidate_count": len(candidates),
                    "judged_count": judged,
                    "flagged_count": len(flagged),
                },
            )
        ],
    }
