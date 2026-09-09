"""academy catalogue

Revision ID: 20260907_0002
Revises: 20260907_0001
Create Date: 2026-09-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260907_0002"
down_revision: str | None = "20260907_0001"
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
    op.create_table(
        "courses",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("slug", sa.String(160), nullable=False, unique=True),
        sa.Column("tier", sa.String(20), nullable=False),
        sa.Column("field", sa.String(60), nullable=False),
        sa.Column("level", sa.String(30), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        *_timestamps(),
    )
    op.create_table(
        "course_translations",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("course_id", uuid_type, sa.ForeignKey("courses.id"), nullable=False),
        sa.Column("locale", sa.String(5), nullable=False),
        sa.Column("title", sa.String(240), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("instructor_name", sa.String(160), nullable=False),
        sa.Column("duration_label", sa.String(80), nullable=False),
        sa.UniqueConstraint("course_id", "locale"),
    )
    op.create_table(
        "course_prices",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("course_id", uuid_type, sa.ForeignKey("courses.id"), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.UniqueConstraint("course_id", "currency"),
    )
    op.create_table(
        "course_sections",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("course_id", uuid_type, sa.ForeignKey("courses.id"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.UniqueConstraint("course_id", "position"),
    )
    op.create_table(
        "section_translations",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("section_id", uuid_type, sa.ForeignKey("course_sections.id"), nullable=False),
        sa.Column("locale", sa.String(5), nullable=False),
        sa.Column("title", sa.String(240), nullable=False),
        sa.UniqueConstraint("section_id", "locale"),
    )
    op.create_table(
        "lessons",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("section_id", uuid_type, sa.ForeignKey("course_sections.id"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("duration_seconds", sa.Integer(), nullable=False),
        sa.Column("video_provider", sa.String(30), nullable=False),
        sa.Column("video_reference", sa.String(255), nullable=False),
        sa.Column("free_preview", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("section_id", "position"),
    )
    op.create_table(
        "lesson_translations",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("lesson_id", uuid_type, sa.ForeignKey("lessons.id"), nullable=False),
        sa.Column("locale", sa.String(5), nullable=False),
        sa.Column("title", sa.String(240), nullable=False),
        sa.UniqueConstraint("lesson_id", "locale"),
    )
    op.create_table(
        "learning_outcomes",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("course_id", uuid_type, sa.ForeignKey("courses.id"), nullable=False),
        sa.Column("locale", sa.String(5), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("text", sa.String(500), nullable=False),
        sa.UniqueConstraint("course_id", "locale", "position"),
    )
    op.create_table(
        "course_resources",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("course_id", uuid_type, sa.ForeignKey("courses.id"), nullable=False),
        sa.Column("lesson_id", uuid_type, sa.ForeignKey("lessons.id")),
        sa.Column("name", sa.String(240), nullable=False),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("storage_path", sa.String(500)),
        sa.Column("external_url", sa.String(1000)),
        *_timestamps(),
    )


def downgrade() -> None:
    for table in (
        "course_resources",
        "learning_outcomes",
        "lesson_translations",
        "lessons",
        "section_translations",
        "course_sections",
        "course_prices",
        "course_translations",
        "courses",
    ):
        op.drop_table(table)
