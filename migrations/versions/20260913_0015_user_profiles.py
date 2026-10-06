"""Rename checkout profiles to user profiles."""

from __future__ import annotations

from alembic import op

revision = "20260913_0015"
down_revision = "20260913_0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.rename_table("checkout_profiles", "user_profiles")
    op.drop_index("ix_checkout_profiles_user_id", table_name="user_profiles")
    op.create_index("ix_user_profiles_user_id", "user_profiles", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_user_profiles_user_id", table_name="user_profiles")
    op.create_index("ix_checkout_profiles_user_id", "user_profiles", ["user_id"])
    op.rename_table("user_profiles", "checkout_profiles")
