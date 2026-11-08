"""Permanent history deletion suppression and audit metadata.

Revision ID: v2_54
Revises: v2_53
"""

import sqlalchemy as sa
from alembic import op

revision = "v2_54"
down_revision = "v2_53"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "history_deletions",
        sa.Column("session_id", sa.Text(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Text(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_key", sa.Text(), index=True),
        sa.Column("deletion_id", sa.Text(), nullable=False, index=True),
        sa.Column("deleted_at", sa.Text(), nullable=False),
    )
    op.create_table(
        "history_deletion_audit",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Text(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("object_type", sa.Text(), nullable=False),
        sa.Column("object_id", sa.Text(), nullable=False),
        sa.Column("session_count", sa.Integer(), nullable=False),
        sa.Column("cleanup_pending", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("deleted_at", sa.Text(), nullable=False),
    )


def downgrade() -> None:
    # History cannot be restored; removal also permits native sources to reimport.
    op.drop_table("history_deletion_audit")
    op.drop_table("history_deletions")
