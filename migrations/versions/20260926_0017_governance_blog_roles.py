"""Add governance workflow, blog, settings, ownership, and expanded roles."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260926_0017"
down_revision = "20260913_0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("courses") as batch_op:
        batch_op.add_column(
            sa.Column(
                "owner_user_id", sa.Uuid(as_uuid=True, native_uuid=False), nullable=True
            )
        )
        batch_op.create_foreign_key(
            "fk_courses_owner_user_id_users",
            "users",
            ["owner_user_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index("ix_courses_owner_user_id", ["owner_user_id"])

    op.create_table(
        "approval_requests",
        sa.Column("resource_type", sa.String(40), nullable=False),
        sa.Column("resource_key", sa.String(200), nullable=False),
        sa.Column("resource_id", sa.Uuid(as_uuid=True, native_uuid=False), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("requested_by_user_id", sa.Uuid(as_uuid=True, native_uuid=False), nullable=False),
        sa.Column(
            "last_requested_by_user_id",
            sa.Uuid(as_uuid=True, native_uuid=False),
            nullable=False,
        ),
        sa.Column("reviewed_by_user_id", sa.Uuid(as_uuid=True, native_uuid=False), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column("changes_json", sa.Text(), nullable=False),
        sa.Column("id", sa.Uuid(as_uuid=True, native_uuid=False), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(["requested_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["last_requested_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["reviewed_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_approval_requests_status_updated",
        "approval_requests",
        ["status", "updated_at"],
    )
    op.create_index(
        "ix_approval_requests_resource",
        "approval_requests",
        ["resource_type", "resource_key"],
    )

    op.create_table(
        "blog_posts",
        sa.Column("slug", sa.String(180), nullable=False),
        sa.Column("author_user_id", sa.Uuid(as_uuid=True, native_uuid=False), nullable=False),
        sa.Column("cover_url", sa.String(1000), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(as_uuid=True, native_uuid=False), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(["author_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_table(
        "blog_post_translations",
        sa.Column("post_id", sa.Uuid(as_uuid=True, native_uuid=False), nullable=False),
        sa.Column("locale", sa.String(5), nullable=False),
        sa.Column("title", sa.String(240), nullable=False),
        sa.Column("excerpt", sa.String(600), nullable=False, server_default=""),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("id", sa.Uuid(as_uuid=True, native_uuid=False), nullable=False),
        sa.ForeignKeyConstraint(["post_id"], ["blog_posts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("post_id", "locale"),
    )
    op.create_table(
        "site_settings",
        sa.Column("key", sa.String(100), nullable=False),
        sa.Column("value_json", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by_user_id", sa.Uuid(as_uuid=True, native_uuid=False), nullable=False),
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("key"),
    )
    op.execute("UPDATE users SET role = 'super_admin' WHERE role = 'admin'")


def downgrade() -> None:
    op.execute("UPDATE users SET role = 'admin' WHERE role = 'super_admin'")
    op.drop_table("site_settings")
    op.drop_table("blog_post_translations")
    op.drop_table("blog_posts")
    op.drop_index("ix_approval_requests_resource", table_name="approval_requests")
    op.drop_index("ix_approval_requests_status_updated", table_name="approval_requests")
    op.drop_table("approval_requests")
    with op.batch_alter_table("courses") as batch_op:
        batch_op.drop_index("ix_courses_owner_user_id")
        batch_op.drop_constraint("fk_courses_owner_user_id_users", type_="foreignkey")
        batch_op.drop_column("owner_user_id")
