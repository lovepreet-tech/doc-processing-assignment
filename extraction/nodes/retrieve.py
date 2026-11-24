"""retrieve node - pulls candidate context from DocumentBlock rows via pgvector
similarity search, and from SpreadsheetCell rows whose header_context
fuzzy-matches the query.

Returns a flat list of dicts the LLM node can stuff into its prompt, each tagged
with enough source info for verify_citations to re-check later.
"""

import difflib
import re

from sqlalchemy.orm import Session as DBSession

from core.config import get_settings
from core.models import DocumentBlock, FormulaEdge, SpreadsheetCell
from extraction.batch_files import resolve_source_file_ids

settings = get_settings()

TOP_K = 8
FUZZY_THRESHOLD = 0.4  # loose on purpose: this is recall, verify_citations does the real check
SMALL_WORKBOOK_CELL_LIMIT = 60  # a file with this many labeled value cells or fewer is sent whole
_WORD_RE = re.compile(r"[a-z0-9]+")

# No hardcoded per-field synonym expansion here on purpose. A static "query term
# X also means Y" list used to widen the query's own word set before scoring, but
# it repeatedly pulled in cells that measure a genuinely different thing (e.g. a
# net rentable/lettable area cell under a "property area" query, which measures
# the site/parcel instead) and let them get compared downstream as if they were
# competing values of one field. Recall here comes from _match_score's per-word
# fuzzy matching (catches wording/spelling variation) and from always_include
# pulling in a cell's own formula-graph neighbors - neither needs to guess which
# concepts are "the same".


def retrieve(db: DBSession, tenant_id: str, batch_id: str, query: str) -> list[dict]:
    source_file_ids = resolve_source_file_ids(db, tenant_id, batch_id)
    results: list[dict] = []
    results.extend(_search_vectors(db, tenant_id, source_file_ids, query))
    results.extend(_search_cells(db, tenant_id, source_file_ids, query))
    return results


def _search_vectors(db: DBSession, tenant_id: str, source_file_ids: list[str], query: str) -> list[dict]:
    if not source_file_ids:
        return []
    query_vector = _embed(query)
    if query_vector is None:
        return []

    hits: list[dict] = []
    # one nearest-neighbor search per file, each capped at TOP_K, so one file's
    # chunks can't crowd out every other file's in a multi-file batch
    for file_id in source_file_ids:
        rows = (
            db.query(DocumentBlock, DocumentBlock.embedding.cosine_distance(query_vector).label("distance"))
            .filter(
                DocumentBlock.tenant_id == tenant_id,
                DocumentBlock.file_id == file_id,
                DocumentBlock.embedding.isnot(None),
            )
            .order_by("distance")
            .limit(TOP_K)
            .all()
        )
        for block, distance in rows:
            hits.append(
                {
                    "source": "pgvector",
                    "text": block.text or "",
                    "document_block_id": str(block.id),
                    "spreadsheet_cell_id": None,
                    "file_id": str(block.file_id),
                    "section": block.source_section_path,
                    "page_number": block.page_number,
                    # cosine_distance is 1 - cosine_similarity; inverted for "higher score = better match"
                    "score": 1.0 - float(distance),
                }
            )
    return hits


def _embed(text: str) -> list[float] | None:
    try:
        from langchain_openai import OpenAIEmbeddings
    except Exception:
        return None
    if not settings.openai_api_key:
        return None
    try:
        embedder = OpenAIEmbeddings(
            model=settings.openai_embedding_model,
            api_key=settings.openai_api_key,
            timeout=settings.openai_request_timeout_seconds,
        )
        return embedder.embed_query(text)
    except Exception:
        return None


def _search_cells(db: DBSession, tenant_id: str, source_file_ids: list[str], query: str) -> list[dict]:
    if not source_file_ids:
        return []
    cells = (
        db.query(SpreadsheetCell)
        .filter(SpreadsheetCell.tenant_id == tenant_id)
        .filter(SpreadsheetCell.file_id.in_(source_file_ids))
        .all()
    )

    # cells that feed a formula are part of the traceable logic graph even if
    # their header text doesn't match the query's own vocabulary
    edge_cell_ids = _formula_graph_cell_ids(db, tenant_id, source_file_ids)
    occupied = _occupied_columns_by_row(cells)

    candidates_by_file: dict[str, list[tuple[SpreadsheetCell, str, bool]]] = {}
    for cell in cells:
        if _is_label_cell(cell, occupied):
            continue  # the label itself is already in its value cell's header text
        label = _cell_label(cell)
        always_include = cell.is_formula or str(cell.id) in edge_cell_ids
        if not label and not always_include:
            continue
        candidates_by_file.setdefault(str(cell.file_id), []).append((cell, label, always_include))

    query_lower = query.lower()
    query_words = set(_WORD_RE.findall(query_lower))

    hits: list[dict] = []
    for file_candidates in candidates_by_file.values():
        # a small workbook's every labeled value fits in the prompt, and recall
        # matters more than keyword overlap (e.g. "Basis adopted: Direct
        # capitalization" never shares a word with a "methodology" query)
        small_workbook = sum(1 for _, label, _ in file_candidates if label) <= SMALL_WORKBOOK_CELL_LIMIT

        graph_hits: list[dict] = []
        keyword_hits: list[dict] = []
        for cell, label, always_include in file_candidates:
            score = _match_score(query_lower, query_words, label.lower()) if label else 0.0
            if always_include:
                # never trimmed by the per-file cap; ranked among themselves by relevance
                graph_hits.append(_cell_hit(cell, label, 1.0 + score))
            elif small_workbook or score >= FUZZY_THRESHOLD:
                keyword_hits.append(_cell_hit(cell, label, score))

        hits.extend(graph_hits)
        hits.extend(keyword_hits if small_workbook else _cap_per_file(keyword_hits, TOP_K))

    return hits


def _cell_hit(cell: SpreadsheetCell, label: str, score: float) -> dict:
    location = f"{cell.sheet_name}!{cell.cell_ref}"
    text = f"{location} | {label}: {cell.cached_value}" if label else f"{location}: {cell.cached_value}"
    return {
        "source": "spreadsheet_cell",
        "spreadsheet_cell_id": str(cell.id),
        "file_id": str(cell.file_id),
        "text": text,
        "sheet_name": cell.sheet_name,
        "cell_ref": cell.cell_ref,
        "raw_formula": cell.raw_formula,
        "cached_value": cell.cached_value,
        "score": score,
    }


def _cell_label(cell: SpreadsheetCell) -> str:
    # row label (cells to the left) first, then the column header above it
    header = cell.header_context or {}
    parts = [header.get("col"), header.get("row")]
    parts += [v for k, v in header.items() if k not in ("col", "row")]
    return " ".join(str(p) for p in parts if p)


_CELL_REF_RE = re.compile(r"^([A-Z]+)(\d+)$")


def _split_ref(cell_ref: str) -> tuple[int, int] | None:
    match = _CELL_REF_RE.match(cell_ref or "")
    if not match:
        return None
    col = 0
    for ch in match.group(1):
        col = col * 26 + (ord(ch) - ord("A") + 1)
    return int(match.group(2)), col


def _occupied_columns_by_row(cells: list[SpreadsheetCell]) -> dict[tuple[str, str, int], list[int]]:
    occupied: dict[tuple[str, str, int], list[int]] = {}
    for cell in cells:
        pos = _split_ref(cell.cell_ref)
        if pos:
            occupied.setdefault((str(cell.file_id), cell.sheet_name, pos[0]), []).append(pos[1])
    return occupied


def _is_label_cell(cell: SpreadsheetCell, occupied: dict[tuple[str, str, int], list[int]]) -> bool:
    """A text cell outside any table header's column that has something to its
    right in the same row is a label (e.g. "Vacancy allowance" | "rate" | 0.05),
    not a value. Text under a column header is tabular data, never a label."""
    if cell.is_formula or cell.value_type != "string":
        return False
    if (cell.header_context or {}).get("row"):
        return False
    pos = _split_ref(cell.cell_ref)
    if not pos:
        return False
    return any(col > pos[1] for col in occupied.get((str(cell.file_id), cell.sheet_name, pos[0]), []))


def _formula_graph_cell_ids(db: DBSession, tenant_id: str, source_file_ids: list[str]) -> set[str]:
    if not source_file_ids:
        return set()
    edges = (
        db.query(FormulaEdge.source_cell_id, FormulaEdge.target_cell_id)
        .filter(FormulaEdge.tenant_id == tenant_id, FormulaEdge.file_id.in_(source_file_ids))
        .all()
    )
    ids: set[str] = set()
    for source_id, target_id in edges:
        ids.add(str(source_id))
        ids.add(str(target_id))
    return ids


def _cap_per_file(hits: list[dict], top_k: int) -> list[dict]:
    """Keeps only the top_k highest-scoring hits per file_id, not top_k across
    the whole batch."""
    by_file: dict[str, list[dict]] = {}
    for hit in hits:
        by_file.setdefault(hit["file_id"], []).append(hit)

    capped: list[dict] = []
    for file_hits in by_file.values():
        file_hits.sort(key=lambda h: h["score"], reverse=True)
        capped.extend(file_hits[:top_k])
    return capped


def _match_score(query_lower: str, query_words: set[str], header_text_lower: str) -> float:
    """Score is the fraction of the header's own words that show up in the query,
    with a per-word fuzzy match (difflib ratio) for small spelling variations."""
    if header_text_lower in query_lower:
        return 1.0

    header_words = _WORD_RE.findall(header_text_lower)
    if not header_words:
        return 0.0

    matched_words = 0
    for word in header_words:
        if word in query_words:
            matched_words += 1
            continue
        if any(difflib.SequenceMatcher(None, word, qw).ratio() >= 0.85 for qw in query_words):
            matched_words += 1

    return matched_words / len(header_words)
