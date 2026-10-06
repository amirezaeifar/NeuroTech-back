"""Store each member's favorite courses and products."""

import sqlalchemy as sa
from alembic import op

revision = "20260927_0019"
down_revision = "20260927_0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "favorites",
        sa.Column("id", sa.Uuid(as_uuid=True, native_uuid=False), primary_key=True),
        sa.Column("user_id", sa.Uuid(as_uuid=True, native_uuid=False), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("item_type", sa.String(20), nullable=False),
        sa.Column("item_id", sa.Uuid(as_uuid=True, native_uuid=False), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.UniqueConstraint("user_id", "item_type", "item_id"),
    )
    op.create_index("ix_favorites_user_id", "favorites", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_favorites_user_id", table_name="favorites")
    op.drop_table("favorites")
