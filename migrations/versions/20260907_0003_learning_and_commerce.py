"""learning, orders, payments, and entitlements

Revision ID: 20260907_0003
Revises: 20260907_0002
Create Date: 2026-09-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260907_0003"
down_revision: str | None = "20260907_0002"
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
        "enrollments",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("user_id", uuid_type, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("course_id", uuid_type, sa.ForeignKey("courses.id"), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("enrolled_at", sa.DateTime(timezone=True), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint("user_id", "course_id"),
    )
    op.create_index("ix_enrollments_user_id", "enrollments", ["user_id"])
    op.create_index("ix_enrollments_course_id", "enrollments", ["course_id"])
    op.create_table(
        "lesson_progress",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("enrollment_id", uuid_type, sa.ForeignKey("enrollments.id"), nullable=False),
        sa.Column("lesson_id", uuid_type, sa.ForeignKey("lessons.id"), nullable=False),
        sa.Column("position_seconds", sa.Integer(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        *_timestamps(),
        sa.UniqueConstraint("enrollment_id", "lesson_id"),
    )
    op.create_table(
        "course_comments",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("course_id", uuid_type, sa.ForeignKey("courses.id"), nullable=False),
        sa.Column("user_id", uuid_type, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        *_timestamps(),
    )
    op.create_index("ix_course_comments_course_id", "course_comments", ["course_id"])
    op.create_index("ix_course_comments_user_id", "course_comments", ["user_id"])
    op.create_index("ix_course_comments_status", "course_comments", ["status"])
    op.create_table(
        "moderation_decisions",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("comment_id", uuid_type, sa.ForeignKey("course_comments.id"), nullable=False),
        sa.Column("moderator_id", uuid_type, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("decision", sa.String(20), nullable=False),
        sa.Column("reason", sa.String(500)),
        *_timestamps(),
    )
    op.create_table(
        "orders",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("user_id", uuid_type, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("total_minor", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True)),
        *_timestamps(),
    )
    op.create_index("ix_orders_user_id", "orders", ["user_id"])
    op.create_index("ix_orders_status", "orders", ["status"])
    op.create_table(
        "order_items",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("order_id", uuid_type, sa.ForeignKey("orders.id"), nullable=False),
        sa.Column("course_id", uuid_type, sa.ForeignKey("courses.id"), nullable=False),
        sa.Column("title_snapshot", sa.String(240), nullable=False),
        sa.Column("unit_amount_minor", sa.BigInteger(), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint("order_id", "course_id"),
    )
    op.create_table(
        "payment_attempts",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("order_id", uuid_type, sa.ForeignKey("orders.id"), nullable=False),
        sa.Column("provider", sa.String(30), nullable=False),
        sa.Column("provider_reference", sa.String(160), nullable=False, unique=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("redirect_url", sa.Text(), nullable=False),
        *_timestamps(),
    )
    op.create_index("ix_payment_attempts_order_id", "payment_attempts", ["order_id"])
    op.create_table(
        "payment_events",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("attempt_id", uuid_type, sa.ForeignKey("payment_attempts.id"), nullable=False),
        sa.Column("provider_event_id", sa.String(190), nullable=False, unique=True),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        *_timestamps(),
    )
    op.create_table(
        "entitlements",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("user_id", uuid_type, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("course_id", uuid_type, sa.ForeignKey("courses.id"), nullable=False),
        sa.Column("source_order_id", uuid_type, sa.ForeignKey("orders.id"), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        *_timestamps(),
        sa.UniqueConstraint("user_id", "course_id"),
    )
    op.create_index("ix_entitlements_user_id", "entitlements", ["user_id"])
    op.create_index("ix_entitlements_course_id", "entitlements", ["course_id"])


def downgrade() -> None:
    for table in (
        "entitlements",
        "payment_events",
        "payment_attempts",
        "order_items",
        "orders",
        "moderation_decisions",
        "course_comments",
        "lesson_progress",
        "enrollments",
    ):
        op.drop_table(table)
