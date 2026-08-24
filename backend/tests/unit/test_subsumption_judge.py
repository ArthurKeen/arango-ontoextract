"""Tests for the subsumption judge (PRD §6.2 FR-2.20).

The judge exists because ~52% of the 753 ``subClassOf`` edges in the 1688-class
JLR extraction were not subsumption at all. The properties that must hold:

* it flags, never drops -- a rejected edge still reaches the database, carrying
  the verdict, because a vanished edge is harder to curate than a wrong one;
* it fails open -- an LLM outage degrades to "unjudged", never to a blocked or
  truncated extraction;
* "unjudged" and "judged and passed" are distinguishable downstream.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.extraction.judges import subsumption
from app.extraction.judges.subsumption import FEW_SHOT, build_prompt, judge_subsumption
from app.extraction.judges.subsumption_node import subsumption_judge_node
from app.models.ontology import ExtractedClass, ExtractionResult


def _cls(label: str, *, parent: str | None = None) -> ExtractedClass:
    return ExtractedClass(
        uri=f"http://x#{label.replace(' ', '')}",
        label=label,
        description="",
        parent_uri=f"http://x#{parent.replace(' ', '')}" if parent else None,
        confidence=0.9,
    )


def _llm_returning(payload: str) -> Any:
    llm = AsyncMock()
    llm.ainvoke.return_value = type("R", (), {"content": payload})()
    return llm


# --- the few-shot dictionary -------------------------------------------------


def test_few_shot_covers_both_verdicts() -> None:
    """A dictionary of only-failures teaches the model to reject everything."""
    verdicts = {ex["verdict"] for ex in FEW_SHOT}
    assert verdicts == {"yes", "no"}
    assert sum(1 for e in FEW_SHOT if e["verdict"] == "yes") >= 3
    assert sum(1 for e in FEW_SHOT if e["verdict"] == "no") >= 5


def test_few_shot_examples_reach_the_prompt() -> None:
    prompt = build_prompt([{"child": "Brake Pad", "parent": "Brake"}])
    for example in ("Airbag", "Speed Rating", "Winter Tyre"):
        assert example in prompt
    assert "Brake Pad" in prompt


def test_extraction_prompts_carry_the_same_dictionary() -> None:
    """Gemini's second recommendation: teach the extractor, not just the judge."""
    from app.extraction.prompts import tier1_standard, tier1_technical, tier1_visual_aware

    for module in (tier1_standard, tier1_technical, tier1_visual_aware):
        source = "".join(str(v) for v in vars(module).values() if isinstance(v, str))
        assert "SUBCLASS DISCIPLINE" in source, module.__name__
        assert "Airbag" in source, module.__name__


# --- the judge itself --------------------------------------------------------


@pytest.mark.asyncio
async def test_judges_each_edge_and_returns_one_verdict_per_input() -> None:
    payload = (
        '{"verdicts": ['
        '{"child": "Airbag", "parent": "SRS", "is_a": false, '
        '"relation": "part-of", "reason": "component"},'
        '{"child": "Winter Tyre", "parent": "Tyre", "is_a": true, '
        '"relation": "is-a", "reason": "genuine"}]}'
    )
    with patch.object(subsumption, "_get_llm", return_value=_llm_returning(payload)):
        out = await judge_subsumption(
            [
                {"child": "Airbag", "parent": "SRS"},
                {"child": "Winter Tyre", "parent": "Tyre"},
            ]
        )
    assert [v["is_a"] for v in out] == [False, True]
    assert out[0]["relation"] == "part-of"


@pytest.mark.asyncio
async def test_llm_failure_leaves_edges_unjudged_rather_than_rejected() -> None:
    """Fail open. An outage must not silently prune the hierarchy."""
    llm = AsyncMock()
    llm.ainvoke.side_effect = RuntimeError("503")
    with patch.object(subsumption, "_get_llm", return_value=llm):
        out = await judge_subsumption([{"child": "A", "parent": "B"}])
    assert len(out) == 1
    assert out[0]["is_a"] is None  # not False -- that would mean "rejected"


@pytest.mark.asyncio
async def test_short_response_leaves_the_remainder_unjudged() -> None:
    payload = '{"verdicts": [{"child": "A", "parent": "B", "is_a": true}]}'
    with patch.object(subsumption, "_get_llm", return_value=_llm_returning(payload)):
        out = await judge_subsumption(
            [{"child": "A", "parent": "B"}, {"child": "C", "parent": "D"}]
        )
    assert [v["is_a"] for v in out] == [True, None]


@pytest.mark.asyncio
async def test_batches_are_split_at_the_batch_size() -> None:
    payload = '{"verdicts": []}'
    llm = _llm_returning(payload)
    with patch.object(subsumption, "_get_llm", return_value=llm):
        await judge_subsumption([{"child": f"C{i}", "parent": "P"} for i in range(7)], batch_size=3)
    assert llm.ainvoke.await_count == 3  # 3 + 3 + 1


@pytest.mark.asyncio
async def test_fenced_json_is_parsed() -> None:
    payload = '```json\n{"verdicts": [{"child": "A", "parent": "B", "is_a": false}]}\n```'
    with patch.object(subsumption, "_get_llm", return_value=_llm_returning(payload)):
        out = await judge_subsumption([{"child": "A", "parent": "B"}])
    assert out[0]["is_a"] is False


# --- the pipeline node -------------------------------------------------------


def _state(classes: list[ExtractedClass]) -> dict[str, Any]:
    return {
        "run_id": "r1",
        "consistency_result": ExtractionResult(pass_number=1, model="test", classes=classes),
    }


@pytest.mark.asyncio
async def test_node_stamps_verdicts_and_keeps_every_class() -> None:
    classes = [_cls("Airbag", parent="SRS"), _cls("SRS"), _cls("Winter Tyre", parent="Tyre")]
    verdicts = [
        {"is_a": False, "relation": "part-of", "reason": "component of"},
        {"is_a": True, "relation": "is-a", "reason": "genuine"},
    ]
    with patch(
        "app.extraction.judges.subsumption_node.judge_subsumption",
        AsyncMock(return_value=verdicts),
    ):
        out = await subsumption_judge_node(_state(classes))

    result = out["consistency_result"]
    assert len(result.classes) == 3, "the judge must not drop classes"
    assert result.classes[0].subsumption_verdict["is_a"] is False
    assert result.classes[1].subsumption_verdict is None, "no parent -> never judged"
    assert result.classes[2].subsumption_verdict["is_a"] is True
    assert out["subsumption_report"]["flagged_count"] == 1
    assert out["subsumption_report"]["flagged"][0]["child"] == "Airbag"


@pytest.mark.asyncio
async def test_node_passes_parent_labels_not_uris_to_the_judge() -> None:
    """«Airbag» vs «SRS» is judgeable; «http://x#SRS» is noise in the prompt."""
    captured: dict[str, Any] = {}

    async def _capture(edges: list[dict[str, str]], **kw: Any) -> list[dict[str, Any]]:
        captured["edges"] = edges
        return [{"is_a": True}]

    with patch("app.extraction.judges.subsumption_node.judge_subsumption", _capture):
        await subsumption_judge_node(_state([_cls("Airbag", parent="SRS"), _cls("SRS")]))
    assert captured["edges"] == [{"child": "Airbag", "parent": "SRS", "child_key": "0"}]


@pytest.mark.asyncio
async def test_node_is_a_pass_through_when_disabled() -> None:
    classes = [_cls("Airbag", parent="SRS")]
    with patch("app.extraction.judges.subsumption_node.settings") as cfg:
        cfg.subsumption_judge_enabled = False
        out = await subsumption_judge_node(_state(classes))
    assert out["subsumption_report"] is None
    assert "consistency_result" not in out
    assert out["step_logs"][0]["status"] == "skipped"


@pytest.mark.asyncio
async def test_node_skips_when_there_are_no_subclass_edges() -> None:
    with patch("app.extraction.judges.subsumption_node.judge_subsumption") as judge:
        out = await subsumption_judge_node(_state([_cls("Airbag"), _cls("SRS")]))
    judge.assert_not_called()
    assert out["step_logs"][0]["metadata"]["reason"] == "no_subclass_edges"


@pytest.mark.asyncio
async def test_unjudged_edges_are_left_alone() -> None:
    classes = [_cls("Airbag", parent="SRS")]
    with patch(
        "app.extraction.judges.subsumption_node.judge_subsumption",
        AsyncMock(return_value=[{"is_a": None, "relation": "", "reason": ""}]),
    ):
        out = await subsumption_judge_node(_state(classes))
    assert out["consistency_result"].classes[0].subsumption_verdict is None
    assert out["subsumption_report"]["judged_count"] == 0
    assert out["subsumption_report"]["flagged_count"] == 0


# --- pipeline topology -------------------------------------------------------


def test_judge_runs_before_the_curation_breakpoint() -> None:
    from app.extraction.pipeline import _NEXT_STEPS

    assert _NEXT_STEPS["structural_gate"] == ["subsumption_judge"]
    assert _NEXT_STEPS["subsumption_judge"] == ["filter"]
