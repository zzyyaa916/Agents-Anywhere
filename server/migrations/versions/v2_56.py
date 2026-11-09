"""Durable session quota wait and original resume binding."""

import sqlalchemy as sa
from alembic import op

revision = "v2_56"
down_revision = "v2_55"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("sessions", sa.Column("quota_json", sa.Text()))


def downgrade():
    op.execute("UPDATE sessions SET status='idle' WHERE status='limited'")
    op.drop_column("sessions", "quota_json")
