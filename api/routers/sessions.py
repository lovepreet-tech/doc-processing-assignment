import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session as DBSession

from api.deps import get_scoped_db, get_session_scoped
from api.schemas.session import SessionCreate, SessionOut
from core.models import Batch, File, Session as SessionModel
from core.security import Identity, get_current_identity
from storage.object_store import delete as delete_stored_file

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.post("", response_model=SessionOut)
def create_session(
    body: SessionCreate,
    identity: Identity = Depends(get_current_identity),
    db: DBSession = Depends(get_scoped_db),
):
    session = SessionModel(
        tenant_id=identity.tenant_id,
        user_id=identity.user_id,
        name=body.name,
        retention_ttl_days=body.retention_ttl_days,
        expires_at=datetime.now(timezone.utc) + timedelta(days=body.retention_ttl_days),
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


@router.get("", response_model=list[SessionOut])
def list_sessions(
    identity: Identity = Depends(get_current_identity),
    db: DBSession = Depends(get_scoped_db),
):
    return (
        db.query(SessionModel)
        .filter(SessionModel.tenant_id == identity.tenant_id, SessionModel.status == "ACTIVE")
        .order_by(SessionModel.created_at.desc())
        .all()
    )


@router.get("/{session_id}", response_model=SessionOut)
def get_session(session: SessionModel = Depends(get_session_scoped)):
    return session


@router.delete("/{session_id}", status_code=204)
def delete_session(
    session: SessionModel = Depends(get_session_scoped),
    db: DBSession = Depends(get_scoped_db),
):
    # hard delete; DB-level ON DELETE CASCADE handles every dependent row once the
    # session row goes, so this only needs to clean up on-disk file bytes
    batches = db.query(Batch).filter(Batch.session_id == session.id, Batch.tenant_id == session.tenant_id).all()
    batch_ids = [batch.id for batch in batches]

    files = db.query(File).filter(File.batch_id.in_(batch_ids), File.tenant_id == session.tenant_id).all() if batch_ids else []
    file_ids = {file.id for file in files}

    for file in files:
        # a REUSED file doesn't own its storage bytes
        if file.status == "REUSED":
            continue
        # dedup is tenant-wide, so another session's file may still reference these bytes
        still_referenced = (
            db.query(File)
            .filter(File.reused_from_file_id == file.id, File.id.notin_(file_ids))
            .first()
        )
        if still_referenced is None:
            delete_stored_file(file.storage_uri)

    db.delete(session)
    db.commit()
