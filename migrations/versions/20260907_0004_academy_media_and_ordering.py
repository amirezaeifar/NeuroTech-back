"""academy media and explicit course ordering

Revision ID: 20260907_0004
Revises: 20260907_0003
Create Date: 2026-09-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260907_0004"
down_revision: str | None = "20260907_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
uuid_type = sa.Uuid(as_uuid=True, native_uuid=False)


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
    ]


def upgrade() -> None:
    op.add_column(
        "courses",
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_table(
        "course_media",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("course_id", uuid_type, sa.ForeignKey("courses.id"), nullable=False),
        sa.Column("lesson_id", uuid_type, sa.ForeignKey("lessons.id")),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("locale", sa.String(5)),
        sa.Column("mime_type", sa.String(120)),
        sa.Column("storage_path", sa.String(500)),
        sa.Column("external_url", sa.String(1000)),
        *_timestamps(),
        sa.UniqueConstraint("course_id", "position"),
    )


def downgrade() -> None:
    op.drop_table("course_media")
    op.drop_column("courses", "position")
