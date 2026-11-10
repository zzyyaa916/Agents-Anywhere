"""Durable independent candidate groups; native sessions keep their existing lifecycle."""

import sqlalchemy as sa
from alembic import op

revision = "v2_57"
down_revision = "v2_56"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "task_groups",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Text(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            sa.Text(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("request_json", sa.Text(), nullable=False),
        sa.Column("state_json", sa.Text(), nullable=False),
    )
    op.create_index(
        "idx_task_groups_project_created", "task_groups", ["project_id", "created_at"]
    )


def downgrade():
    op.drop_table("task_groups")
