"""Bilingual event resources and live room controls."""

import sqlalchemy as sa
from alembic import op

revision = "20260928_0022"
down_revision = "20260927_0021"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("events") as batch:
        batch.add_column(
            sa.Column("chat_enabled", sa.Boolean(), nullable=False, server_default=sa.true())
        )
        batch.add_column(
            sa.Column("questions_enabled", sa.Boolean(), nullable=False, server_default=sa.true())
        )
    with op.batch_alter_table("event_translations") as batch:
        batch.add_column(sa.Column("content", sa.JSON(), nullable=False, server_default="{}"))


def downgrade():
    with op.batch_alter_table("event_translations") as batch:
        batch.drop_column("content")
    with op.batch_alter_table("events") as batch:
        batch.drop_column("questions_enabled")
        batch.drop_column("chat_enabled")
