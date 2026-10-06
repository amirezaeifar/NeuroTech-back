"""Track account activation and latest activity without changing user content."""

import sqlalchemy as sa
from alembic import op

revision = "20260927_0018"
down_revision = "20260926_0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("activated_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("last_active_at", sa.DateTime(timezone=True)))
    op.execute("UPDATE users SET activated_at = (SELECT MIN(created_at) FROM auth_sessions WHERE auth_sessions.user_id = users.id), last_active_at = (SELECT MAX(created_at) FROM auth_sessions WHERE auth_sessions.user_id = users.id)")


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_column("last_active_at")
        batch.drop_column("activated_at")
