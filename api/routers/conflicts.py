import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as DBSession

from api.deps import get_batch_scoped, get_scoped_db
from api.schemas.conflict import ConflictingValueOut, ConflictOut, ConflictResolveRequest
from api.schemas.extraction import CitationOut
from core.models import Batch, Conflict, Extraction, ExtractionJob
from core.security import Identity, get_current_identity
from extraction.nodes.detect_conflicts import normalize_field_name

router = APIRouter(tags=["conflicts"])


def _enrich(db: DBSession, conflict: Conflict) -> ConflictOut:
    # resolves conflicting_extraction_ids into the actual disagreeing values and
    # their source files
    extractions = (
        db.query(Extraction).filter(Extraction.id.in_(conflict.conflicting_extraction_ids)).all()
    )
    by_id = {row.id: row for row in extractions}
    conflicting_values = []
    for extraction_id in conflict.conflicting_extraction_ids:
        row = by_id.get(extraction_id)
        if row is None:
            continue
        conflicting_values.append(
            ConflictingValueOut(
                extraction_id=row.id,
                value=row.value,
                epistemic_status=row.epistemic_status,
                citations=[CitationOut.model_validate(c) for c in row.citations],
            )
        )
    out = ConflictOut.model_validate(conflict)
    out.conflicting_values = conflicting_values
    return out


@router.get("/batches/{batch_id}/conflicts", response_model=list[ConflictOut])
def list_conflicts(
    batch: Batch = Depends(get_batch_scoped),
    db: DBSession = Depends(get_scoped_db),
):
    conflicts = db.query(Conflict).filter(Conflict.batch_id == batch.id).all()
    return [_enrich(db, conflict) for conflict in conflicts]


@router.get("/extraction-jobs/{job_id}/conflicts", response_model=list[ConflictOut])
def list_job_conflicts(
    job_id: uuid.UUID,
    identity: Identity = Depends(get_current_identity),
    db: DBSession = Depends(get_scoped_db),
):
    # only the conflicts on fields this job's query touched
    job = db.query(ExtractionJob).filter(ExtractionJob.id == job_id, ExtractionJob.tenant_id == identity.tenant_id).first()
    if job is None:
        raise HTTPException(status_code=404, detail="extraction job not found")
    ids = job.extraction_ids or []
    if not ids:
        return []

    field_names = {
        normalize_field_name(row.field_name)
        for row in db.query(Extraction).filter(Extraction.id.in_(ids), Extraction.tenant_id == identity.tenant_id).all()
    }
    conflicts = db.query(Conflict).filter(Conflict.batch_id == job.batch_id, Conflict.tenant_id == identity.tenant_id).all()
    scoped = [c for c in conflicts if normalize_field_name(c.field_name) in field_names]
    return [_enrich(db, c) for c in scoped]


@router.post("/conflicts/{conflict_id}/resolve", response_model=ConflictOut)
def resolve_conflict(
    conflict_id: uuid.UUID,
    body: ConflictResolveRequest = ConflictResolveRequest(),
    identity: Identity = Depends(get_current_identity),
    db: DBSession = Depends(get_scoped_db),
):
    conflict = (
        db.query(Conflict)
        .filter(Conflict.id == conflict_id, Conflict.tenant_id == identity.tenant_id)
        .first()
    )
    if conflict is None:
        raise HTTPException(status_code=404, detail="conflict not found")

    conflict.resolved_value = body.resolved_value
    conflict.resolved_by = identity.user_id
    conflict.status = "RESOLVED"
    db.commit()
    db.refresh(conflict)
    return _enrich(db, conflict)
