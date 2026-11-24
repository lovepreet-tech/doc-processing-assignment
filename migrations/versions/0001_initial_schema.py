"""initial schema: sessions, batches, files, parsed artifacts, extractions, citations, conflicts

Revision ID: 0001
Revises:
Create Date: 2026-11-23
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto"')

    op.create_table(
        "sessions",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="ACTIVE"),
        sa.Column("retention_ttl_days", sa.Integer(), nullable=False, server_default="90"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_sessions_tenant_id", "sessions", ["tenant_id"])

    op.create_table(
        "batches",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", pg.UUID(as_uuid=True), sa.ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="PENDING"),
        sa.Column("status_detail", pg.JSONB(), nullable=False, server_default="{}"),
        sa.Column("reconciliation_version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_batches_tenant_id", "batches", ["tenant_id"])
    op.create_index("ix_batches_session_id", "batches", ["session_id"])

    op.create_table(
        "files",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("batch_id", pg.UUID(as_uuid=True), sa.ForeignKey("batches.id", ondelete="CASCADE"), nullable=False),
        sa.Column("original_filename", sa.String(), nullable=False),
        sa.Column("storage_uri", sa.String(), nullable=False),
        sa.Column("file_type", sa.String(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="PENDING"),
        sa.Column("reused_from_file_id", pg.UUID(as_uuid=True), sa.ForeignKey("files.id"), nullable=True),
        sa.Column("parse_error", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_files_tenant_id", "files", ["tenant_id"])
    op.create_index("ix_files_batch_id", "files", ["batch_id"])
    op.create_index("ix_files_tenant_sha256", "files", ["tenant_id", "sha256"])

    op.create_table(
        "document_blocks",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("file_id", pg.UUID(as_uuid=True), sa.ForeignKey("files.id", ondelete="CASCADE"), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("block_type", sa.String(), nullable=False),
        sa.Column("bbox", pg.JSONB(), nullable=True),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("table_data", pg.JSONB(), nullable=True),
        sa.Column("reading_order", sa.Integer(), nullable=True),
        sa.Column("ocr_confidence", sa.Float(), nullable=True),
        sa.Column("needs_vlm_review", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("source_section_path", sa.String(), nullable=True),
    )
    op.create_index("ix_document_blocks_tenant_id", "document_blocks", ["tenant_id"])
    op.create_index("ix_document_blocks_file_page", "document_blocks", ["file_id", "page_number"])

    op.create_table(
        "spreadsheet_cells",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("file_id", pg.UUID(as_uuid=True), sa.ForeignKey("files.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sheet_name", sa.String(), nullable=False),
        sa.Column("cell_ref", sa.String(), nullable=False),
        sa.Column("raw_formula", sa.String(), nullable=True),
        sa.Column("cached_value", sa.String(), nullable=True),
        sa.Column("value_type", sa.String(), nullable=True),
        sa.Column("is_formula", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("header_context", pg.JSONB(), nullable=True),
        sa.UniqueConstraint("file_id", "sheet_name", "cell_ref"),
    )
    op.create_index("ix_spreadsheet_cells_tenant_id", "spreadsheet_cells", ["tenant_id"])

    op.create_table(
        "formula_edges",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("file_id", pg.UUID(as_uuid=True), sa.ForeignKey("files.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_cell_id", pg.UUID(as_uuid=True), sa.ForeignKey("spreadsheet_cells.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_cell_id", pg.UUID(as_uuid=True), sa.ForeignKey("spreadsheet_cells.id", ondelete="CASCADE"), nullable=False),
        sa.Column("edge_type", sa.String(), nullable=False),
        sa.UniqueConstraint("source_cell_id", "target_cell_id"),
    )
    op.create_index("ix_formula_edges_tenant_id", "formula_edges", ["tenant_id"])
    op.create_index("ix_formula_edges_source_cell_id", "formula_edges", ["source_cell_id"])
    op.create_index("ix_formula_edges_target_cell_id", "formula_edges", ["target_cell_id"])

    op.create_table(
        "extractions",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("batch_id", pg.UUID(as_uuid=True), sa.ForeignKey("batches.id", ondelete="CASCADE"), nullable=False),
        sa.Column("field_name", sa.String(), nullable=False),
        sa.Column("field_category", sa.String(), nullable=False),
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column("value_normalized", pg.JSONB(), nullable=True),
        sa.Column("epistemic_status", sa.String(), nullable=False),
        sa.Column("evidence_type", sa.String(), nullable=True),
        sa.Column("reasoning_note", sa.Text(), nullable=True),
        sa.Column("reconciliation_version", sa.Integer(), nullable=False),
        sa.Column("superseded", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_extractions_tenant_id", "extractions", ["tenant_id"])
    op.create_index(
        "ix_extractions_batch_field_active",
        "extractions",
        ["batch_id", "field_name"],
        postgresql_where=sa.text("superseded = false"),
    )

    op.create_table(
        "citations",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("extraction_id", pg.UUID(as_uuid=True), sa.ForeignKey("extractions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("file_id", pg.UUID(as_uuid=True), sa.ForeignKey("files.id"), nullable=False),
        sa.Column("citation_type", sa.String(), nullable=False),
        sa.Column("document_block_id", pg.UUID(as_uuid=True), sa.ForeignKey("document_blocks.id"), nullable=True),
        sa.Column("spreadsheet_cell_id", pg.UUID(as_uuid=True), sa.ForeignKey("spreadsheet_cells.id"), nullable=True),
        sa.Column("formula_path", pg.JSONB(), nullable=True),
        sa.Column("quote_or_formula", sa.Text(), nullable=True),
        sa.Column("verified", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_citations_tenant_id", "citations", ["tenant_id"])
    op.create_index("ix_citations_extraction_id", "citations", ["extraction_id"])

    op.create_table(
        "conflicts",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("batch_id", pg.UUID(as_uuid=True), sa.ForeignKey("batches.id", ondelete="CASCADE"), nullable=False),
        sa.Column("field_name", sa.String(), nullable=False),
        sa.Column("conflicting_extraction_ids", pg.ARRAY(pg.UUID(as_uuid=True)), nullable=False),
        sa.Column("conflict_summary", sa.Text(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="OPEN"),
        sa.Column("resolved_value", pg.JSONB(), nullable=True),
        sa.Column("resolved_by", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_conflicts_tenant_id", "conflicts", ["tenant_id"])
    op.create_index("ix_conflicts_batch_id", "conflicts", ["batch_id"])

    # row-level security: every tenant-scoped table is only visible to the tenant
    # set via `SET app.tenant_id` (see core/db.py:set_tenant_context). This is a
    # defense-in-depth layer behind the API's own tenant checks, not a replacement.
    tenant_tables = [
        "sessions", "batches", "files", "document_blocks", "spreadsheet_cells",
        "formula_edges", "extractions", "citations", "conflicts",
    ]
    for table in tenant_tables:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY tenant_isolation_{table} ON {table}
            USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
            """
        )


def downgrade() -> None:
    for table in ["conflicts", "citations", "extractions", "formula_edges",
                  "spreadsheet_cells", "document_blocks", "files", "batches", "sessions"]:
        op.drop_table(table)
