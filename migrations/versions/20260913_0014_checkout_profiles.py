"""Add persisted checkout profiles."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260913_0014"
down_revision = "20260913_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "checkout_profiles",
        sa.Column("user_id", sa.Uuid(as_uuid=True, native_uuid=False), nullable=False),
        sa.Column("full_name", sa.String(length=160), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("phone", sa.String(length=24), nullable=False),
        sa.Column("national_id", sa.String(length=20), nullable=True),
        sa.Column("address", sa.String(length=1000), nullable=True),
        sa.Column("city", sa.String(length=120), nullable=True),
        sa.Column("postal_code", sa.String(length=20), nullable=True),
        sa.Column("id", sa.Uuid(as_uuid=True, native_uuid=False), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
    )
    op.create_index("ix_checkout_profiles_user_id", "checkout_profiles", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_checkout_profiles_user_id", table_name="checkout_profiles")
    op.drop_table("checkout_profiles")
