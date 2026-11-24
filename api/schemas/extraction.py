import uuid
from datetime import datetime

from pydantic import BaseModel


class ExtractRequest(BaseModel):
    query: str | None = None
    field_schema: dict | None = None
    # skips the already-extracted-fields shortcut; used for the post-upload pass
    force: bool = False


class MissingFieldOut(BaseModel):
    field_name: str
    field_category: str
    reason: str


class ExtractionJobOut(BaseModel):
    id: uuid.UUID
    batch_id: uuid.UUID
    query: str | None
    status: str
    error: str | None
    result_kind: str
    guidance: dict | None
    missing_fields: list[MissingFieldOut] | None
    created_at: datetime

    class Config:
        from_attributes = True


class CitationOut(BaseModel):
    id: uuid.UUID
    extraction_id: uuid.UUID
    file_id: uuid.UUID
    file_name: str | None
    location: str | None
    citation_type: str
    document_block_id: uuid.UUID | None
    spreadsheet_cell_id: uuid.UUID | None
    formula_path: list | None
    quote_or_formula: str | None
    verified: bool

    class Config:
        from_attributes = True


class ExtractionOut(BaseModel):
    id: uuid.UUID
    batch_id: uuid.UUID
    field_name: str
    field_category: str
    value: str | None
    epistemic_status: str
    evidence_type: str | None
    reasoning_note: str | None
    reconciliation_version: int
    created_at: datetime
    citations: list[CitationOut] = []

    class Config:
        from_attributes = True
