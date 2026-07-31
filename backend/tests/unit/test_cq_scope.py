"""Unit tests for CQ term scoping (Stream 22 CQ-PR7, PRD §6.19 FR-19.9)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.services import cq_scope


def _spec(*texts: str) -> dict:
    return {
        "use_cases": [
            {
                "name": "UC1",
                "competency_questions": [{"text": t} for t in texts],
            }
        ]
    }


class TestCqTextTokens:
    def test_unions_text_query_and_shape_and_drops_short_tokens(self) -> None:
        db = MagicMock()
        spec = {
            "use_cases": [
                {
                    "name": "UC1",
                    "competency_questions": [
                        {
                            "text": "Which company filed a report?",
                            "query": "FOR f IN filings RETURN f",
                            "expected_answer_shape": "list of periods",
                        }
                    ],
                }
            ]
        }
        with patch.object(cq_scope.requirements_repo, "get_requirements", return_value=spec):
            toks = cq_scope.cq_text_tokens(db, "ont1")
        assert {"company", "filed", "report", "filings", "periods", "list"} <= toks
        assert "a" not in toks  # short token dropped
        assert "of" not in toks

    def test_no_spec_is_empty(self) -> None:
        db = MagicMock()
        with patch.object(cq_scope.requirements_repo, "get_requirements", return_value=None):
            assert cq_scope.cq_text_tokens(db, "ont1") == set()


class TestCqRelevantClassKeys:
    def _run(self, spec, classes):
        db = MagicMock()
        db.has_collection.return_value = True
        with (
            patch.object(cq_scope.requirements_repo, "get_requirements", return_value=spec),
            patch.object(cq_scope, "run_aql", return_value=iter(classes)),
        ):
            return cq_scope.cq_relevant_class_keys(db, "ont1")

    def test_keeps_only_classes_referenced_by_cqs(self) -> None:
        spec = _spec("Which company filed a report?")
        classes = [
            {"key": "Company", "label": "Company"},
            {"key": "Report", "label": "Report"},
            {"key": "Zebra", "label": "Zebra"},  # not referenced
        ]
        assert self._run(spec, classes) == {"Company", "Report"}

    def test_multiword_label_matches_on_any_token(self) -> None:
        spec = _spec("List every financial filing")
        classes = [
            {"key": "FF", "label": "Financial Filing"},  # both tokens hit
            {"key": "Person", "label": "Person"},
        ]
        assert self._run(spec, classes) == {"FF"}

    def test_no_cqs_returns_empty(self) -> None:
        assert self._run(None, [{"key": "X", "label": "X"}]) == set()


class TestCqAlignmentScope:
    def test_builds_per_source_scope(self) -> None:
        db = MagicMock()

        def fake_keys(_db, oid):
            return {"ontA": {"Account"}, "ontB": {"Acct"}}[oid]

        with patch.object(cq_scope, "cq_relevant_class_keys", side_effect=fake_keys):
            scope = cq_scope.cq_alignment_scope(db, ["ontA", "ontB"])
        assert scope == {"ontA": {"Account"}, "ontB": {"Acct"}}

    def test_all_empty_returns_none_not_empty_scope(self) -> None:
        # Critical: no CQ-relevant class anywhere must mean "align everything"
        # (scope=None), never "align nothing" (empty scope filters all pairs).
        db = MagicMock()
        with patch.object(cq_scope, "cq_relevant_class_keys", return_value=set()):
            assert cq_scope.cq_alignment_scope(db, ["ontA", "ontB"]) is None
