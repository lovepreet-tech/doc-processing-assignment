"""One cell from a parsed workbook - either a raw value or a formula + its cached result."""

import uuid

from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.db import Base
from core.models.mixins import TenantScopedMixin, UUIDPrimaryKeyMixin


class SpreadsheetCell(UUIDPrimaryKeyMixin, TenantScopedMixin, Base):
    __tablename__ = "spreadsheet_cells"
    __table_args__ = (UniqueConstraint("file_id", "sheet_name", "cell_ref"),)

    file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("files.id", ondelete="CASCADE"), nullable=False
    )

    sheet_name: Mapped[str] = mapped_column(String, nullable=False)
    cell_ref: Mapped[str] = mapped_column(String, nullable=False)  # e.g. "B12"

    raw_formula: Mapped[str | None] = mapped_column(String, nullable=True)  # "=B10*0.08"
    cached_value: Mapped[str | None] = mapped_column(String, nullable=True)  # stringified value
    value_type: Mapped[str | None] = mapped_column(String, nullable=True)  # number/string/date/bool/error
    is_formula: Mapped[bool] = mapped_column(Boolean, default=False)

    # best-guess row/column header labels for this cell, e.g. {"row": "Cap Rate", "col": "FY2024"}
    header_context: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    file = relationship("File", back_populates="cells")
