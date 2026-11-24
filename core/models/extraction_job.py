"""Tracks one async extraction run against a batch - what the FE polls for status."""

import uuid

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.db import Base
from core.models.mixins import TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin


class ExtractionJob(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "extraction_jobs"

    batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("batches.id", ondelete="CASCADE"), nullable=False
    )

    query: Mapped[str | None] = mapped_column(String, nullable=True)
    field_schema: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # PENDING -> RUNNING -> DONE, or FAILED
    status: Mapped[str] = mapped_column(String, default="PENDING", nullable=False)
    error: Mapped[str | None] = mapped_column(String, nullable=True)

    # EXTRACTION: result lives in the extractions table. GUIDANCE: query didn't
    # map to anything extractable, so `guidance` holds a batch overview plus
    # suggested follow-up queries instead.
    result_kind: Mapped[str] = mapped_column(String, default="EXTRACTION", nullable=False)
    guidance: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # fields this query asked about with no supporting evidence in any uploaded
    # file: list of {field_name, field_category, reason}
    missing_fields: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    # ids of the Extraction rows that answer this job's query, whether freshly
    # created or reused from an earlier run via cache_match
    extraction_ids: Mapped[list | None] = mapped_column(JSONB, nullable=True)
