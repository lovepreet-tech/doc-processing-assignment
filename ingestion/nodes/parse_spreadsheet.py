"""Parses an xlsx workbook into SpreadsheetCell rows using openpyxl.

Dual-loads the workbook: once with data_only=False (to get raw formula strings)
and once with data_only=True (to get the cached values Excel last computed).

Each cell's header_context is inferred from the sheet's own layout by
infer_headers - labels are found wherever they actually sit, not assumed to be in
column A / row 1 (a common model layout is label in B, unit in C, value in D, with
a title block above, which the old column-A/row-1 assumption read as "no label at
all" and left every value cell unlabeled).
"""

import io

import openpyxl

from core.models import SpreadsheetCell

# a header-like row needs at least this many text cells, which keeps a 2-cell
# "label | value" row (e.g. "Basis adopted | Direct capitalization") from being
# mistaken for a table header over the cells below it
MIN_HEADER_ROW_CELLS = 3
# ...and at least this many of its columns must hold non-text data further down,
# so it's genuinely a header sitting over data columns
MIN_HEADER_DATA_COLUMNS = 2

Grid = dict[tuple[int, int], object]


def parse_spreadsheet(db, file) -> list[SpreadsheetCell]:
    from storage.object_store import read

    data = read(file.storage_uri)

    formula_wb = openpyxl.load_workbook(io.BytesIO(data), data_only=False)
    value_wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True)

    cells: list[SpreadsheetCell] = []

    for sheet_name in formula_wb.sheetnames:
        formula_ws = formula_wb[sheet_name]
        value_ws = value_wb[sheet_name] if sheet_name in value_wb.sheetnames else None

        entries = []
        grid: Grid = {}
        for row in formula_ws.iter_rows():
            for cell in row:
                if cell.value is None:
                    continue
                is_formula = isinstance(cell.value, str) and cell.value.startswith("=")
                cached = value_ws[cell.coordinate].value if value_ws is not None else None
                effective = cached if is_formula else cell.value
                entries.append((cell, is_formula, effective))
                # a formula with no cached result is still data, never a label
                grid[(cell.row, cell.column)] = 0 if (is_formula and effective is None) else effective

        headers = infer_headers(grid)

        for cell, is_formula, effective in entries:
            value_type, cached_str = _classify(effective)
            column_header, row_label = headers.get((cell.row, cell.column), (None, None))
            row_obj = SpreadsheetCell(
                file_id=file.id,
                tenant_id=file.tenant_id,
                sheet_name=sheet_name,
                cell_ref=cell.coordinate,
                raw_formula=cell.value if is_formula else None,
                cached_value=cached_str,
                value_type=value_type,
                is_formula=is_formula,
                header_context=header_context_dict(column_header, row_label),
            )
            db.add(row_obj)
            cells.append(row_obj)

    db.flush()  # need cell.id's before build_formula_graph wires edges between them
    return cells


def header_context_dict(column_header: str | None, row_label: str | None) -> dict | None:
    # "row" = header from a header row above, "col" = label from cells to the left
    if not (column_header or row_label):
        return None
    return {"row": column_header, "col": row_label}


def _is_text(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def infer_headers(grid: Grid, force_header_row: int | None = None) -> dict[tuple[int, int], tuple[str | None, str | None]]:
    """Maps every (row, col) in grid to (column_header, row_label).

    - column_header: the cell in the nearest header-like row above that has a
      cell in this column. A header-like row has >= MIN_HEADER_ROW_CELLS cells,
      all text, and >= MIN_HEADER_DATA_COLUMNS of its columns hold non-text data
      further down. force_header_row (e.g. a CSV's first row) is always treated
      as a header row when it is all text.
    - row_label: under a header row (tabular data), the leftmost text cell in the
      row to the left of this one (the record's key); otherwise (a label/value
      layout), every text cell to the left of this one, joined in order - so
      "Vacancy allowance | rate | 0.05" labels 0.05 as "Vacancy allowance rate".
    A header row's own cells get (None, None), and no cell is ever labeled with
    its own text, since only cells strictly left of / above it are used.
    """
    rows: dict[int, list[tuple[int, object]]] = {}
    for (r, c), value in grid.items():
        rows.setdefault(r, []).append((c, value))
    for r in rows:
        rows[r].sort(key=lambda item: item[0])

    header_rows = _header_rows(rows, force_header_row)

    result: dict[tuple[int, int], tuple[str | None, str | None]] = {}
    for r, row_cells in rows.items():
        if r in header_rows:
            for c, _ in row_cells:
                result[(r, c)] = (None, None)
            continue

        header_above = max((h for h in header_rows if h < r), default=None)
        header_cells = dict(rows[header_above]) if header_above is not None else {}

        row_map = dict(row_cells)
        for c, _ in row_cells:
            header_value = header_cells.get(c)
            column_header = str(header_value).strip() if _is_text(header_value) else None

            # walk left one column at a time. A single blank column is tolerated
            # (the common "label | <blank unit> | value" layout when a row has no
            # unit), but a second one in a row ends the walk - that wider gap means
            # whatever text sits further left belongs to an unrelated block (e.g. a
            # section title sharing a row with an unrelated reference code) rather
            # than labeling this cell, even though both happen to share a row
            left_text = []
            cc = c - 1
            gap_budget = 1
            while True:
                if cc in row_map:
                    v = row_map[cc]
                    if _is_text(v):
                        left_text.append(str(v).strip())
                elif gap_budget > 0:
                    gap_budget -= 1
                else:
                    break
                cc -= 1
            left_text.reverse()

            if not left_text:
                row_label = None
            elif column_header is not None:
                row_label = left_text[0]
            else:
                row_label = " ".join(left_text)

            result[(r, c)] = (column_header, row_label)
    return result


def _header_rows(rows: dict[int, list[tuple[int, object]]], force_header_row: int | None) -> set[int]:
    header_rows: set[int] = set()
    for r, row_cells in rows.items():
        if not all(_is_text(v) for _, v in row_cells):
            continue
        if r == force_header_row:
            header_rows.add(r)
            continue
        if len(row_cells) < MIN_HEADER_ROW_CELLS:
            continue
        columns = {c for c, _ in row_cells}
        data_columns = {
            c for rr, cells in rows.items() if rr > r for c, v in cells if c in columns and not _is_text(v)
        }
        if len(data_columns) >= MIN_HEADER_DATA_COLUMNS:
            header_rows.add(r)
    return header_rows


def _classify(value) -> tuple[str | None, str | None]:
    if value is None:
        return None, None
    if isinstance(value, bool):
        return "bool", str(value)
    if isinstance(value, (int, float)):
        return "number", str(value)
    if isinstance(value, str):
        if value.startswith("#"):  # #DIV/0!, #N/A, etc.
            return "error", value
        return "string", value
    # dates etc come back as datetime objects from openpyxl
    return "date", str(value)
