"""Unit tests for propose_extractions.py's deterministic cleanup of what the
per-file LLM calls come back with: canonicalizing field names and demoting a
"not stated" DATA placeholder out of the proposal list so it never looks like a
competing value in a conflict group.
"""

from extraction.field_canon import UNDETERMINED_LOGIC_VALUE
from extraction.nodes.propose_extractions import (
    _dedupe_missing,
    _demote_pointer_logic_proposals,
    _demote_sentinel_data_proposals,
    _demote_shape_mismatched_data_proposals,
    _drop_shadowed_undetermined_logic,
    _drop_unresolved_citations,
)


def _proposal(field_name, category, value):
    return {"field_name": field_name, "field_category": category, "value": value}


def _proposal_with_ref(field_name, category, value, document_block_id=None, spreadsheet_cell_id=None, file_id=None):
    proposal = _proposal(field_name, category, value)
    proposal["source_ref"] = {
        "document_block_id": document_block_id,
        "spreadsheet_cell_id": spreadsheet_cell_id,
        "file_id": file_id,
    }
    return proposal


def test_unresolved_citation_is_dropped_and_reported_as_missing():
    # llm_client.py clears document_block_id/spreadsheet_cell_id/file_id back to
    # None when the LLM's ref_id didn't match anything it was actually shown -
    # that proposal must never reach persist.py, or it ends up as a real-looking
    # Extraction row with zero Citations ("0 sources" in the FE)
    proposals = [_proposal_with_ref("Assessed Value", "valuation_info", "$9,500,000")]
    resolved, unresolved = _drop_unresolved_citations(proposals)
    assert resolved == []
    assert len(unresolved) == 1
    assert unresolved[0]["field_name"] == "Assessed Value"


def test_resolved_citation_is_kept():
    proposals = [
        _proposal_with_ref(
            "Assessed Value", "valuation_info", "$9,500,000", document_block_id="11111111-1111-1111-1111-111111111111"
        )
    ]
    resolved, unresolved = _drop_unresolved_citations(proposals)
    assert resolved == proposals
    assert unresolved == []


def test_sentinel_data_proposal_is_demoted_to_missing():
    proposals = [_proposal("Assessed Value", "valuation_info", "not stated in the provided files")]
    kept, demoted = _demote_sentinel_data_proposals(proposals)
    assert kept == []
    assert len(demoted) == 1
    assert demoted[0]["field_name"] == "Assessed Value"
    assert demoted[0]["reason"] == "not stated in the provided files"


def test_real_data_value_is_kept():
    proposals = [_proposal("Property Area", "property_detail", "45,000 sq ft")]
    kept, demoted = _demote_sentinel_data_proposals(proposals)
    assert kept == proposals
    assert demoted == []


def test_logic_sentinel_value_is_never_demoted():
    # LOGIC fields are explicitly allowed to report "logic not stated" as their
    # actual value (see llm_client.py's undetermined-logic rule) - this is not a
    # DATA placeholder and must stay a real extraction
    proposals = [_proposal("NOI Calculation Logic", "logic", "logic not stated in the provided files")]
    kept, demoted = _demote_sentinel_data_proposals(proposals)
    assert kept == proposals
    assert demoted == []


def test_dedupe_missing_drops_a_field_that_was_actually_found():
    proposals = [_proposal("Property Area", "property_detail", "45000")]
    missing = [{"field_name": "Property Area", "field_category": "property_detail", "reason": "x"}]
    assert _dedupe_missing(proposals, missing) == []


def test_dedupe_missing_keeps_one_copy_when_several_files_report_the_same_gap():
    missing = [
        {"field_name": "Assessed Value", "field_category": "valuation_info", "reason": "a"},
        {"field_name": "assessed value", "field_category": "valuation_info", "reason": "b"},
    ]
    result = _dedupe_missing([], missing)
    assert len(result) == 1


def test_bare_number_in_a_date_field_is_demoted():
    # a monthly-rent cell or similar unrelated number mislabeled "Valuation Date"
    proposals = [_proposal("Valuation Date", "valuation_info", "60")]
    kept, demoted = _demote_shape_mismatched_data_proposals(proposals)
    assert kept == []
    assert len(demoted) == 1
    assert demoted[0]["field_name"] == "Valuation Date"


def test_real_date_in_a_date_field_is_kept():
    proposals = [_proposal("Valuation Date", "valuation_info", "September 30, 2026")]
    kept, demoted = _demote_shape_mismatched_data_proposals(proposals)
    assert kept == proposals
    assert demoted == []


def test_bare_percent_in_methodology_is_demoted():
    # a vacancy rate or similar unrelated percentage mislabeled "Methodology"
    proposals = [_proposal("Methodology", "valuation_info", "0.05")]
    kept, demoted = _demote_shape_mismatched_data_proposals(proposals)
    assert kept == []
    assert len(demoted) == 1


def test_real_methodology_name_is_kept():
    proposals = [_proposal("Methodology", "valuation_info", "Direct Capitalization")]
    kept, demoted = _demote_shape_mismatched_data_proposals(proposals)
    assert kept == proposals
    assert demoted == []


def test_pointer_only_sentence_is_demoted_out_of_logic():
    proposals = [_proposal("Valuation Logic", "logic", "See the attached calculation for details.")]
    kept, demoted = _demote_pointer_logic_proposals(proposals)
    assert kept == []
    assert len(demoted) == 1


def test_real_logic_statement_is_kept():
    proposals = [_proposal("Valuation Logic", "logic", "NOI divided by the cap rate, rounded to the nearest 100,000.")]
    kept, demoted = _demote_pointer_logic_proposals(proposals)
    assert kept == proposals
    assert demoted == []


def test_undetermined_logic_is_dropped_when_a_real_value_exists_for_the_same_field():
    proposals = [
        _proposal("Assessed Value Logic", "logic", UNDETERMINED_LOGIC_VALUE),
        _proposal("Assessed Value Logic", "logic", "NOI / Cap Rate, rounded to the nearest INR 100,000."),
    ]
    result = _drop_shadowed_undetermined_logic(proposals)
    assert len(result) == 1
    assert result[0]["value"] != UNDETERMINED_LOGIC_VALUE


def test_undetermined_logic_is_kept_when_no_other_field_answers_it():
    proposals = [_proposal("Growth Rate Logic", "logic", UNDETERMINED_LOGIC_VALUE)]
    assert _drop_shadowed_undetermined_logic(proposals) == proposals
