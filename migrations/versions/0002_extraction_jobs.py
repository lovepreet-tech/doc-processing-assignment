"""extraction jobs: polling target for the stage-3 async extraction pipeline

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-23
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "extraction_jobs",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("batch_id", pg.UUID(as_uuid=True), sa.ForeignKey("batches.id", ondelete="CASCADE"), nullable=False),
        sa.Column("query", sa.String(), nullable=True),
        sa.Column("field_schema", pg.JSONB(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="PENDING"),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_extraction_jobs_tenant_id", "extraction_jobs", ["tenant_id"])
    op.create_index("ix_extraction_jobs_batch_id", "extraction_jobs", ["batch_id"])

    op.execute("ALTER TABLE extraction_jobs ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation_extraction_jobs ON extraction_jobs
        USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
        """
    )


def downgrade() -> None:
    op.drop_table("extraction_jobs")
