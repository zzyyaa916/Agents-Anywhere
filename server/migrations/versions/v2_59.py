"""Server-received Claude windows and durable global manual-probe control."""
import sqlalchemy as sa
from alembic import op

revision = "v2_59"
down_revision = "v2_58"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("account_usage_snapshots", sa.Column("claude_windows_json", sa.Text(), nullable=True))
    op.create_table("claude_usage_probe", sa.Column("key", sa.Text(), primary_key=True), sa.Column("state_json", sa.Text(), nullable=False))


def downgrade():
    op.drop_table("claude_usage_probe")
    op.drop_column("account_usage_snapshots", "claude_windows_json")
