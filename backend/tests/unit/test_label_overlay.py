"""Read-time curated-label overlay (PRD §6.20 FR-20.4).

The headline behaviour under test is SURVIVAL: a curated label must still be the
label a reader sees after extraction has rewritten the underlying entity
document. Everything else here guards the ways an overlay can quietly do damage —
blanking a description, dropping uncurated rows, or taking down a read path when
the lexicon is unavailable.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.services import label_overlay

URI = "http://example.org/crm#ContactRole"

DECISION = {
    "concept_uri": URI,
    "label": "job title",
    "description": None,
    "decided_by": "arthur",
    "decided_at": 1000.0,
    "concept_type": "datatype_property",
}


class TestSurvivesReExtraction:
    """FR-20.5 — the overriding property."""

    def test_curated_label_wins_over_freshly_extracted_row(self) -> None:
        # This row is exactly what extraction writes on every run: it rebuilds
        # `_key` from the LLM's label and re-inserts with overwrite=True, so the
        # document reverts to "role" no matter what the curator chose.
        re_extracted = {"_key": "Contact_role", "uri": URI, "label": "role"}

        out = label_overlay.apply_to_rows([re_extracted], {URI: DECISION})

        assert out[0]["label"] == "job title"
        # The pre-curation label stays visible so a curator can see what the
        # extractor called it, rather than the decision looking like ground truth.
        assert out[0]["extracted_label"] == "role"
        assert out[0]["curated_label"] is True
        assert out[0]["curated_by"] == "arthur"

    def test_collapses_the_resurrection_duplicate(self) -> None:
        # A curator edit expires the original document and writes the new label
        # under a fresh _key; a later extraction revives the original key via
        # overwrite=True. Both rows are then live and share a uri — the overlay
        # must resolve them to ONE label rather than showing "role" beside
        # "job title".
        resurrected = {"_key": "Contact_role", "uri": URI, "label": "role"}
        curated_version = {"_key": "918273", "uri": URI, "label": "job title"}

        out = label_overlay.apply_to_rows([resurrected, curated_version], {URI: DECISION})

        assert [r["label"] for r in out] == ["job title", "job title"]

    def test_join_is_on_uri_not_key(self) -> None:
        # _key is rebuilt from the label by extraction, so it cannot be the join.
        rows = [{"_key": "totally_different_key", "uri": URI, "label": "role"}]
        assert label_overlay.apply_to_rows(rows, {URI: DECISION})[0]["label"] == "job title"


class TestApplyToRows:
    def test_uncurated_rows_pass_through_untouched(self) -> None:
        row = {"_key": "k", "uri": "http://example.org#Other", "label": "role"}
        out = label_overlay.apply_to_rows([row], {URI: DECISION})
        # Same object, not a copy: the overlay costs nothing without curation.
        assert out[0] is row
        assert "curated_label" not in out[0]

    def test_empty_decisions_short_circuits(self) -> None:
        rows = [{"uri": URI, "label": "role"}]
        assert label_overlay.apply_to_rows(rows, {}) is rows

    def test_does_not_blank_description_when_decision_has_none(self) -> None:
        # A rename that did not rewrite the description must keep the extracted
        # one, or curating a label silently destroys documentation.
        row = {"uri": URI, "label": "role", "description": "extracted prose"}
        out = label_overlay.apply_to_rows([row], {URI: DECISION})
        assert out[0]["description"] == "extracted prose"

    def test_overrides_description_when_decision_supplies_one(self) -> None:
        decision = {**DECISION, "description": "The person's job title."}
        row = {"uri": URI, "label": "role", "description": "extracted prose"}
        out = label_overlay.apply_to_rows([row], {URI: decision})
        assert out[0]["description"] == "The person's job title."

    def test_row_without_uri_is_untouched(self) -> None:
        row = {"_key": "k", "label": "role"}
        assert label_overlay.apply_to_rows([row], {URI: DECISION})[0] is row

    def test_does_not_mutate_the_input_row(self) -> None:
        row = {"uri": URI, "label": "role"}
        label_overlay.apply_to_rows([row], {URI: DECISION})
        assert row["label"] == "role"

    def test_honours_a_custom_uri_field(self) -> None:
        row = {"concept_uri": URI, "label": "role"}
        out = label_overlay.apply_to_rows([row], {URI: DECISION}, uri_field="concept_uri")
        assert out[0]["label"] == "job title"


class TestApplyForOntology:
    def test_fetches_decisions_and_applies_them(self) -> None:
        db = MagicMock()
        rows = [{"uri": URI, "label": "role"}]
        with patch.object(
            label_overlay.lexicon_repo, "live_decisions_by_uri", return_value={URI: DECISION}
        ) as mk:
            out = label_overlay.apply_for_ontology(db, "ont1", rows)
        assert out[0]["label"] == "job title"
        assert mk.call_args.kwargs["ontology_id"] == "ont1"

    def test_fails_open_when_the_lexicon_lookup_errors(self) -> None:
        # A degraded read beats a 500 on the canvas.
        db = MagicMock()
        rows = [{"uri": URI, "label": "role"}]
        with patch.object(
            label_overlay.lexicon_repo,
            "live_decisions_by_uri",
            side_effect=RuntimeError("collection gone"),
        ):
            out = label_overlay.apply_for_ontology(db, "ont1", rows)
        assert out[0]["label"] == "role"

    def test_empty_rows_skip_the_lookup_entirely(self) -> None:
        db = MagicMock()
        with patch.object(label_overlay.lexicon_repo, "live_decisions_by_uri") as mk:
            assert label_overlay.apply_for_ontology(db, "ont1", []) == []
        mk.assert_not_called()


class TestResolvedLabel:
    def test_returns_curated_label(self) -> None:
        db = MagicMock()
        with patch.object(label_overlay.lexicon_repo, "get_live_decision", return_value=DECISION):
            assert label_overlay.resolved_label(db, concept_uri=URI, fallback="role") == (
                "job title"
            )

    def test_falls_back_when_undecided(self) -> None:
        db = MagicMock()
        with patch.object(label_overlay.lexicon_repo, "get_live_decision", return_value=None):
            assert label_overlay.resolved_label(db, concept_uri=URI, fallback="role") == "role"

    def test_falls_back_on_empty_uri_without_a_lookup(self) -> None:
        db = MagicMock()
        with patch.object(label_overlay.lexicon_repo, "get_live_decision") as mk:
            assert label_overlay.resolved_label(db, concept_uri="", fallback="role") == "role"
        mk.assert_not_called()

    def test_falls_back_when_the_lookup_errors(self) -> None:
        db = MagicMock()
        with patch.object(
            label_overlay.lexicon_repo, "get_live_decision", side_effect=RuntimeError("boom")
        ):
            assert label_overlay.resolved_label(db, concept_uri=URI, fallback="role") == "role"
