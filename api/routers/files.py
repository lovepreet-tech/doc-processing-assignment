import mimetypes
import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile
from sse_starlette.sse import EventSourceResponse
from sqlalchemy.orm import Session as DBSession

from api.deps import get_batch_scoped, get_scoped_db
from api.schemas.file import FileOut
from core.batch_status import recompute_batch_status
from core.db import session_scope, set_tenant_context
from core.models import Batch, File
from core.security import Identity, get_current_identity
from ingestion.tasks.ingest_file import ingest_file
from progress.events import stream_steps
from storage.object_store import read, save, sha256_of

router = APIRouter(prefix="/batches/{batch_id}/files", tags=["files"])


@router.post("", response_model=list[FileOut])
async def upload_files(
    uploads: list[UploadFile],
    batch: Batch = Depends(get_batch_scoped),
    db: DBSession = Depends(get_scoped_db),
):
    created: list[File] = []

    for upload in uploads:
        data = await upload.read()
        checksum = sha256_of(data)

        # dedup: reuse an already-parsed file with the same checksum for this tenant
        existing = (
            db.query(File)
            .filter(File.tenant_id == batch.tenant_id, File.sha256 == checksum, File.status == "PARSED")
            .first()
        )

        file_type = _infer_file_type(upload.filename)

        if existing is not None:
            file = File(
                tenant_id=batch.tenant_id,
                batch_id=batch.id,
                original_filename=upload.filename,
                storage_uri=existing.storage_uri,
                file_type=file_type,
                sha256=checksum,
                size_bytes=len(data),
                status="REUSED",
                reused_from_file_id=existing.id,
            )
            db.add(file)
            db.commit()
            db.refresh(file)
            created.append(file)
            continue

        storage_uri = save(data, upload.filename)
        file = File(
            tenant_id=batch.tenant_id,
            batch_id=batch.id,
            original_filename=upload.filename,
            storage_uri=storage_uri,
            file_type=file_type,
            sha256=checksum,
            size_bytes=len(data),
            status="PENDING",
        )
        db.add(file)
        db.commit()
        db.refresh(file)
        created.append(file)

        ingest_file.delay(str(file.id))

    recompute_batch_status(db, batch.id)
    db.commit()

    return created


@router.get("", response_model=list[FileOut])
def list_files(
    batch: Batch = Depends(get_batch_scoped),
    db: DBSession = Depends(get_scoped_db),
):
    return (
        db.query(File)
        .filter(File.batch_id == batch.id, File.tenant_id == batch.tenant_id)
        .order_by(File.created_at.asc())
        .all()
    )


@router.get("/{file_id}/status", response_model=FileOut)
def get_file_status(
    file_id: str,
    batch: Batch = Depends(get_batch_scoped),
    db: DBSession = Depends(get_scoped_db),
):
    file = db.query(File).filter(File.id == file_id, File.batch_id == batch.id).one()
    return file


@router.get("/{file_id}/content")
def get_file_content(
    file_id: str,
    batch: Batch = Depends(get_batch_scoped),
    db: DBSession = Depends(get_scoped_db),
):
    # opened as a plain browser navigation (window.open), so identity comes via
    # the query-param fallback rather than the X-Tenant-Id header
    file = db.query(File).filter(File.id == file_id, File.batch_id == batch.id).one_or_none()
    if file is None:
        raise HTTPException(status_code=404, detail="file not found")

    data = read(file.storage_uri)
    media_type, _ = mimetypes.guess_type(file.original_filename)
    return Response(
        content=data,
        media_type=media_type or "application/octet-stream",
        headers={"Content-Disposition": f'inline; filename="{file.original_filename}"'},
    )


@router.get("/{file_id}/progress")
def get_file_progress(
    batch_id: uuid.UUID,
    file_id: uuid.UUID,
    identity: Identity = Depends(get_current_identity),
):
    # uses a short-lived session rather than Depends(get_batch_scoped)/get_scoped_db,
    # since those would hold a pooled connection open for the life of the SSE stream
    with session_scope() as db:
        set_tenant_context(db, str(identity.tenant_id))
        batch = (
            db.query(Batch).filter(Batch.id == batch_id, Batch.tenant_id == identity.tenant_id).first()
        )
        if batch is None:
            raise HTTPException(status_code=404, detail="batch not found")
    return EventSourceResponse(stream_steps("file", str(file_id)))


def _infer_file_type(filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext in ("xlsx", "xlsm"):
        return "xlsx"
    if ext == "xls":
        return "xls"
    if ext == "csv":
        return "csv"
    if ext == "pdf":
        return "pdf"
    if ext in ("txt", "md", "markdown"):
        return "text"
    if ext == "docx":
        return "docx"
    # unrecognized extensions (jpg, png, tiff, ...) are treated as scanned pages
    return "scan_image"
