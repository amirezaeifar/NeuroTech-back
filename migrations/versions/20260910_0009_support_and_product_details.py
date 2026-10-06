"""Guest support tickets and per-product page details."""

import sqlalchemy as sa
from alembic import op

revision = "20260910_0009"
down_revision = "20260910_0008"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("course_translations", sa.Column("summary", sa.Text(), nullable=True))
    op.execute(sa.text("UPDATE course_translations SET summary = '' WHERE summary IS NULL"))
    with op.batch_alter_table("course_translations") as batch:
        batch.alter_column("summary", existing_type=sa.Text(), nullable=False)
    op.add_column("product_translations", sa.Column("details", sa.JSON(), nullable=True))
    op.execute(sa.text("UPDATE product_translations SET details = '{}' WHERE details IS NULL"))
    with op.batch_alter_table("product_translations") as batch:
        batch.alter_column("details", existing_type=sa.JSON(), nullable=False)
    op.create_table(
        "support_tickets",
        sa.Column("id", sa.Uuid(native_uuid=False), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("tracking_token", sa.String(64), nullable=False, unique=True),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("phone", sa.String(24), nullable=False),
        sa.Column("email", sa.String(254)),
        sa.Column("subject", sa.String(240), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("locale", sa.String(5), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("history", sa.JSON(), nullable=False),
    )
    op.create_index("ix_support_tickets_status", "support_tickets", ["status"])


def downgrade():
    with op.batch_alter_table("course_translations") as batch:
        batch.drop_column("summary")
    op.drop_table("support_tickets")
    with op.batch_alter_table("product_translations") as batch:
        batch.drop_column("details")
