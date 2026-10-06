"""Ticket categories and contextual course comment moderation."""

import sqlalchemy as sa
from alembic import op

revision = "20260912_0010"
down_revision = "20260910_0009"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "support_tickets",
        sa.Column("category", sa.String(32), nullable=False, server_default="general"),
    )
    op.create_index("ix_support_tickets_category", "support_tickets", ["category"])
    with op.batch_alter_table("course_comments") as batch:
        batch.add_column(sa.Column("lesson_id", sa.Uuid(native_uuid=False), nullable=True))
        batch.add_column(sa.Column("parent_id", sa.Uuid(native_uuid=False), nullable=True))
        batch.create_foreign_key("fk_course_comments_lesson", "lessons", ["lesson_id"], ["id"])
        batch.create_foreign_key(
            "fk_course_comments_parent", "course_comments", ["parent_id"], ["id"]
        )
    op.create_index("ix_course_comments_lesson_id", "course_comments", ["lesson_id"])
    op.create_index("ix_course_comments_parent_id", "course_comments", ["parent_id"])


def downgrade():
    op.drop_index("ix_course_comments_parent_id", table_name="course_comments")
    op.drop_index("ix_course_comments_lesson_id", table_name="course_comments")
    with op.batch_alter_table("course_comments") as batch:
        batch.drop_column("parent_id")
        batch.drop_column("lesson_id")
    op.drop_index("ix_support_tickets_category", table_name="support_tickets")
    with op.batch_alter_table("support_tickets") as batch:
        batch.drop_column("category")
