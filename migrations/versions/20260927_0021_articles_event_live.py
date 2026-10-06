"""Article metadata and persistent live event activity."""

import sqlalchemy as sa
from alembic import op

revision = "20260927_0021"
down_revision = "20260927_0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("blog_posts") as batch:
        batch.add_column(
            sa.Column("category", sa.String(20), nullable=False, server_default="blog")
        )
        batch.add_column(sa.Column("cover_alt", sa.String(240), nullable=False, server_default=""))
        batch.create_index("ix_blog_posts_category", ["category"])
    with op.batch_alter_table("blog_post_translations") as batch:
        batch.add_column(sa.Column("seo_title", sa.String(240), nullable=False, server_default=""))
        batch.add_column(
            sa.Column("seo_description", sa.String(600), nullable=False, server_default="")
        )
        batch.add_column(
            sa.Column("seo_keywords", sa.String(500), nullable=False, server_default="")
        )
    with op.batch_alter_table("events") as batch:
        batch.add_column(sa.Column("cover_url", sa.String(1000)))
        batch.add_column(sa.Column("agenda_steps", sa.JSON(), nullable=False, server_default="[]"))
        batch.add_column(
            sa.Column("current_step", sa.Integer(), nullable=False, server_default="0")
        )
    for table, columns, extras in (
        (
            "event_live_presence",
            [
                sa.Column("country_code", sa.String(2)),
                sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False),
                sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
            ],
            True,
        ),
        (
            "event_live_messages",
            [
                sa.Column("body", sa.String(1000), nullable=False),
                sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            ],
            False,
        ),
        (
            "event_live_questions",
            [
                sa.Column("body", sa.String(1000), nullable=False),
                sa.Column("answered", sa.Boolean(), nullable=False, server_default=sa.false()),
                sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            ],
            False,
        ),
    ):
        op.create_table(
            table,
            sa.Column("id", sa.Uuid(as_uuid=True, native_uuid=False), primary_key=True),
            sa.Column(
                "event_id",
                sa.Uuid(as_uuid=True, native_uuid=False),
                sa.ForeignKey("events.id"),
                nullable=False,
            ),
            sa.Column(
                "user_id",
                sa.Uuid(as_uuid=True, native_uuid=False),
                sa.ForeignKey("users.id"),
                nullable=False,
            ),
            *columns,
            *([sa.UniqueConstraint("event_id", "user_id")] if extras else []),
        )
        op.create_index(f"ix_{table}_event_id", table, ["event_id"])
    op.create_table(
        "event_live_votes",
        sa.Column("id", sa.Uuid(as_uuid=True, native_uuid=False), primary_key=True),
        sa.Column(
            "question_id",
            sa.Uuid(as_uuid=True, native_uuid=False),
            sa.ForeignKey("event_live_questions.id"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Uuid(as_uuid=True, native_uuid=False),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.UniqueConstraint("question_id", "user_id"),
    )
    op.create_index("ix_event_live_votes_question_id", "event_live_votes", ["question_id"])


def downgrade() -> None:
    op.drop_index("ix_event_live_votes_question_id", table_name="event_live_votes")
    op.drop_table("event_live_votes")
    for table in ("event_live_questions", "event_live_messages", "event_live_presence"):
        op.drop_index(f"ix_{table}_event_id", table_name=table)
        op.drop_table(table)
    with op.batch_alter_table("events") as batch:
        batch.drop_column("current_step")
        batch.drop_column("agenda_steps")
        batch.drop_column("cover_url")
    with op.batch_alter_table("blog_post_translations") as batch:
        batch.drop_column("seo_keywords")
        batch.drop_column("seo_description")
        batch.drop_column("seo_title")
    with op.batch_alter_table("blog_posts") as batch:
        batch.drop_index("ix_blog_posts_category")
        batch.drop_column("cover_alt")
        batch.drop_column("category")
