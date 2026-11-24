"""Unit tests for extraction/field_canon.py - disambiguating a LOGIC extraction's
field_name from the DATA field it explains, decided dynamically from what a given
run's own proposals contain rather than a hardcoded synonym dictionary (a static
list of "known variant -> canonical name" used to live here and was removed after
repeatedly causing false conflicts between two genuinely different concepts that
happened to share a name, e.g. a site area and a net rentable area).
"""

from extraction.field_canon import disambiguate_logic_field_names


def test_logic_field_colliding_with_a_data_field_in_this_run_gets_disambiguated():
    # the LLM naming a LOGIC extraction "Methodology" (same as the DATA field it's
    # explaining) must not survive as-is, or detect_conflicts would compare a
    # label against its own description as if they were competing values
    proposals = [
        {"field_name": "Methodology", "field_category": "valuation_info"},
        {"field_name": "Methodology", "field_category": "logic"},
    ]
    disambiguate_logic_field_names(proposals)
    assert proposals[0]["field_name"] == "Methodology"
    assert proposals[1]["field_name"] == "Methodology Logic"


def test_logic_field_is_case_and_separator_insensitive_when_matching_the_data_field():
    proposals = [
        {"field_name": "assessed value", "field_category": "property_detail"},
        {"field_name": "Assessed-Value", "field_category": "logic"},
    ]
    disambiguate_logic_field_names(proposals)
    assert proposals[1]["field_name"] == "Assessed-Value Logic"


def test_logic_field_with_no_colliding_data_field_in_this_run_is_left_unchanged():
    # nothing in this run's own proposals is named "Cap Rate Assumption", so there
    # is nothing to disambiguate from - nothing here is a hardcoded "known field"
    proposals = [{"field_name": "Cap Rate Assumption", "field_category": "logic"}]
    disambiguate_logic_field_names(proposals)
    assert proposals[0]["field_name"] == "Cap Rate Assumption"


def test_data_field_is_never_renamed():
    proposals = [{"field_name": "Methodology", "field_category": "valuation_info"}]
    disambiguate_logic_field_names(proposals)
    assert proposals[0]["field_name"] == "Methodology"


def test_two_different_data_fields_that_merely_share_a_noun_stay_distinct():
    # "Net Rentable Area" and "Property Area" are two different measurements, not
    # two phrasings of one fact - this module no longer merges them (that was the
    # removed synonym dictionary's job, and the source of repeated false
    # conflicts); each DATA field_name here is left exactly as the LLM produced it
    proposals = [
        {"field_name": "Net Rentable Area", "field_category": "property_detail"},
        {"field_name": "Property Area", "field_category": "property_detail"},
    ]
    disambiguate_logic_field_names(proposals)
    assert proposals[0]["field_name"] == "Net Rentable Area"
    assert proposals[1]["field_name"] == "Property Area"
