"""fix FK ondelete actions so deleting a session actually cascades all the way down

citations.file_id/document_block_id/spreadsheet_cell_id and
files.reused_from_file_id were left as the Postgres default (NO ACTION), which
blocks deleting a session's files - a citation outliving the file/block/cell it
points to should never happen anyway, so this just makes that structural
invariant match what the app already assumes everywhere else.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-23
"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("citations_file_id_fkey", "citations", type_="foreignkey")
    op.create_foreign_key(
        "citations_file_id_fkey", "citations", "files", ["file_id"], ["id"], ondelete="CASCADE"
    )

    op.drop_constraint("citations_document_block_id_fkey", "citations", type_="foreignkey")
    op.create_foreign_key(
        "citations_document_block_id_fkey",
        "citations",
        "document_blocks",
        ["document_block_id"],
        ["id"],
        ondelete="CASCADE",
    )

    op.drop_constraint("citations_spreadsheet_cell_id_fkey", "citations", type_="foreignkey")
    op.create_foreign_key(
        "citations_spreadsheet_cell_id_fkey",
        "citations",
        "spreadsheet_cells",
        ["spreadsheet_cell_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # a dedup pointer, not a hard dependency - if the file it was copied from gets
    # deleted, just null it out rather than blocking (or cascading) the delete
    op.drop_constraint("files_reused_from_file_id_fkey", "files", type_="foreignkey")
    op.create_foreign_key(
        "files_reused_from_file_id_fkey", "files", "files", ["reused_from_file_id"], ["id"], ondelete="SET NULL"
    )


def downgrade() -> None:
    op.drop_constraint("citations_file_id_fkey", "citations", type_="foreignkey")
    op.create_foreign_key("citations_file_id_fkey", "citations", "files", ["file_id"], ["id"])

    op.drop_constraint("citations_document_block_id_fkey", "citations", type_="foreignkey")
    op.create_foreign_key(
        "citations_document_block_id_fkey", "citations", "document_blocks", ["document_block_id"], ["id"]
    )

    op.drop_constraint("citations_spreadsheet_cell_id_fkey", "citations", type_="foreignkey")
    op.create_foreign_key(
        "citations_spreadsheet_cell_id_fkey", "citations", "spreadsheet_cells", ["spreadsheet_cell_id"], ["id"]
    )

    op.drop_constraint("files_reused_from_file_id_fkey", "files", type_="foreignkey")
    op.create_foreign_key("files_reused_from_file_id_fkey", "files", "files", ["reused_from_file_id"], ["id"])
