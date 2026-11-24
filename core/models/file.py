"""One uploaded file (pdf/scan/xlsx) within a batch."""

import uuid

from sqlalchemy import BigInteger, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.db import Base
from core.models.mixins import TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin


class File(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "files"

    batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("batches.id", ondelete="CASCADE"), nullable=False
    )

    original_filename: Mapped[str] = mapped_column(String, nullable=False)
    storage_uri: Mapped[str] = mapped_column(String, nullable=False)
    file_type: Mapped[str] = mapped_column(String, nullable=False)  # pdf | xlsx | xls | csv | text | docx | scan_image
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # PENDING -> PARSING -> PARSED, or FAILED. REUSED means dedup kicked in.
    status: Mapped[str] = mapped_column(String, default="PENDING", nullable=False)

    # set when this upload is a byte-identical re-upload of a previously parsed
    # file; an audit pointer only, nulled out (not cascaded) if that file is deleted
    reused_from_file_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("files.id", ondelete="SET NULL"), nullable=True
    )
    parse_error: Mapped[str | None] = mapped_column(String, nullable=True)

    batch = relationship("Batch", back_populates="files")
    blocks = relationship("DocumentBlock", back_populates="file", cascade="all, delete-orphan")
    cells = relationship("SpreadsheetCell", back_populates="file", cascade="all, delete-orphan")
