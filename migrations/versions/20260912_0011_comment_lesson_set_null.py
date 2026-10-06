"""Preserve comments when course lessons are replaced."""

from alembic import op

revision = "20260912_0011"
down_revision = "20260912_0010"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("course_comments") as batch:
        batch.drop_constraint("fk_course_comments_lesson", type_="foreignkey")
        batch.create_foreign_key(
            "fk_course_comments_lesson",
            "lessons",
            ["lesson_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade():
    with op.batch_alter_table("course_comments") as batch:
        batch.drop_constraint("fk_course_comments_lesson", type_="foreignkey")
        batch.create_foreign_key(
            "fk_course_comments_lesson", "lessons", ["lesson_id"], ["id"]
        )
