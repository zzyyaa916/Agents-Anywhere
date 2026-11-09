"""Account quota cache and account-wide collection gates."""

import sqlalchemy as sa
from alembic import op

revision = "v2_55"
down_revision = "v2_54"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "account_usage_sources",
        sa.Column("connector_id", sa.Text(), primary_key=True),
        sa.Column("runtime_id", sa.Text(), primary_key=True),
        sa.Column("account_key", sa.Text()),
        sa.Column("discovery_after", sa.Float(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(
            ["connector_id", "runtime_id"],
            ["device_runtimes.connector_id", "device_runtimes.runtime_id"],
            ondelete="CASCADE",
        ),
    )
    op.create_table(
        "account_usage_snapshots",
        sa.Column(
            "user_id",
            sa.Text(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("runtime", sa.Text(), primary_key=True),
        sa.Column("account_key", sa.Text(), primary_key=True),
        sa.Column("snapshot_json", sa.Text()),
        sa.Column("failures", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.Float(), nullable=False, server_default="0"),
        sa.Column("attempt_id", sa.Text()),
    )


def downgrade():
    op.drop_table("account_usage_snapshots")
    op.drop_table("account_usage_sources")
