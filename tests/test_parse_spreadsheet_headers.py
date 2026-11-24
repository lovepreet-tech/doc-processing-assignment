"""Unit tests for ingestion/nodes/parse_spreadsheet.py's infer_headers - the rule
that decides each cell's header_context, which is what retrieve._search_cells
later fuzzy-matches a query against and what the LLM sees as a cell's label.

Regression coverage for two real bugs:
- a two-column label/value sheet (A1="Client Name", B1=<the name>) used to treat
  row 1 as a shared header row, so B1 self-referenced its own value as a header;
- labels were only ever looked for in column A / row 1, so a model laid out as
  label in B, unit in C, value in D (with a title block above) left every value
  cell unlabeled, and the LLM had to guess what each bare number meant.
"""

from ingestion.nodes.parse_spreadsheet import infer_headers


def test_two_col_label_value_sheet_labels_value_with_its_own_row_label():
    grid = {
        (1, 1): "Client Name",
        (1, 2): "Northstar Logistics Holdings LLC",
        (2, 1): "Property Address",
        (2, 2): "1 Main St",
    }
    headers = infer_headers(grid)
    assert headers[(1, 2)] == (None, "Client Name")
    assert headers[(2, 2)] == (None, "Property Address")


def test_label_cells_never_get_their_own_text_or_row_1_as_a_header():
    grid = {
        (1, 1): "Client Name",
        (1, 2): "Northstar Logistics Holdings LLC",
        (2, 1): "Property Address",
        (2, 2): "1 Main St",
    }
    headers = infer_headers(grid)
    assert headers[(1, 1)] == (None, None)
    assert headers[(2, 1)] == (None, None)


def test_label_unit_value_layout_with_title_block_labels_value_from_cells_to_its_left():
    grid = {
        (2, 2): "Operating Assumptions",
        (2, 5): "VAL-2617",
        (8, 2): "Vacancy allowance",
        (8, 3): "rate",
        (8, 4): 0.05,
        (11, 2): "Occupancy threshold",
        (11, 3): "rate",
        (11, 4): 0.95,
    }
    headers = infer_headers(grid)
    assert headers[(8, 4)] == (None, "Vacancy allowance rate")
    assert headers[(11, 4)] == (None, "Occupancy threshold rate")
    # the title block's "Operating Assumptions" is 2 columns away from VAL-2617
    # (col 2 vs col 5, a gap of columns 3 and 4) - too wide a gap to be its label,
    # unlike the single-blank-unit-column gap in the label/unit/value tests above
    assert headers[(2, 5)] == (None, None)


def test_two_cell_label_value_row_is_not_mistaken_for_a_header_over_cells_below():
    grid = {
        (4, 2): "Basis adopted",
        (4, 4): "Direct capitalization",
        (6, 2): "Adopted market value",
        (6, 3): "INR",
        (6, 4): 120000000,
    }
    headers = infer_headers(grid)
    assert headers[(4, 4)] == (None, "Basis adopted")
    assert headers[(6, 4)] == (None, "Adopted market value INR")


def test_wide_table_gets_column_header_and_record_key_label():
    grid = {
        (1, 1): "Line Item",
        (1, 2): "FY2024",
        (1, 3): "FY2025",
        (2, 1): "Net Operating Income",
        (2, 2): 100,
        (2, 3): 120,
    }
    headers = infer_headers(grid)
    assert headers[(2, 2)] == ("FY2024", "Net Operating Income")
    assert headers[(2, 3)] == ("FY2025", "Net Operating Income")


def test_header_row_cells_get_no_header_context():
    grid = {
        (1, 1): "Line Item",
        (1, 2): "FY2024",
        (1, 3): "FY2025",
        (2, 1): "Net Operating Income",
        (2, 2): 100,
        (2, 3): 120,
    }
    headers = infer_headers(grid)
    assert headers[(1, 2)] == (None, None)


def test_forced_header_row_applies_even_with_few_numeric_columns():
    # a CSV's first row is its header even when most columns are text
    grid = {
        (1, 1): "ref",
        (1, 2): "subject",
        (2, 1): "VAL-2648",
        (2, 2): "3 Orchard Quay",
    }
    headers = infer_headers(grid, force_header_row=1)
    assert headers[(2, 2)] == ("subject", "VAL-2648")
    assert headers[(2, 1)] == ("ref", None)
