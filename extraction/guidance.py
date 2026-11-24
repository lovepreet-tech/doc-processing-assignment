"""Builds a "here's what I can help with" payload for a batch, used when a query
doesn't resolve to any extractable field, or when a batch's files are reviewed
with no query at all.

Does not call the LLM; it's a plain survey of the batch's files and spreadsheet
column/row headers already in Postgres.
"""

from sqlalchemy.orm import Session as DBSession

from core.models import File, SpreadsheetCell

MAX_SUGGESTED_FIELDS = 8


def build_guidance(db: DBSession, tenant_id: str, batch_id: str) -> dict:
    files = (
        db.query(File)
        .filter(File.tenant_id == tenant_id, File.batch_id == batch_id)
        .order_by(File.created_at.asc())
        .all()
    )

    field_names = _distinct_field_names(db, tenant_id, batch_id)
    suggested_queries = field_names[:MAX_SUGGESTED_FIELDS]

    file_summaries = [{"filename": f.original_filename, "status": f.status} for f in files]

    if not files:
        message = "I don't have any files to work with yet - attach a PDF, scan, or spreadsheet to get started."
    elif not field_names:
        message = (
            f"I've reviewed {len(files)} file(s): {', '.join(f.original_filename for f in files)}. "
            "I didn't find any structured fields to extract yet - try asking about a specific "
            "value you expect to find in the text (e.g. a property address or appraised value)."
        )
    else:
        message = (
            f"I've reviewed {len(files)} file(s): {', '.join(f.original_filename for f in files)}. "
            f"Here's what I can pull values for - ask me about any of these, "
            "and I'll cite exactly where each value comes from:"
        )

    return {
        "message": message,
        "file_summaries": file_summaries,
        "available_fields": field_names,
        "suggested_queries": suggested_queries,
    }


def _distinct_field_names(db: DBSession, tenant_id: str, batch_id: str) -> list[str]:
    cells = (
        db.query(SpreadsheetCell)
        .join(SpreadsheetCell.file)
        .filter(SpreadsheetCell.tenant_id == tenant_id)
        .filter(SpreadsheetCell.file.has(batch_id=batch_id))
        .all()
    )

    seen: dict[str, None] = {}  # dict, not set - preserves first-seen order
    for cell in cells:
        header = cell.header_context or {}
        for value in header.values():
            name = str(value).strip()
            # skip purely numeric header values - not meaningful field names
            if name and not name.replace(".", "", 1).isdigit():
                seen.setdefault(name, None)

    return list(seen.keys())
