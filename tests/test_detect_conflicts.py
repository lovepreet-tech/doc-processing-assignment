"""Unit tests for the deterministic conflict-matching rules in
extraction/nodes/detect_conflicts.py - no DB needed, these are pure functions.

This is the "flag conflicting information" half of the spec's success criteria:
two values should agree despite cosmetic formatting differences (currency symbols,
date formats, case), and genuinely different values should not be waved through.
"""

from extraction.field_canon import UNDETERMINED_LOGIC_VALUE
from extraction.nodes.detect_conflicts import (
    _all_agree,
    _drop_proposals_shadowed_by_existing,
    _effective_values_for_conflict,
    _values_equal,
    normalize_field_name,
)


def test_normalize_field_name_collapses_separators():
    assert normalize_field_name("Property Address") == "property_address"
    assert normalize_field_name("property-address") == "property_address"
    assert normalize_field_name("  property_address  ") == "property_address"


def test_values_equal_identical_strings():
    assert _values_equal("Austin, TX", "Austin, TX")


def test_values_equal_numeric_with_currency_and_commas():
    assert _values_equal("$1,250,000", "1250000")


def test_values_equal_numeric_within_tolerance():
    assert _values_equal("1250000", "1250050")  # within 1% relative tolerance


def test_values_equal_numeric_outside_tolerance_is_conflict():
    assert not _values_equal("1250000", "1500000")


def test_values_equal_strips_unit_suffix_before_comparing():
    # "45000" (bare spreadsheet number) and "45,000 sq ft" (PDF phrasing) are the
    # same value - the unit must not make them look like a conflict
    assert _values_equal("45000", "45,000 sq ft")
    assert _values_equal("45,000 sq ft", "45000.0")


def test_values_equal_different_numbers_with_units_still_conflict():
    # real disagreement (not just formatting) must still be caught even with units
    assert not _values_equal("45,000 sq ft", "41,800 sq ft")


def test_values_equal_dates_different_formats():
    assert _values_equal("2026-09-30", "09/30/2026")
    assert _values_equal("September 30, 2026", "2026-09-30")


def test_values_equal_dates_that_differ_is_conflict():
    assert not _values_equal("2026-09-30", "2026-10-01")


def test_values_equal_case_insensitive_text():
    assert _values_equal("Direct Capitalization Approach", "direct capitalization approach")


def test_values_equal_minor_ocr_typo_in_long_text():
    assert _values_equal("Northstar Logistics Hoidings LLC", "Northstar Logistics Holdings LLC")


def test_values_equal_different_short_values_not_fuzzed_together():
    # below the length floor, even a 1-char difference must stay a real conflict -
    # short strings have too little room for a ratio-based match to be meaningful
    assert not _values_equal("NOI", "ROI")


def test_values_equal_genuinely_different_text_is_not_fuzzed_into_agreement():
    assert not _values_equal("Direct Capitalization Approach", "Sales Comparison Approach")


def test_values_equal_none_is_never_equal_to_a_value():
    assert not _values_equal(None, "some value")
    assert not _values_equal("some value", None)


def test_all_agree_true_when_every_value_matches():
    assert _all_agree(["$1,250,000", "1250000", "1,250,000.00"])


def test_all_agree_false_when_one_value_disagrees():
    assert not _all_agree(["$1,250,000", "1250000", "1,500,000"])


def test_all_agree_single_value_trivially_agrees():
    assert _all_agree(["only one value"])


def test_values_equal_indian_crore_notation_matches_full_number():
    assert _values_equal("INR 12 crore", "120000000")
    assert _values_equal("Rs. 12 Crore", "120000000")
    assert _values_equal("₹1.2 crore", "12000000")


def test_values_equal_indian_lakh_notation_matches_full_number():
    assert _values_equal("50 lakh", "5000000")
    assert _values_equal("INR 50 Lakhs", "5,000,000")


def test_values_equal_crore_notation_still_catches_real_conflict():
    assert not _values_equal("INR 12 crore", "100000000")


def test_effective_values_drops_undetermined_placeholder_when_a_real_value_exists():
    # one file found no evidence (undetermined) while another found a real
    # answer - the placeholder must not get compared against the real value
    values = [UNDETERMINED_LOGIC_VALUE, "NOI / Cap Rate, rounded to nearest 100,000"]
    assert _effective_values_for_conflict(values) == ["NOI / Cap Rate, rounded to nearest 100,000"]


def test_effective_values_keeps_placeholders_when_nothing_real_was_found():
    values = [UNDETERMINED_LOGIC_VALUE, UNDETERMINED_LOGIC_VALUE]
    assert _effective_values_for_conflict(values) == values


def test_drop_proposals_shadowed_by_existing_removes_undetermined_when_real_value_on_record():
    proposals = [{"value": UNDETERMINED_LOGIC_VALUE}, {"value": "Direct Capitalization"}]
    existing_values = ["Direct Capitalization"]
    kept = _drop_proposals_shadowed_by_existing(proposals, existing_values)
    assert kept == [{"value": "Direct Capitalization"}]


def test_drop_proposals_shadowed_by_existing_keeps_undetermined_when_no_real_value_on_record():
    proposals = [{"value": UNDETERMINED_LOGIC_VALUE}]
    existing_values: list[str | None] = []
    assert _drop_proposals_shadowed_by_existing(proposals, existing_values) == proposals


def test_drop_proposals_shadowed_by_existing_keeps_undetermined_when_existing_is_also_undetermined():
    proposals = [{"value": UNDETERMINED_LOGIC_VALUE}]
    existing_values = [UNDETERMINED_LOGIC_VALUE]
    assert _drop_proposals_shadowed_by_existing(proposals, existing_values) == proposals


def test_values_equal_unit_abbreviation_with_periods_matches_plain_unit():
    # "sq. ft." and "sq ft" are the same unit written with and without full
    # stops - punctuation alone must never make this look like a conflict
    assert _values_equal("31,400 sq. ft.", "31,400 sq ft")
    assert _values_equal("31,400 sq. ft.", "31400")
