"""Derives a batch's overall status from the status of its files."""

import uuid

from sqlalchemy.orm import Session as DBSession

from core.models import Batch, File

_IN_PROGRESS = {"PENDING", "PARSING"}


def recompute_batch_status(db: DBSession, batch_id: uuid.UUID) -> None:
    batch = db.query(Batch).filter(Batch.id == batch_id).one_or_none()
    if batch is None:
        return

    statuses = [s for (s,) in db.query(File.status).filter(File.batch_id == batch_id).all()]
    if not statuses:
        return

    if any(s in _IN_PROGRESS for s in statuses):
        batch.status = "INGESTING"
    elif all(s == "FAILED" for s in statuses):
        batch.status = "FAILED"
    elif any(s == "FAILED" for s in statuses):
        batch.status = "PARTIAL"
    else:
        batch.status = "READY"
