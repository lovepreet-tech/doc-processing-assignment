"""Walks a workbook's formula dependency graph (formula_edges) to answer "how was
this cell's value produced" - the spreadsheet half of logic extraction.

A recursive query gets every cell reachable from a root formula cell (its direct
and transitive inputs), then each formula cell along that chain is re-derived with
ingestion.formula_eval and checked against its own cached_value. The resulting
chain, not anything the LLM produced, is what gets persisted on the Citation.
"""

import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session as DBSession

from core.models import SpreadsheetCell

MAX_TRACE_DEPTH = 12

# reachable set only: each cell once, at its shallowest depth from the root
_CHAIN_SQL = text(
    """
    WITH RECURSIVE chain(cell_id, depth) AS (
        SELECT CAST(:root_id AS uuid), 0
        UNION ALL
        SELECT fe.target_cell_id, chain.depth + 1
        FROM formula_edges fe
        JOIN chain ON fe.source_cell_id = chain.cell_id
        WHERE fe.tenant_id = :tenant_id AND chain.depth < :max_depth
    )
    SELECT cell_id, MIN(depth) AS depth
    FROM chain
    GROUP BY cell_id
    """
)

# every edge inside the reachable set, so a cell feeding several formulas keeps
# all of those relationships (not just the one on its shallowest path)
_EDGES_SQL = text(
    """
    SELECT source_cell_id, target_cell_id
    FROM formula_edges
    WHERE tenant_id = :tenant_id
      AND source_cell_id = ANY(CAST(:ids AS uuid[]))
      AND target_cell_id = ANY(CAST(:ids AS uuid[]))
    """
)


def trace_formula_chain(
    db: DBSession, tenant_id: str, root_cell_id: uuid.UUID, max_depth: int = MAX_TRACE_DEPTH
) -> list[tuple[SpreadsheetCell, int, list[uuid.UUID]]]:
    """Returns every cell reachable from root_cell_id as (cell, depth, parent_ids),
    root first, ordered by real dependency depth. parent_ids are every formula cell
    inside the chain that references this cell (the root has none)."""
    rows = db.execute(
        _CHAIN_SQL, {"root_id": str(root_cell_id), "tenant_id": tenant_id, "max_depth": max_depth}
    ).all()
    if not rows:
        return []

    depth_by_id = {row.cell_id: row.depth for row in rows}
    ids = list(depth_by_id)
    edges = db.execute(_EDGES_SQL, {"tenant_id": tenant_id, "ids": [str(i) for i in ids]}).all()
    parents_by_id: dict[uuid.UUID, list[uuid.UUID]] = {}
    for edge in edges:
        parents_by_id.setdefault(edge.target_cell_id, []).append(edge.source_cell_id)

    cells_by_id = {
        c.id: c
        for c in db.query(SpreadsheetCell)
        .filter(SpreadsheetCell.tenant_id == tenant_id, SpreadsheetCell.id.in_(ids))
        .all()
    }
    present = [cid for cid in ids if cid in cells_by_id]
    present.sort(key=lambda cid: (depth_by_id[cid], cells_by_id[cid].sheet_name, _ref_sort_key(cells_by_id[cid].cell_ref)))
    return [(cells_by_id[cid], depth_by_id[cid], parents_by_id.get(cid, [])) for cid in present]


def _ref_sort_key(cell_ref: str) -> tuple[int, str]:
    letters = "".join(ch for ch in cell_ref if ch.isalpha())
    digits = "".join(ch for ch in cell_ref if ch.isdigit())
    return (int(digits) if digits else 0, letters)


def verify_formula_chain(db: DBSession, tenant_id: str, root_cell: SpreadsheetCell) -> dict:
    """Re-derives every formula cell in root_cell's dependency chain and checks it
    against that cell's own cached_value. Returns the chain (root first) as plain
    dicts for persisting/display, plus whether the whole chain checked out."""
    from ingestion.formula_eval import evaluate as evaluate_formula

    chain = trace_formula_chain(db, tenant_id, root_cell.id)
    if not chain:
        chain = [(root_cell, 0, [])]

    cells_by_id = {cell.id: cell for cell, _, _ in chain}
    cells_by_ref = {(c.sheet_name, c.cell_ref): c for c, _, _ in chain}

    def _make_lookup(home_sheet: str):
        # each formula's own cell refs resolve against ITS sheet, not the root
        # cell's - without this, a cell's intra-sheet refs were silently looked
        # up on whatever sheet the root happened to live on, which only worked
        # by accident for a single-sheet chain and returned None (treated as 0)
        # for every cell whose chain spans more than one sheet.
        def lookup(cell_ref: str):
            # "Sheet!A1" (cross-sheet) or plain "A1" (the formula's own sheet)
            sheet, _, ref = cell_ref.rpartition("!")
            cell = cells_by_ref.get((sheet or home_sheet, ref))
            return cell.cached_value if cell else None

        return lookup

    hops: list[dict] = []
    all_verified = True
    failure_reason: str | None = None

    for cell, depth, parent_ids in chain:
        parent_cells = sorted(
            (cells_by_id[pid] for pid in parent_ids if pid in cells_by_id),
            key=lambda p: (p.sheet_name, _ref_sort_key(p.cell_ref)),
        )
        hop = {
            "cell_id": str(cell.id),
            "parent_cell_ids": [str(p.id) for p in parent_cells],
            "parent_cell_refs": [f"{p.sheet_name}!{p.cell_ref}" for p in parent_cells],
            "sheet_name": cell.sheet_name,
            "cell_ref": cell.cell_ref,
            "raw_formula": cell.raw_formula,
            "cached_value": cell.cached_value,
            "is_formula": cell.is_formula,
            "depth": depth,
            "derivation_matched": None,  # None = not a formula, nothing to re-derive
        }

        if cell.is_formula and cell.raw_formula:
            try:
                value, is_safe_subset = evaluate_formula(cell.raw_formula, _make_lookup(cell.sheet_name))
            except Exception:
                value, is_safe_subset = None, False

            if not is_safe_subset:
                hop["derivation_matched"] = None  # outside the safe subset: unverifiable, not a failure
            elif cell.cached_value is None:
                # no cached result to compare against: unverifiable, not a failure
                hop["derivation_matched"] = None
            else:
                matched = _values_match(value, cell.cached_value)
                hop["derivation_matched"] = matched
                if not matched:
                    all_verified = False
                    failure_reason = failure_reason or f"{cell.cell_ref} re-derived {value!r}, expected {cell.cached_value!r}"

        hops.append(hop)

    if all_verified:
        reason = "formula chain re-derivation matched cached values" if any(
            h["derivation_matched"] for h in hops
        ) else "formula chain traced but no re-derivable formulas (cached values trusted as-is)"
    else:
        reason = f"formula chain re-derivation mismatch: {failure_reason}"

    return {
        "verified": all_verified,
        "reason": reason,
        "file_id": str(root_cell.file_id),
        "chain": hops,
    }


def _values_match(derived, cached) -> bool:
    if cached is None:
        return False
    try:
        return abs(float(derived) - float(cached)) <= 1e-6
    except (TypeError, ValueError):
        return str(derived).strip() == str(cached).strip()
