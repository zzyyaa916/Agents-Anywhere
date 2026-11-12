"""Retain device cleanup receipts after project/session rows are deleted."""
import sqlalchemy as sa
from alembic import op

revision = "v2_58"
down_revision = "v2_57"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("history_deletion_audit", sa.Column("device_cleanup_json", sa.Text(), nullable=True))


def downgrade():
    op.drop_column("history_deletion_audit", "device_cleanup_json")
