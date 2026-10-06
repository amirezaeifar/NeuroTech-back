"""Store each user's optional private profile image reference."""

import sqlalchemy as sa
from alembic import op

revision = "20260927_0020"
down_revision = "20260927_0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("avatar_file_id", sa.Uuid(as_uuid=True, native_uuid=False)))


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_column("avatar_file_id")
