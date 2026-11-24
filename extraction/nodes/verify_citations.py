"""verify_citations node - deterministic, no LLM. Checks each proposed extraction's
source_ref actually exists and backs up what the LLM claims.

- document_block_id: row must exist in this file/batch; a given quote is
  fuzzy substring-matched against the block's stored text.
- spreadsheet_cell_id: row must exist in this file/batch.
- formula_edge_path: walks the cited cell's full dependency chain
  (extraction.formula_trace) and re-derives every formula cell in it via
  ingestion.formula_eval, checked against its cached_value within tolerance.
"""

import difflib
import re
import uuid

from sqlalchemy.orm import Session as DBSession

from core.models import DocumentBlock, SpreadsheetCell
from extraction.batch_files import resolve_source_file_ids
from extraction.formula_trace import verify_formula_chain

QUOTE_MATCH_THRESHOLD = 0.8


def verify_citations(db: DBSession, tenant_id: str, batch_id: str, proposals: list[dict]) -> list[dict]:
    """Mutates nothing - returns copies of proposals with a `_citation_verification`
    key added. A plain spreadsheet_cell citation that points at a formula cell is
    upgraded to formula_edge_path, so a value computed by a formula always carries
    its own traced, re-derived dependency chain - not only when the model happened
    to choose formula_edge_path itself."""
    # resolved once per call; reused-aware, since a block's file may differ from batch_id
    source_file_ids = set(resolve_source_file_ids(db, tenant_id, batch_id))

    verified_proposals = []
    for proposal in proposals:
        ref = dict(proposal.get("source_ref") or {})
        if ref.get("citation_type") in ("spreadsheet_cell", "formula_edge_path"):
            raw_formula = _raw_formula(db, tenant_id, ref)
            if raw_formula:
                ref["citation_type"] = "formula_edge_path"
                # the formula shown is the cell's own, never the model's retyping of it
                ref["quote_or_formula"] = raw_formula
            else:
                # a plain input cell cited as a formula path is still a valid cell citation
                ref["citation_type"] = "spreadsheet_cell"
        result = _verify_one(db, tenant_id, source_file_ids, ref)
        proposal = dict(proposal)
        proposal["source_ref"] = ref
        proposal["_citation_verification"] = result
        verified_proposals.append(proposal)
    return verified_proposals


def _raw_formula(db: DBSession, tenant_id: str, ref: dict) -> str | None:
    try:
        cell = (
            db.query(SpreadsheetCell)
            .filter(SpreadsheetCell.id == uuid.UUID(str(ref.get("spreadsheet_cell_id"))), SpreadsheetCell.tenant_id == tenant_id)
            .one_or_none()
        )
    except (ValueError, TypeError):
        return None
    return cell.raw_formula if cell and cell.is_formula else None


def _verify_one(db: DBSession, tenant_id: str, source_file_ids: set[str], ref: dict) -> dict:
    citation_type = ref.get("citation_type")

    if citation_type == "document_block":
        return _verify_document_block(db, tenant_id, source_file_ids, ref)
    if citation_type == "spreadsheet_cell":
        return _verify_spreadsheet_cell(db, tenant_id, source_file_ids, ref)
    if citation_type == "formula_edge_path":
        return _verify_formula_path(db, tenant_id, source_file_ids, ref)

    return {"verified": False, "reason": f"unknown citation_type: {citation_type}"}


def _verify_document_block(db: DBSession, tenant_id: str, source_file_ids: set[str], ref: dict) -> dict:
    block_id = ref.get("document_block_id")
    if not block_id:
        return {"verified": False, "reason": "missing document_block_id"}

    try:
        block = (
            db.query(DocumentBlock)
            .filter(DocumentBlock.id == uuid.UUID(str(block_id)), DocumentBlock.tenant_id == tenant_id)
            .one_or_none()
        )
    except (ValueError, TypeError):
        return {"verified": False, "reason": "malformed document_block_id"}

    if block is None or str(block.file_id) not in source_file_ids:
        return {"verified": False, "reason": "document_block not found in this batch"}

    quote = ref.get("quote_or_formula")
    if quote and block.text:
        matched, ratio = quote_matches(quote, block.text)
        if matched:
            return {"verified": True, "reason": "quote matched block text", "file_id": str(block.file_id)}
        return {"verified": False, "reason": f"quote did not match block text (ratio={ratio:.2f})"}

    return {"verified": True, "reason": "block exists, no quote to check", "file_id": str(block.file_id)}


_WHITESPACE_RE = re.compile(r"\s+")
_WINDOW_STEP = 4
_MAX_WINDOWS = 2000


def _normalize(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", text.lower()).strip()


def quote_matches(quote: str, block_text: str) -> tuple[bool, float]:
    """Whether a quote appears in a block's text, tolerant of line-break/whitespace
    differences and small OCR noise. A scanned page is stored as one long block,
    so the quote is compared against same-length windows of the block rather
    than the whole block (a whole-block ratio is dragged down by length alone)."""
    q, t = _normalize(quote), _normalize(block_text)
    if not q:
        return False, 0.0
    if q in t:
        return True, 1.0
    if len(t) <= len(q):
        ratio = difflib.SequenceMatcher(None, q, t).ratio()
        return ratio >= QUOTE_MATCH_THRESHOLD, ratio

    step = max(_WINDOW_STEP, (len(t) - len(q)) // _MAX_WINDOWS + 1)
    best = 0.0
    matcher = difflib.SequenceMatcher(None, autojunk=False)
    matcher.set_seq2(q)
    for start in range(0, len(t) - len(q) + 1, step):
        matcher.set_seq1(t[start : start + len(q)])
        if matcher.real_quick_ratio() < QUOTE_MATCH_THRESHOLD or matcher.quick_ratio() < QUOTE_MATCH_THRESHOLD:
            continue
        best = max(best, matcher.ratio())
        if best >= QUOTE_MATCH_THRESHOLD:
            return True, best
    return False, best


def _verify_spreadsheet_cell(db: DBSession, tenant_id: str, source_file_ids: set[str], ref: dict) -> dict:
    cell_id = ref.get("spreadsheet_cell_id")
    if not cell_id:
        return {"verified": False, "reason": "missing spreadsheet_cell_id"}

    try:
        cell = (
            db.query(SpreadsheetCell)
            .filter(SpreadsheetCell.id == uuid.UUID(str(cell_id)), SpreadsheetCell.tenant_id == tenant_id)
            .one_or_none()
        )
    except (ValueError, TypeError):
        return {"verified": False, "reason": "malformed spreadsheet_cell_id"}

    if cell is None or str(cell.file_id) not in source_file_ids:
        return {"verified": False, "reason": "spreadsheet_cell not found in this batch"}

    return {"verified": True, "reason": "cell exists", "file_id": str(cell.file_id)}


def _verify_formula_path(db: DBSession, tenant_id: str, source_file_ids: set[str], ref: dict) -> dict:
    # the dependency chain is always derived server-side from formula_edges
    root_cell_id = ref.get("spreadsheet_cell_id")
    if not root_cell_id:
        return {"verified": False, "reason": "missing spreadsheet_cell_id for formula_edge_path citation"}

    try:
        root_cell = (
            db.query(SpreadsheetCell)
            .filter(SpreadsheetCell.id == uuid.UUID(str(root_cell_id)), SpreadsheetCell.tenant_id == tenant_id)
            .one_or_none()
        )
    except (ValueError, TypeError):
        return {"verified": False, "reason": "malformed spreadsheet_cell_id"}

    if root_cell is not None and str(root_cell.file_id) not in source_file_ids:
        root_cell = None

    if root_cell is None:
        return {"verified": False, "reason": "spreadsheet_cell not found in this batch"}
    if not root_cell.is_formula or not root_cell.raw_formula:
        return {"verified": False, "reason": "cited cell is not a formula - nothing to trace"}

    try:
        return verify_formula_chain(db, tenant_id, root_cell)
    except Exception as exc:
        return {"verified": False, "reason": f"formula chain trace failed: {exc}"}
