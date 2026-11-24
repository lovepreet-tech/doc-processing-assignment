from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session as DBSession

from api.deps import get_batch_scoped, get_scoped_db, get_session_scoped
from api.schemas.batch import BatchOut
from core.models import Batch
from core.models import Session as SessionModel

router = APIRouter(tags=["batches"])


@router.post("/sessions/{session_id}/batches", response_model=BatchOut)
def create_batch(
    session: SessionModel = Depends(get_session_scoped),
    db: DBSession = Depends(get_scoped_db),
):
    batch = Batch(tenant_id=session.tenant_id, session_id=session.id, status="PENDING")
    db.add(batch)
    db.commit()
    db.refresh(batch)
    return batch


@router.get("/batches/{batch_id}", response_model=BatchOut)
def get_batch(batch: Batch = Depends(get_batch_scoped)):
    return batch


@router.get("/sessions/{session_id}/batches", response_model=list[BatchOut])
def list_batches(
    session: SessionModel = Depends(get_session_scoped),
    db: DBSession = Depends(get_scoped_db),
):
    return (
        db.query(Batch)
        .filter(Batch.session_id == session.id, Batch.tenant_id == session.tenant_id)
        .order_by(Batch.created_at.asc())
        .all()
    )
