"""Unit tests for CQ suggestion + VSPO pitfall lint (Stream 22 CQ-PR2, FR-19.2)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import cq_suggest


class TestLintCq:
    def test_wellformed_question_has_no_pitfalls(self) -> None:
        assert cq_suggest.lint_cq("Which suppliers ship a given product?") == []

    def test_empty_is_error(self) -> None:
        out = cq_suggest.lint_cq("   ")
        assert out and out[0]["severity"] == "error"

    def test_not_a_question_flagged(self) -> None:
        codes = {p["code"] for p in cq_suggest.lint_cq("Suppliers of products in Europe")}
        assert cq_suggest.PITFALL_NOT_A_QUESTION in codes

    def test_too_short_flagged(self) -> None:
        codes = {p["code"] for p in cq_suggest.lint_cq("Who?")}
        assert cq_suggest.PITFALL_TOO_SHORT in codes

    def test_compound_flagged(self) -> None:
        codes = {
            p["code"]
            for p in cq_suggest.lint_cq(
                "Which suppliers ship products and which customers buy them?"
            )
        }
        assert cq_suggest.PITFALL_COMPOUND in codes

    def test_binary_flagged(self) -> None:
        codes = {p["code"] for p in cq_suggest.lint_cq("Is the supplier active in Europe?")}
        assert cq_suggest.PITFALL_BINARY in codes

    def test_no_domain_term_flagged(self) -> None:
        codes = {p["code"] for p in cq_suggest.lint_cq("What is the of a the?")}
        assert cq_suggest.PITFALL_NO_DOMAIN_TERM in codes


class TestParseSuggestions:
    def test_strips_code_fences(self) -> None:
        raw = '```json\n[{"text": "Which X?", "priority": "high"}]\n```'
        out = cq_suggest._parse_suggestions(raw)
        assert out == [{"text": "Which X?", "priority": "high"}]

    def test_bad_json_is_empty(self) -> None:
        assert cq_suggest._parse_suggestions("not json") == []

    def test_drops_textless_items(self) -> None:
        assert cq_suggest._parse_suggestions('[{"priority": "high"}, {"text": " "}]') == []


class TestSuggestCqs:
    @pytest.mark.asyncio
    async def test_suggests_lints_dedups_and_never_persists(self) -> None:
        db = MagicMock()
        db.has_collection.return_value = True
        llm = MagicMock()
        llm.ainvoke = AsyncMock(
            return_value=MagicMock(
                content=(
                    '[{"text": "Which suppliers ship a product?", "priority": "high"},'
                    ' {"text": "Which suppliers ship a product?", "priority": "low"},'  # dup
                    ' {"text": "Is it active?", "priority": "weird"}]'  # binary + bad priority
                )
            )
        )
        with (
            patch.object(cq_suggest, "run_aql", return_value=iter(["Supplier", "Product"])),
            patch("app.extraction.agents.extractor._get_llm", return_value=llm),
        ):
            out = await cq_suggest.suggest_cqs(db, ontology_id="ont1", purpose="track supply")
        # dedup -> 2 unique; all proposed; second's bad priority normalized; linted.
        assert [s["text"] for s in out] == [
            "Which suppliers ship a product?",
            "Is it active?",
        ]
        assert all(s["status"] == "proposed" for s in out)
        assert out[1]["priority"] == "medium"  # 'weird' -> default
        assert any(p["code"] == cq_suggest.PITFALL_BINARY for p in out[1]["pitfalls"])
        # never persisted
        db.collection.assert_not_called()

    @pytest.mark.asyncio
    async def test_llm_failure_returns_empty(self) -> None:
        db = MagicMock()
        db.has_collection.return_value = True
        with (
            patch.object(cq_suggest, "run_aql", return_value=iter([])),
            patch(
                "app.extraction.agents.extractor._get_llm",
                side_effect=RuntimeError("no key"),
            ),
        ):
            out = await cq_suggest.suggest_cqs(db, ontology_id="ont1", purpose="x")
        assert out == []
