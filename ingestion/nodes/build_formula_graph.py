"""Builds the per-workbook formula dependency graph and persists it as FormulaEdge rows.

Tokenizes raw_formula strings with regex (cell refs, ranges, cross-sheet refs) and
builds a networkx.DiGraph in memory to check for cycles; only the resulting edges
are persisted, so later traces read from Postgres rather than from openpyxl again.
"""

import re

import networkx as nx

from core.models import FormulaEdge, SpreadsheetCell

# Sheet2!A1 style cross-sheet ref (sheet name optionally quoted)
_CROSS_SHEET_RE = re.compile(r"(?:'([^']+)'|([A-Za-z0-9_]+))!(\$?[A-Z]{1,3}\$?\d+)")
# A1:B10 style range (checked before plain cell refs so ranges aren't double counted)
_RANGE_RE = re.compile(r"\$?[A-Z]{1,3}\$?\d+:\$?[A-Z]{1,3}\$?\d+")
# plain A1 style single-cell ref
_CELL_RE = re.compile(r"\$?([A-Z]{1,3})\$?(\d+)")


def build_formula_graph(db, file, cells: list[SpreadsheetCell]) -> list[FormulaEdge]:
    by_ref: dict[tuple[str, str], SpreadsheetCell] = {
        (c.sheet_name, c.cell_ref): c for c in cells
    }
    sheet_names = {c.sheet_name for c in cells}

    graph = nx.DiGraph()
    for c in cells:
        graph.add_node(c.id)

    # collected before persisting, so a detected cycle leaves no partial edges written
    pending_edges: list[tuple[SpreadsheetCell, SpreadsheetCell, str]] = []

    for cell in cells:
        if not cell.is_formula or not cell.raw_formula:
            continue

        for sheet_ref, col, row, edge_type in _extract_refs(cell.raw_formula, cell.sheet_name, sheet_names):
            target = by_ref.get((sheet_ref, f"{col}{row}"))
            if target is None or target.id == cell.id:
                continue  # dangling ref (outside parsed range) or self-ref - skip
            graph.add_edge(cell.id, target.id)
            pending_edges.append((cell, target, edge_type))

    if not nx.is_directed_acyclic_graph(graph):
        cycle = next(nx.simple_cycles(graph), [])
        file.parse_error = f"formula graph contains a cycle involving {len(cycle)} cell(s) - skipping graph persistence"
        return []

    edges: list[FormulaEdge] = []
    seen: set[tuple] = set()
    for source, target, edge_type in pending_edges:
        key = (source.id, target.id)
        if key in seen:
            continue  # UNIQUE(source_cell_id, target_cell_id) - don't double-insert
        seen.add(key)
        edge = FormulaEdge(
            file_id=file.id,
            tenant_id=file.tenant_id,
            source_cell_id=source.id,
            target_cell_id=target.id,
            edge_type=edge_type,
        )
        db.add(edge)
        edges.append(edge)

    db.flush()
    return edges


def _extract_refs(formula: str, home_sheet: str, sheet_names: set[str]):
    """Yields (sheet_name, col, row, edge_type) for every reference in a formula string."""
    body = formula[1:] if formula.startswith("=") else formula
    consumed = set()  # char spans already claimed by a cross-sheet/range match

    for m in _CROSS_SHEET_RE.finditer(body):
        sheet = m.group(1) or m.group(2)
        if sheet not in sheet_names:
            continue
        ref = m.group(3).replace("$", "")
        cell_match = _CELL_RE.match(ref)
        if cell_match:
            col, row = cell_match.group(1), cell_match.group(2)
            yield sheet, col, row, "cross_sheet_ref"
        consumed.add((m.start(), m.end()))

    for m in _RANGE_RE.finditer(body):
        if _overlaps(m.start(), m.end(), consumed):
            continue
        start_ref, end_ref = m.group(0).split(":")
        for col, row in _expand_range(start_ref, end_ref):
            yield home_sheet, col, row, "range_ref"
        consumed.add((m.start(), m.end()))

    for m in _CELL_RE.finditer(body):
        if _overlaps(m.start(), m.end(), consumed):
            continue
        yield home_sheet, m.group(1), m.group(2), "direct_ref"


def _overlaps(start: int, end: int, spans: set[tuple[int, int]]) -> bool:
    return any(start >= s and end <= e for s, e in spans)


def _expand_range(start_ref: str, end_ref: str, max_cells: int = 500):
    """Expands A1:B3 into individual (col, row) pairs, capped to avoid blowing up on huge ranges."""
    sm, em = _CELL_RE.match(start_ref.replace("$", "")), _CELL_RE.match(end_ref.replace("$", ""))
    if not sm or not em:
        return
    c1, r1 = _col_to_num(sm.group(1)), int(sm.group(2))
    c2, r2 = _col_to_num(em.group(1)), int(em.group(2))
    count = 0
    for r in range(min(r1, r2), max(r1, r2) + 1):
        for c in range(min(c1, c2), max(c1, c2) + 1):
            if count >= max_cells:
                return
            yield _num_to_col(c), r
            count += 1


def _col_to_num(col: str) -> int:
    n = 0
    for ch in col:
        n = n * 26 + (ord(ch) - ord("A") + 1)
    return n


def _num_to_col(n: int) -> str:
    out = ""
    while n > 0:
        n, rem = divmod(n - 1, 26)
        out = chr(rem + ord("A")) + out
    return out
