"""Shared FastAPI dependencies for tenant-scoped DB access and lookups."""

import uuid

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session as DBSession

from core.db import get_db, set_tenant_context
from core.models import Batch, Session as SessionModel
from core.security import Identity, get_current_identity


def get_scoped_db(
    identity: Identity = Depends(get_current_identity),
    db: DBSession = Depends(get_db),
) -> DBSession:
    """A DB session with the RLS tenant variable already set for this request."""
    set_tenant_context(db, str(identity.tenant_id))
    return db


def get_session_scoped(
    session_id: uuid.UUID,
    identity: Identity = Depends(get_current_identity),
    db: DBSession = Depends(get_scoped_db),
) -> SessionModel:
    session = (
        db.query(SessionModel)
        .filter(SessionModel.id == session_id, SessionModel.tenant_id == identity.tenant_id)
        .first()
    )
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    return session


def get_batch_scoped(
    batch_id: uuid.UUID,
    identity: Identity = Depends(get_current_identity),
    db: DBSession = Depends(get_scoped_db),
) -> Batch:
    batch = (
        db.query(Batch)
        .filter(Batch.id == batch_id, Batch.tenant_id == identity.tenant_id)
        .first()
    )
    if batch is None:
        raise HTTPException(status_code=404, detail="batch not found")
    return batch
