"""Unit test for extraction/formula_trace.py's numeric re-derivation check - the
rule that a formula-backed value is only ever trusted after the system re-derives
it itself and compares it to the cell's cached value, never on the LLM's say-so.
"""

from extraction.formula_trace import _values_match


def test_matching_numbers_within_float_tolerance():
    assert _values_match(1250000.0000001, "1250000")


def test_mismatched_numbers_fail():
    assert not _values_match(1250000, "1300000")


def test_cached_value_none_never_matches():
    assert not _values_match(1250000, None)


def test_non_numeric_falls_back_to_string_equality():
    assert _values_match("TRUE", "TRUE")
    assert not _values_match("TRUE", "FALSE")


def test_ref_sort_key_orders_rows_numerically():
    from extraction.formula_trace import _ref_sort_key

    refs = ["D10", "D9", "D11", "B2"]
    assert sorted(refs, key=_ref_sort_key) == ["B2", "D9", "D10", "D11"]
