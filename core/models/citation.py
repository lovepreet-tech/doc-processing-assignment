"""The source reference backing one extraction - a page/quote, a cell, or a formula path.

`verified` is set only by the deterministic verification node, never by the LLM.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.db import Base
from core.models.mixins import TenantScopedMixin, UUIDPrimaryKeyMixin


class Citation(UUIDPrimaryKeyMixin, TenantScopedMixin, Base):
    __tablename__ = "citations"

    extraction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("extractions.id", ondelete="CASCADE"), nullable=False
    )
    file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("files.id", ondelete="CASCADE"), nullable=False
    )

    citation_type: Mapped[str] = mapped_column(String, nullable=False)  # document_block | spreadsheet_cell | formula_edge_path
    document_block_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document_blocks.id", ondelete="CASCADE"), nullable=True
    )
    spreadsheet_cell_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("spreadsheet_cells.id", ondelete="CASCADE"), nullable=True
    )
    # server-derived dependency chain for a formula_edge_path citation:
    # list of hop dicts, root cell first (see extraction.formula_trace)
    formula_path: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    quote_or_formula: Mapped[str | None] = mapped_column(Text, nullable=True)

    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    extraction = relationship("Extraction", back_populates="citations")
    file = relationship("File")
    document_block = relationship("DocumentBlock")
    spreadsheet_cell = relationship("SpreadsheetCell")

    @property
    def file_name(self) -> str | None:
        return self.file.original_filename if self.file else None

    @property
    def location(self) -> str | None:
        """Human-readable "where in the file": a page/section for a document_block
        citation, a sheet!cell for a spreadsheet_cell one, None for a formula_edge_path."""
        if self.document_block is not None:
            parts = []
            if self.document_block.page_number is not None:
                parts.append(f"p. {self.document_block.page_number}")
            if self.document_block.source_section_path:
                parts.append(self.document_block.source_section_path)
            return " – ".join(parts) or None
        if self.spreadsheet_cell is not None:
            return f"{self.spreadsheet_cell.sheet_name}!{self.spreadsheet_cell.cell_ref}"
        return None
