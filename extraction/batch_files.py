"""Resolves a batch's files to the file id that actually owns their parsed data.

A REUSED file has no DocumentBlock/SpreadsheetCell rows of its own; its content
lives under the original file referenced by reused_from_file_id, which may belong
to a different batch. Retrieval and citation verification use this to look up
parsed data by the owning file id rather than the batch's own File rows.
"""

from sqlalchemy.orm import Session as DBSession

from core.models import File


def resolve_source_file_ids(db: DBSession, tenant_id: str, batch_id: str) -> list[str]:
    files = db.query(File).filter(File.tenant_id == tenant_id, File.batch_id == batch_id).all()
    return [str(f.reused_from_file_id or f.id) for f in files]
