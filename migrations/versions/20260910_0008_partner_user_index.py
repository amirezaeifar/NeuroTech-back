"""remove the redundant partner user index

Revision ID: 20260910_0008
Revises: 20260909_0007
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260910_0008"
down_revision: str | None = "20260909_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index("ix_partner_profiles_user_id", table_name="partner_profiles")


def downgrade() -> None:
    op.create_index(
        "ix_partner_profiles_user_id", "partner_profiles", ["user_id"], unique=False
    )
