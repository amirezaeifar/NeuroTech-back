"""connect event speakers to user profiles

Revision ID: 20260909_0006
Revises: 20260909_0005
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260909_0006"
down_revision: str | None = "20260909_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
uuid_type = sa.Uuid(as_uuid=True, native_uuid=False)


def upgrade() -> None:
    op.create_table(
        "event_speakers",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("event_id", uuid_type, sa.ForeignKey("events.id"), nullable=False),
        sa.Column("user_id", uuid_type, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("role_label", sa.String(160), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.UniqueConstraint("event_id", "user_id"),
        sa.UniqueConstraint("event_id", "position"),
    )
    op.create_index("ix_event_speakers_event_id", "event_speakers", ["event_id"])
    op.create_index("ix_event_speakers_user_id", "event_speakers", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_event_speakers_user_id", table_name="event_speakers")
    op.drop_index("ix_event_speakers_event_id", table_name="event_speakers")
    op.drop_table("event_speakers")
