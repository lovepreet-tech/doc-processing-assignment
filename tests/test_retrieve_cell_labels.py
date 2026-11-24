"""Unit tests for retrieve.py's spreadsheet-cell helpers: what text a cell hit
shows the LLM, and which text cells count as labels (skipped as hits of their
own, since their text already appears in the value cell's label).
"""

from types import SimpleNamespace

from extraction.nodes.retrieve import _cell_hit, _cell_label, _is_label_cell, _occupied_columns_by_row


def _cell(ref, value, value_type="number", header=None, is_formula=False, sheet="Operating Inputs"):
    return SimpleNamespace(
        id=f"id-{sheet}-{ref}",
        file_id="file-1",
        sheet_name=sheet,
        cell_ref=ref,
        cached_value=value,
        value_type=value_type,
        header_context=header,
        is_formula=is_formula,
        raw_formula=None,
    )


def test_hit_text_carries_sheet_ref_label_and_value():
    cell = _cell("D8", "0.05", header={"row": None, "col": "Vacancy allowance rate"})
    hit = _cell_hit(cell, _cell_label(cell), 1.0)
    assert hit["text"] == "Operating Inputs!D8 | Vacancy allowance rate: 0.05"


def test_label_puts_row_label_before_column_header():
    cell = _cell("B2", "100", header={"row": "FY2024", "col": "Net Operating Income"})
    assert _cell_label(cell) == "Net Operating Income FY2024"


def test_text_cell_with_a_value_to_its_right_is_a_label():
    label = _cell("B8", "Vacancy allowance", value_type="string")
    unit = _cell("C8", "rate", value_type="string", header={"row": None, "col": "Vacancy allowance"})
    value = _cell("D8", "0.05", header={"row": None, "col": "Vacancy allowance rate"})
    occupied = _occupied_columns_by_row([label, unit, value])
    assert _is_label_cell(label, occupied)
    assert _is_label_cell(unit, occupied)
    assert not _is_label_cell(value, occupied)


def test_trailing_text_value_is_not_a_label():
    label = _cell("B4", "Basis adopted", value_type="string", sheet="Desk View")
    value = _cell("D4", "Direct capitalization", value_type="string", header={"row": None, "col": "Basis adopted"}, sheet="Desk View")
    occupied = _occupied_columns_by_row([label, value])
    assert not _is_label_cell(value, occupied)


def test_text_under_a_column_header_is_table_data_not_a_label():
    key = _cell("A2", "VAL-2648", value_type="string", header={"row": "ref", "col": None}, sheet="Sheet1")
    more = _cell("B2", "provisional", value_type="string", header={"row": "record_state", "col": "VAL-2648"}, sheet="Sheet1")
    occupied = _occupied_columns_by_row([key, more])
    assert not _is_label_cell(key, occupied)
