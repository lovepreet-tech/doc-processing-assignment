"""Celery entrypoint for ingesting one uploaded file.

Manages the file's status lifecycle and progress events; dispatches the actual
parsing to the nodes wired up in `_run_parse_pipeline` below.
"""

import uuid

from ingestion.celery_app import celery_app
from core.batch_status import recompute_batch_status
from core.db import session_scope
from core.models import File
from progress.events import publish_step


@celery_app.task(name="ingestion.tasks.ingest_file", bind=True, max_retries=2)
def ingest_file(self, file_id: str) -> None:
    with session_scope() as db:
        file = db.query(File).filter(File.id == uuid.UUID(file_id)).one_or_none()
        if file is None:
            return  # file was deleted before the task ran

        # idempotency guard: a retry landing after completion shouldn't redo work
        if file.status in ("PARSED", "REUSED"):
            return

        publish_step("file", file_id, step="queued", status="started")

        try:
            file.status = "PARSING"
            db.commit()

            _run_parse_pipeline(db, file)

            file.status = "PARSED"
            recompute_batch_status(db, file.batch_id)
            db.commit()
            publish_step("file", file_id, step="ready", status="done")

        except Exception as exc:
            file.status = "FAILED"
            file.parse_error = str(exc)
            recompute_batch_status(db, file.batch_id)
            db.commit()
            publish_step("file", file_id, step="ready", status="failed", detail=str(exc))
            raise


def _run_parse_pipeline(db, file: File) -> None:
    """Dispatches to the right parse node by file_type, then formula graph (xlsx
    only), then embedding, publishing a progress step around each node."""
    from ingestion.nodes.parse_pdf import parse_pdf
    from ingestion.nodes.parse_spreadsheet import parse_spreadsheet
    from ingestion.nodes.parse_csv import parse_csv
    from ingestion.nodes.parse_text import parse_text
    from ingestion.nodes.parse_docx import parse_docx
    from ingestion.nodes.build_formula_graph import build_formula_graph
    from ingestion.nodes.embed_chunks import embed_chunks
    from ingestion.nodes.persist import persist

    file_id = str(file.id)
    blocks = []
    cells = []

    if file.file_type in ("xlsx", "xls", "csv"):
        publish_step("file", file_id, step="parsing_cells", status="started")
        cells = parse_csv(db, file) if file.file_type == "csv" else parse_spreadsheet(db, file)
        publish_step("file", file_id, step="parsing_cells", status="done")

        publish_step("file", file_id, step="building_formula_graph", status="started")
        build_formula_graph(db, file, cells)
        # build_formula_graph sets file.parse_error on a cycle instead of raising
        status = "failed" if file.parse_error else "done"
        publish_step("file", file_id, step="building_formula_graph", status=status, detail=file.parse_error)

    elif file.file_type in ("pdf", "scan_image"):
        publish_step("file", file_id, step="parsing_blocks", status="started")
        blocks = parse_pdf(db, file)
        publish_step("file", file_id, step="parsing_blocks", status="done")

    elif file.file_type == "text":
        publish_step("file", file_id, step="parsing_blocks", status="started")
        blocks = parse_text(db, file)
        publish_step("file", file_id, step="parsing_blocks", status="done")

    elif file.file_type == "docx":
        publish_step("file", file_id, step="parsing_blocks", status="started")
        blocks = parse_docx(db, file)
        publish_step("file", file_id, step="parsing_blocks", status="done")

    else:
        raise ValueError(f"unsupported file_type for ingestion: {file.file_type}")

    publish_step("file", file_id, step="embedding_chunks", status="started")
    embed_chunks(file, blocks=blocks, cells=cells)
    publish_step("file", file_id, step="embedding_chunks", status="done")

    publish_step("file", file_id, step="persisting", status="started")
    persist(db)
    publish_step("file", file_id, step="persisting", status="done")
