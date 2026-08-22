"""Document-furniture rejection at extraction (FR-2.18).

`Page 697` reached the JLR ontology as a class. It passes both pre-existing
filters — GENERIC_TERMS is exact-match, and the low-confidence rule only fires
on single-word labels — so a two-token label at moderate confidence sails
through. These tests pin BOTH directions: the artefact is rejected, and the
legitimate concept that merely starts with the same word is not.
"""

from __future__ import annotations

import pytest

from app.extraction.agents.filter import _remove_structural_artifacts, is_structural_artifact
from app.models.ontology import ExtractedClass


@pytest.mark.parametrize(
    "label",
    [
        "Page 697",
        "Page 812",
        "pages 4",
        "pg 9",
        "Figure 4",
        "fig 12",
        "FIGURE 3",
        "Table 12",
        "Table 12.3",
        "Table 4-2",
        "tbl 7",
        "Section 3.2",
        "sect 9",
        "Chapter 11",
        "chap 2",
        "Appendix B",
        "Appendix B2",
        "Appendix A.1",
        "Annex C",
        "Step 7",
        "Note 5",
        "Item 3",
        "Paragraph 4",
        "para 12",
        "Exhibit 2",
        "Plate C",
        "Diagram 8",
        "Illustration 15",
        "Page  697",
        "Page: 697",
        "Page #697",
        "Page 7a",
    ],
)
def test_rejects_document_furniture(label: str) -> None:
    assert is_structural_artifact(label), f"should reject {label!r}"


@pytest.mark.parametrize(
    "label",
    [
        # The trailing number is what distinguishes furniture from a concept.
        "Page Layout",
        "Table of Contents",
        "Section Heading",
        "Chapter Summary",
        "Figure Caption Style",
        "Step by Step",
        "Appendix",
        "Page",
        "Note",
        "Notebook",
        "Table saw",
        "Paragraph Style",
        "Noteworthy Item",
        # Real domain concepts must be untouched.
        "Vehicle Security",
        "Rear Traffic Monitor",
        "Tyre Pressure",
        # A number alone is not furniture — GENERIC_TERMS/confidence handle those.
        "2024",
        "V8",
    ],
)
def test_keeps_legitimate_concepts(label: str) -> None:
    assert not is_structural_artifact(label), f"should keep {label!r}"


def _cls(label: str) -> ExtractedClass:
    return ExtractedClass(
        uri=f"http://example.org/ontology#{label.replace(' ', '')}",
        label=label,
        description="",
        confidence=0.6,
    )


class TestRemoveStructuralArtifacts:
    def test_filters_only_the_artefacts(self) -> None:
        classes = [
            _cls("Page 697"),
            _cls("Vehicle Security"),
            _cls("Figure 4"),
            _cls("Page Layout"),
        ]
        kept = [c.label for c in _remove_structural_artifacts(classes)]
        assert kept == ["Vehicle Security", "Page Layout"]

    def test_empty_input_is_safe(self) -> None:
        assert _remove_structural_artifacts([]) == []

    def test_leading_and_trailing_whitespace_does_not_hide_an_artefact(self) -> None:
        assert _remove_structural_artifacts([_cls("  Page 812  ")]) == []
