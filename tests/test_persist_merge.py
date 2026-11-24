"""Unit test for extraction/nodes/persist.py's EPISTEMIC_PRIORITY - the rule that
picks which agreeing proposal "represents" a merged Extraction row (field_name,
field_category, value, evidence_type all come from this one, while every proposal
in the group still gets its own Citation attached). Covers the ordering itself
(explicit beats inferred beats undetermined) and the default for a missing/unknown
epistemic_status, without needing a DB - _persist_merged's actual DB writes aren't
unit-testable here, but the selection rule it relies on is a pure dict/list operation.
"""

from extraction.nodes.persist import EPISTEMIC_PRIORITY, _classify_evidence_type, _cluster_by_value


def test_cluster_by_value_groups_identical_values_from_different_files():
    proposals = [
        {"source": "a", "value": "2026-09-30"},
        {"source": "b", "value": "2026-10-15"},
        {"source": "c", "value": "09/30/2026"},  # same date, different format - same cluster as "a"
    ]
    clusters = _cluster_by_value(proposals)
    assert len(clusters) == 2
    sizes = sorted(len(c) for c in clusters)
    assert sizes == [1, 2]
    merged = next(c for c in clusters if len(c) == 2)
    assert {p["source"] for p in merged} == {"a", "c"}


def test_cluster_by_value_fuzzes_ocr_typos_together():
    proposals = [
        {"source": "a", "value": "Northstar Logistics Holdings LLC"},
        {"source": "b", "value": "Northstar Logistics Hoidings LLC"},
    ]
    clusters = _cluster_by_value(proposals)
    assert len(clusters) == 1


def test_cluster_by_value_keeps_genuinely_different_values_separate():
    proposals = [{"source": "a", "value": "45,000 sq ft"}, {"source": "b", "value": "41,800 sq ft"}]
    clusters = _cluster_by_value(proposals)
    assert len(clusters) == 2


def _pick_best(proposals: list[dict]) -> dict:
    return min(proposals, key=lambda p: EPISTEMIC_PRIORITY.get(p.get("epistemic_status"), 2))


def test_explicit_wins_over_inferred_and_undetermined():
    proposals = [
        {"source": "a", "epistemic_status": "undetermined"},
        {"source": "b", "epistemic_status": "inferred"},
        {"source": "c", "epistemic_status": "explicit"},
    ]
    assert _pick_best(proposals)["source"] == "c"


def test_inferred_wins_over_undetermined_when_no_explicit_present():
    proposals = [
        {"source": "a", "epistemic_status": "undetermined"},
        {"source": "b", "epistemic_status": "inferred"},
    ]
    assert _pick_best(proposals)["source"] == "b"


def test_missing_epistemic_status_is_treated_as_lowest_priority():
    proposals = [
        {"source": "a"},  # no epistemic_status key at all
        {"source": "b", "epistemic_status": "explicit"},
    ]
    assert _pick_best(proposals)["source"] == "b"


def test_tie_keeps_the_first_occurrence():
    proposals = [
        {"source": "first", "epistemic_status": "explicit"},
        {"source": "second", "epistemic_status": "explicit"},
    ]
    assert _pick_best(proposals)["source"] == "first"


def test_logic_field_with_formula_edge_path_is_always_formula_trace():
    proposal = {"field_category": "logic", "epistemic_status": "inferred"}
    assert _classify_evidence_type(proposal, "formula_edge_path") == "formula_trace"


def test_logic_field_inferred_without_formula_is_formula_inferred():
    proposal = {"field_category": "logic", "epistemic_status": "inferred"}
    assert _classify_evidence_type(proposal, "document_block") == "formula_inferred"


def test_logic_field_undetermined_without_formula_is_formula_undetermined():
    proposal = {"field_category": "logic", "epistemic_status": "undetermined"}
    assert _classify_evidence_type(proposal, "document_block") == "formula_undetermined"


def test_logic_field_explicit_document_block_is_still_narrative_rule():
    proposal = {"field_category": "logic", "epistemic_status": "explicit"}
    assert _classify_evidence_type(proposal, "document_block") == "narrative_rule"


def test_data_field_is_never_classified():
    proposal = {"field_category": "valuation_info", "epistemic_status": "undetermined"}
    assert _classify_evidence_type(proposal, "document_block") is None
