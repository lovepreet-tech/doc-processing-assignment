"""Celery entrypoint for an extraction query against a batch.

Builds and runs the stage-3 LangGraph StateGraph (see extraction/graph.py),
updating the ExtractionJob row's status as it goes. Each node publishes its own
progress events, so this task itself only needs to handle the start/end/failure
bookkeeping on the job row.
"""

import uuid

from extraction.celery_app import celery_app
from extraction.graph import run
from core.db import session_scope
from core.models import ExtractionJob


@celery_app.task(name="extraction.tasks.run_extraction", bind=True, max_retries=1)
def run_extraction(
    self, job_id: str, batch_id: str, query: str | None, field_schema: dict | None, force: bool = False
) -> None:
    with session_scope() as db:
        job = db.query(ExtractionJob).filter(ExtractionJob.id == uuid.UUID(job_id)).one_or_none()
        if job is None:
            return  # job row was deleted before the task ran

        job.status = "RUNNING"
        db.commit()
        tenant_id = str(job.tenant_id)

    try:
        result = run(job_id=job_id, tenant_id=tenant_id, batch_id=batch_id, query=query or "", force=force)

        with session_scope() as db:
            job = db.query(ExtractionJob).filter(ExtractionJob.id == uuid.UUID(job_id)).one()
            job.status = "DONE"
            job.result_kind = result["result_kind"]
            job.guidance = result["guidance"]
            job.missing_fields = result["missing_fields"]
            job.extraction_ids = result["created_extraction_ids"]
            db.commit()

    except Exception as exc:
        # graph.run() already published the terminal failed step before re-raising
        with session_scope() as db:
            job = db.query(ExtractionJob).filter(ExtractionJob.id == uuid.UUID(job_id)).one()
            job.status = "FAILED"
            job.error = str(exc)
            db.commit()
        raise
