"""One dependency edge in a workbook's formula graph: source cell references target cell.

Built once from NetworkX during ingestion, then re-queried with a recursive CTE at
trace time instead of re-parsing the workbook.
"""

import uuid

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.db import Base
from core.models.mixins import TenantScopedMixin, UUIDPrimaryKeyMixin


class FormulaEdge(UUIDPrimaryKeyMixin, TenantScopedMixin, Base):
    __tablename__ = "formula_edges"
    __table_args__ = (UniqueConstraint("source_cell_id", "target_cell_id"),)

    file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("files.id", ondelete="CASCADE"), nullable=False
    )
    source_cell_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("spreadsheet_cells.id", ondelete="CASCADE"), index=True, nullable=False
    )
    target_cell_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("spreadsheet_cells.id", ondelete="CASCADE"), index=True, nullable=False
    )

    # direct_ref: =B10   range_ref: part of =SUM(B2:B10)   cross_sheet_ref: =Sheet2!B3
    edge_type: Mapped[str] = mapped_column(String, nullable=False)
