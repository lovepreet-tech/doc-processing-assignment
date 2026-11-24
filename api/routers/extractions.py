import uuid

from fastapi import APIRouter, Depends, HTTPException
from sse_starlette.sse import EventSourceResponse
from sqlalchemy.orm import Session as DBSession

from api.deps import get_batch_scoped, get_scoped_db
from api.schemas.extraction import CitationOut, ExtractionJobOut, ExtractionOut, ExtractRequest
from core.db import session_scope, set_tenant_context
from core.models import Batch, Citation, Extraction, ExtractionJob
from core.security import Identity, get_current_identity
from extraction.tasks.run_extraction import run_extraction
from progress.events import stream_steps

router = APIRouter(tags=["extractions"])


@router.post("/batches/{batch_id}/extract", response_model=ExtractionJobOut)
def start_extraction(
    body: ExtractRequest,
    batch: Batch = Depends(get_batch_scoped),
    db: DBSession = Depends(get_scoped_db),
):
    job = ExtractionJob(
        tenant_id=batch.tenant_id,
        batch_id=batch.id,
        query=body.query,
        field_schema=body.field_schema,
        status="PENDING",
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    run_extraction.delay(str(job.id), str(batch.id), body.query, body.field_schema, body.force)

    return job


@router.get("/batches/{batch_id}/extraction-jobs", response_model=list[ExtractionJobOut])
def list_extraction_jobs(
    batch: Batch = Depends(get_batch_scoped),
    db: DBSession = Depends(get_scoped_db),
):
    return (
        db.query(ExtractionJob)
        .filter(ExtractionJob.batch_id == batch.id, ExtractionJob.tenant_id == batch.tenant_id)
        .order_by(ExtractionJob.created_at.asc())
        .all()
    )


@router.get("/extraction-jobs/{job_id}", response_model=ExtractionJobOut)
def get_extraction_job(
    job_id: uuid.UUID,
    identity: Identity = Depends(get_current_identity),
    db: DBSession = Depends(get_scoped_db),
):
    job = db.query(ExtractionJob).filter(ExtractionJob.id == job_id, ExtractionJob.tenant_id == identity.tenant_id).first()
    if job is None:
        raise HTTPException(status_code=404, detail="extraction job not found")
    return job


@router.get("/extraction-jobs/{job_id}/progress")
def get_extraction_job_progress(
    job_id: uuid.UUID,
    identity: Identity = Depends(get_current_identity),
):
    # uses a short-lived session rather than Depends(get_scoped_db), since that
    # session would stay checked out for the lifetime of the SSE connection
    with session_scope() as db:
        set_tenant_context(db, str(identity.tenant_id))
        job = db.query(ExtractionJob).filter(ExtractionJob.id == job_id, ExtractionJob.tenant_id == identity.tenant_id).first()
        if job is None:
            raise HTTPException(status_code=404, detail="extraction job not found")
    return EventSourceResponse(stream_steps("extraction_job", str(job_id)))


@router.get("/batches/{batch_id}/extractions", response_model=list[ExtractionOut])
def list_extractions(
    batch: Batch = Depends(get_batch_scoped),
    db: DBSession = Depends(get_scoped_db),
):
    # the batch's full current state across every query ever run against it;
    # see list_job_extractions below for a single job's results
    return (
        db.query(Extraction)
        .filter(Extraction.batch_id == batch.id, Extraction.superseded == False)  # noqa: E712
        .all()
    )


@router.get("/extraction-jobs/{job_id}/extractions", response_model=list[ExtractionOut])
def list_job_extractions(
    job_id: uuid.UUID,
    identity: Identity = Depends(get_current_identity),
    db: DBSession = Depends(get_scoped_db),
):
    # only the extractions this job's query asked about
    job = db.query(ExtractionJob).filter(ExtractionJob.id == job_id, ExtractionJob.tenant_id == identity.tenant_id).first()
    if job is None:
        raise HTTPException(status_code=404, detail="extraction job not found")
    ids = job.extraction_ids or []
    if not ids:
        return []
    return db.query(Extraction).filter(Extraction.id.in_(ids), Extraction.tenant_id == identity.tenant_id).all()


@router.get("/extractions/{extraction_id}/citations", response_model=list[CitationOut])
def list_citations(
    extraction_id: uuid.UUID,
    identity: Identity = Depends(get_current_identity),
    db: DBSession = Depends(get_scoped_db),
):
    extraction = (
        db.query(Extraction)
        .filter(Extraction.id == extraction_id, Extraction.tenant_id == identity.tenant_id)
        .first()
    )
    if extraction is None:
        raise HTTPException(status_code=404, detail="extraction not found")

    return db.query(Citation).filter(Citation.extraction_id == extraction_id).all()
