"""Parses a CSV file into SpreadsheetCell rows, reusing parse_spreadsheet's header
inference and value classification so a CSV's cells are retrievable the same way
an xlsx's cells are (header_context fuzzy match in retrieve.py's _search_cells).

A CSV has no formulas, so every cell is a plain value - is_formula is always
False and build_formula_graph (run on these cells same as for xlsx) will simply
find no edges. Its first row is treated as the header row when it's all text.
"""

import csv
import io

from core.models import SpreadsheetCell
from ingestion.nodes.parse_spreadsheet import _classify, header_context_dict, infer_headers

SHEET_NAME = "Sheet1"


def parse_csv(db, file) -> list[SpreadsheetCell]:
    from storage.object_store import read

    data = read(file.storage_uri)
    text = data.decode("utf-8-sig", errors="replace")
    rows = list(csv.reader(io.StringIO(text)))

    grid = {}
    for row_idx, row in enumerate(rows, start=1):
        for col_idx, raw_value in enumerate(row, start=1):
            if raw_value:
                grid[(row_idx, col_idx)] = _coerce(raw_value)

    headers = infer_headers(grid, force_header_row=1)

    cells: list[SpreadsheetCell] = []
    for (row_idx, col_idx), value in sorted(grid.items()):
        value_type, cached_str = _classify(value)
        column_header, row_label = headers.get((row_idx, col_idx), (None, None))
        cell = SpreadsheetCell(
            file_id=file.id,
            tenant_id=file.tenant_id,
            sheet_name=SHEET_NAME,
            cell_ref=f"{_num_to_col(col_idx)}{row_idx}",
            raw_formula=None,
            cached_value=cached_str,
            value_type=value_type,
            is_formula=False,
            header_context=header_context_dict(column_header, row_label),
        )
        db.add(cell)
        cells.append(cell)

    db.flush()  # need cell.id's before build_formula_graph runs (no-op: no formulas)
    return cells


def _coerce(raw_value: str):
    """CSV cells are all strings on read; recover int/float so _classify tags
    them "number" like an xlsx cell, instead of every value coming back "string"."""
    try:
        return int(raw_value)
    except ValueError:
        pass
    try:
        return float(raw_value)
    except ValueError:
        pass
    return raw_value


def _num_to_col(n: int) -> str:
    out = ""
    while n > 0:
        n, rem = divmod(n - 1, 26)
        out = chr(rem + ord("A")) + out
    return out
