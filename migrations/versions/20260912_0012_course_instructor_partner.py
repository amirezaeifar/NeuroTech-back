"""Link Academy courses to partner instructors."""

import sqlalchemy as sa
from alembic import op

revision = "20260912_0012"
down_revision = "20260912_0011"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("courses") as batch:
        batch.add_column(
            sa.Column(
                "instructor_partner_id",
                sa.Uuid(as_uuid=True, native_uuid=False),
                nullable=True,
            )
        )
        batch.create_foreign_key(
            "fk_courses_instructor_partner",
            "partner_profiles",
            ["instructor_partner_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade():
    with op.batch_alter_table("courses") as batch:
        batch.drop_constraint("fk_courses_instructor_partner", type_="foreignkey")
        batch.drop_column("instructor_partner_id")
