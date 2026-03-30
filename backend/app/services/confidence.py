"""Multi-signal confidence scoring for extracted ontology classes.

Blends five independent signals into a single [0, 1] confidence score:
  1. Cross-pass agreement  (weight 0.25)
  2. LLM self-reported confidence  (weight 0.25)
  3. Structural quality  (weight 0.20)
  4. Description quality  (weight 0.15)
  5. Provenance strength  (weight 0.15)
"""

from __future__ import annotations

WEIGHT_AGREEMENT = 0.25
WEIGHT_LLM = 0.25
WEIGHT_STRUCTURAL = 0.20
WEIGHT_DESCRIPTION = 0.15
WEIGHT_PROVENANCE = 0.15


def _structural_score(
    has_properties: bool,
    has_parent: bool,
    has_children: bool,
) -> float:
    """Score in [0, 1] based on graph connectivity of the class."""
    score = 0.0
    if has_properties:
        score += 0.4
    if has_parent:
        score += 0.3
    if has_children:
        score += 0.3
    return score


def _description_score(
    description: str,
    all_descriptions: list[str],
) -> float:
    """Score in [0, 1] based on description length and uniqueness.

    A description is considered non-unique when it is very short (<20 chars)
    or when an identical copy exists among the other class descriptions.
    """
    length_score = min(len(description) / 100, 1.0) * 0.7

    is_duplicate = False
    if len(description) < 20:
        is_duplicate = True
    else:
        seen_self = False
        for other in all_descriptions:
            if other == description:
                if not seen_self:
                    seen_self = True
                    continue
                is_duplicate = True
                break
    uniqueness = 0.0 if is_duplicate else 1.0

    return length_score + uniqueness * 0.3


def _provenance_score(provenance_count: int) -> float:
    """Score in [0, 1] based on how many source chunks support this class."""
    return min(provenance_count / 3, 1.0)


def compute_class_confidence(
    agreement_ratio: float,
    llm_confidence: float,
    has_properties: bool,
    has_parent: bool,
    has_children: bool,
    description: str,
    all_descriptions: list[str],
    provenance_count: int,
) -> float:
    """Compute blended multi-signal confidence for one ontology class.

    Parameters
    ----------
    agreement_ratio:
        Fraction of extraction passes in which this class appeared (0–1).
    llm_confidence:
        Average of per-pass LLM self-reported confidence (0–1).
    has_properties:
        Whether the class has at least one property in the graph.
    has_parent:
        Whether a subclass_of edge exists FROM this class.
    has_children:
        Whether a subclass_of edge exists TO this class.
    description:
        The merged class description text.
    all_descriptions:
        Descriptions of *all* classes in the same ontology (for uniqueness check).
    provenance_count:
        Number of distinct source documents/chunks that produced this class.

    Returns
    -------
    float in [0, 1] — the composite confidence score, rounded to 3 decimals.
    """
    s_structural = _structural_score(has_properties, has_parent, has_children)
    s_description = _description_score(description, all_descriptions)
    s_provenance = _provenance_score(provenance_count)

    blended = (
        WEIGHT_AGREEMENT * agreement_ratio
        + WEIGHT_LLM * llm_confidence
        + WEIGHT_STRUCTURAL * s_structural
        + WEIGHT_DESCRIPTION * s_description
        + WEIGHT_PROVENANCE * s_provenance
    )
    return round(max(0.0, min(1.0, blended)), 3)
