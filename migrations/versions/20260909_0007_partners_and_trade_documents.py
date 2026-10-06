"""partner directory and global-trade documents

Revision ID: 20260909_0007
Revises: 20260909_0006
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260909_0007"
down_revision: str | None = "20260909_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
uuid_type = sa.Uuid(as_uuid=True, native_uuid=False)


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.Column("version", sa.Integer(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "partner_profiles",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("user_id", uuid_type, sa.ForeignKey("users.id"), unique=True),
        sa.Column("slug", sa.String(160), nullable=False, unique=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("image_file_id", uuid_type, sa.ForeignKey("stored_files.id")),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        *_timestamps(),
    )
    op.create_index("ix_partner_profiles_user_id", "partner_profiles", ["user_id"])
    op.create_index("ix_partner_profiles_published_at", "partner_profiles", ["published_at"])
    op.create_table(
        "partner_translations",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("partner_id", uuid_type, sa.ForeignKey("partner_profiles.id"), nullable=False),
        sa.Column("locale", sa.String(5), nullable=False),
        sa.Column("name", sa.String(240), nullable=False),
        sa.Column("title", sa.String(240), nullable=False),
        sa.Column("qualification", sa.String(300), nullable=False),
        sa.Column("location", sa.String(240), nullable=False),
        sa.Column("affiliation", sa.String(300), nullable=False),
        sa.Column("bio", sa.Text(), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.UniqueConstraint("partner_id", "locale"),
    )
    op.create_table(
        "trade_documents",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("slug", sa.String(190), nullable=False, unique=True),
        sa.Column("document_code", sa.String(100), nullable=False, unique=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("attachment_file_id", uuid_type, sa.ForeignKey("stored_files.id")),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        *_timestamps(),
    )
    op.create_index("ix_trade_documents_published_at", "trade_documents", ["published_at"])
    op.create_table(
        "trade_document_translations",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("document_id", uuid_type, sa.ForeignKey("trade_documents.id"), nullable=False),
        sa.Column("locale", sa.String(5), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("doc_type", sa.String(240), nullable=False),
        sa.Column("partner_name", sa.String(240), nullable=False),
        sa.Column("category", sa.String(240), nullable=False),
        sa.Column("location", sa.String(240)),
        sa.Column("region", sa.String(240)),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("groups", sa.JSON(), nullable=False),
        sa.UniqueConstraint("document_id", "locale"),
    )
    op.create_table(
        "managed_pages",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("page_key", sa.String(80), nullable=False, unique=True),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        *_timestamps(),
    )
    op.create_index("ix_managed_pages_published_at", "managed_pages", ["published_at"])
    op.create_table(
        "managed_page_translations",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("page_id", uuid_type, sa.ForeignKey("managed_pages.id"), nullable=False),
        sa.Column("locale", sa.String(5), nullable=False),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.UniqueConstraint("page_id", "locale"),
    )


def downgrade() -> None:
    op.drop_table("managed_page_translations")
    op.drop_index("ix_managed_pages_published_at", table_name="managed_pages")
    op.drop_table("managed_pages")
    op.drop_table("trade_document_translations")
    op.drop_index("ix_trade_documents_published_at", table_name="trade_documents")
    op.drop_table("trade_documents")
    op.drop_table("partner_translations")
    op.drop_index("ix_partner_profiles_published_at", table_name="partner_profiles")
    op.drop_index("ix_partner_profiles_user_id", table_name="partner_profiles")
    op.drop_table("partner_profiles")
