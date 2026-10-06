"""Add fulfillment workflow to product orders."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260913_0016"
down_revision = "20260913_0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "product_orders",
        sa.Column(
            "fulfillment_status",
            sa.String(length=30),
            nullable=False,
            server_default="awaiting_payment",
        ),
    )
    op.create_index(
        "ix_product_orders_fulfillment_status",
        "product_orders",
        ["fulfillment_status"],
    )
    op.execute(
        "UPDATE product_orders SET fulfillment_status = 'awaiting_confirmation' "
        "WHERE status = 'paid'"
    )


def downgrade() -> None:
    op.drop_index("ix_product_orders_fulfillment_status", table_name="product_orders")
    op.drop_column("product_orders", "fulfillment_status")
