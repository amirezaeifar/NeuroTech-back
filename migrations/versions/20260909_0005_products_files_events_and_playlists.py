"""products, files, product commerce, events, and course playlists

Revision ID: 20260909_0005
Revises: 20260907_0004
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260909_0005"
down_revision: str | None = "20260907_0004"
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
    op.add_column("courses", sa.Column("youtube_playlist_id", sa.String(100)))
    op.create_table(
        "stored_files",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("uploader_id", uuid_type, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("storage_key", sa.String(500), nullable=False, unique=True),
        sa.Column("original_name", sa.String(255), nullable=False),
        sa.Column("mime_type", sa.String(120), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("is_public", sa.Boolean(), nullable=False),
        *_timestamps(),
    )
    op.create_index("ix_stored_files_sha256", "stored_files", ["sha256"])
    op.create_table(
        "product_categories",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("slug", sa.String(120), nullable=False, unique=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        *_timestamps(),
    )
    op.create_table(
        "product_category_translations",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("category_id", uuid_type, sa.ForeignKey("product_categories.id"), nullable=False),
        sa.Column("locale", sa.String(5), nullable=False),
        sa.Column("title", sa.String(160), nullable=False),
        sa.UniqueConstraint("category_id", "locale"),
    )
    op.create_table(
        "products",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("category_id", uuid_type, sa.ForeignKey("product_categories.id"), nullable=False),
        sa.Column("slug", sa.String(160), nullable=False, unique=True),
        sa.Column("sku", sa.String(80), nullable=False, unique=True),
        sa.Column("sale_mode", sa.String(20), nullable=False),
        sa.Column("stock_quantity", sa.Integer()),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        *_timestamps(),
    )
    for column in ("category_id", "sale_mode", "published_at"):
        op.create_index(f"ix_products_{column}", "products", [column])
    op.create_table(
        "product_translations",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("product_id", uuid_type, sa.ForeignKey("products.id"), nullable=False),
        sa.Column("locale", sa.String(5), nullable=False),
        sa.Column("name", sa.String(240), nullable=False),
        sa.Column("short_description", sa.String(500), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.UniqueConstraint("product_id", "locale"),
    )
    op.create_table(
        "product_prices",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("product_id", uuid_type, sa.ForeignKey("products.id"), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.UniqueConstraint("product_id", "currency"),
    )
    op.create_table(
        "product_media",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("product_id", uuid_type, sa.ForeignKey("products.id"), nullable=False),
        sa.Column("stored_file_id", uuid_type, sa.ForeignKey("stored_files.id")),
        sa.Column("external_url", sa.String(1000)),
        sa.Column("alt_text", sa.String(255), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint("product_id", "position"),
    )
    op.create_table(
        "shopping_carts",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("user_id", uuid_type, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        *_timestamps(),
    )
    op.create_index("ix_shopping_carts_user_id", "shopping_carts", ["user_id"])
    op.create_index("ix_shopping_carts_status", "shopping_carts", ["status"])
    op.create_table(
        "cart_items",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("cart_id", uuid_type, sa.ForeignKey("shopping_carts.id"), nullable=False),
        sa.Column("product_id", uuid_type, sa.ForeignKey("products.id"), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint("cart_id", "product_id"),
    )
    op.create_table(
        "product_inquiries",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("product_id", uuid_type, sa.ForeignKey("products.id"), nullable=False),
        sa.Column("user_id", uuid_type, sa.ForeignKey("users.id")),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("phone", sa.String(32)),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("response", sa.Text()),
        sa.Column("responded_by", uuid_type, sa.ForeignKey("users.id")),
        sa.Column("responded_at", sa.DateTime(timezone=True)),
        *_timestamps(),
    )
    for column in ("product_id", "user_id", "email", "status"):
        op.create_index(f"ix_product_inquiries_{column}", "product_inquiries", [column])
    op.create_table(
        "product_orders",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("user_id", uuid_type, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("total_minor", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("shipping_address", sa.JSON(), nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True)),
        *_timestamps(),
    )
    op.create_index("ix_product_orders_user_id", "product_orders", ["user_id"])
    op.create_index("ix_product_orders_status", "product_orders", ["status"])
    op.create_table(
        "product_order_items",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("order_id", uuid_type, sa.ForeignKey("product_orders.id"), nullable=False),
        sa.Column("product_id", uuid_type, sa.ForeignKey("products.id"), nullable=False),
        sa.Column("title_snapshot", sa.String(240), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_amount_minor", sa.BigInteger(), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint("order_id", "product_id"),
    )
    op.create_index("ix_product_order_items_order_id", "product_order_items", ["order_id"])
    op.create_table(
        "product_payment_attempts",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("order_id", uuid_type, sa.ForeignKey("product_orders.id"), nullable=False),
        sa.Column("provider", sa.String(30), nullable=False),
        sa.Column("provider_reference", sa.String(160), nullable=False, unique=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("redirect_url", sa.Text(), nullable=False),
        *_timestamps(),
    )
    op.create_index(
        "ix_product_payment_attempts_order_id", "product_payment_attempts", ["order_id"]
    )
    op.create_table(
        "product_payment_events",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column(
            "attempt_id", uuid_type, sa.ForeignKey("product_payment_attempts.id"), nullable=False
        ),
        sa.Column("provider_event_id", sa.String(190), nullable=False, unique=True),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        *_timestamps(),
    )
    op.create_table(
        "events",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("slug", sa.String(160), nullable=False, unique=True),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("timezone", sa.String(60), nullable=False),
        sa.Column("capacity", sa.Integer()),
        sa.Column("online_url", sa.String(1000)),
        sa.Column("venue", sa.String(500)),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        *_timestamps(),
    )
    for column in ("kind", "status", "starts_at", "published_at"):
        op.create_index(f"ix_events_{column}", "events", [column])
    op.create_table(
        "event_translations",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("event_id", uuid_type, sa.ForeignKey("events.id"), nullable=False),
        sa.Column("locale", sa.String(5), nullable=False),
        sa.Column("title", sa.String(240), nullable=False),
        sa.Column("summary", sa.String(500), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("host_label", sa.String(240), nullable=False),
        sa.UniqueConstraint("event_id", "locale"),
    )
    op.create_table(
        "event_reservations",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("event_id", uuid_type, sa.ForeignKey("events.id"), nullable=False),
        sa.Column("user_id", uuid_type, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("reserved_at", sa.DateTime(timezone=True), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint("event_id", "user_id"),
    )
    op.create_index("ix_event_reservations_event_id", "event_reservations", ["event_id"])
    op.create_index("ix_event_reservations_user_id", "event_reservations", ["user_id"])
    op.create_index("ix_event_reservations_status", "event_reservations", ["status"])


def downgrade() -> None:
    for table in (
        "event_reservations",
        "event_translations",
        "events",
        "product_payment_events",
        "product_payment_attempts",
        "product_order_items",
        "product_orders",
        "product_inquiries",
        "cart_items",
        "shopping_carts",
        "product_media",
        "product_prices",
        "product_translations",
        "products",
        "product_category_translations",
        "product_categories",
        "stored_files",
    ):
        op.drop_table(table)
    op.drop_column("courses", "youtube_playlist_id")
