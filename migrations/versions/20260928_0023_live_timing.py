"""Persist actual live and agenda step start times."""

import sqlalchemy as sa
from alembic import op

revision = "20260928_0023"
down_revision = "20260928_0022"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("events") as batch:
        batch.add_column(sa.Column("live_started_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("step_started_at", sa.DateTime(timezone=True)))
        batch.add_column(
            sa.Column("step_durations", sa.JSON(), nullable=False, server_default="[]")
        )


def downgrade():
    with op.batch_alter_table("events") as batch:
        batch.drop_column("step_durations")
        batch.drop_column("step_started_at")
        batch.drop_column("live_started_at")
