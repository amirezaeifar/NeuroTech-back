"""Regenerate catalogue slugs from English titles and record IDs."""

from __future__ import annotations

import re
import unicodedata

import sqlalchemy as sa
from alembic import op

revision = "20260913_0013"
down_revision = "20260912_0012"
branch_labels = None
depends_on = None


def _slug(title: str, record_id, max_length: int, fallback: str) -> str:  # type: ignore[no-untyped-def]
    ascii_title = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    suffix = getattr(record_id, "hex", str(record_id).replace("-", ""))
    stem = "-".join(re.findall(r"[a-z0-9]+", ascii_title.lower()))
    stem = stem[: max_length - len(suffix) - 1].strip("-")
    return f"{stem or fallback}-{suffix}"


def upgrade() -> None:
    bind = op.get_bind()
    categories = sa.table(
        "product_categories",
        sa.column("id", sa.Uuid(as_uuid=True, native_uuid=False)),
        sa.column("slug", sa.String()),
    )
    category_translations = sa.table(
        "product_category_translations",
        sa.column("category_id", sa.Uuid(as_uuid=True, native_uuid=False)),
        sa.column("locale", sa.String()),
        sa.column("title", sa.String()),
    )
    products = sa.table(
        "products",
        sa.column("id", sa.Uuid(as_uuid=True, native_uuid=False)),
        sa.column("slug", sa.String()),
    )
    product_translations = sa.table(
        "product_translations",
        sa.column("product_id", sa.Uuid(as_uuid=True, native_uuid=False)),
        sa.column("locale", sa.String()),
        sa.column("name", sa.String()),
    )

    for record_id, title in bind.execute(
        sa.select(categories.c.id, category_translations.c.title)
        .join(category_translations, category_translations.c.category_id == categories.c.id)
        .where(category_translations.c.locale == "en")
    ):
        bind.execute(
            categories.update()
            .where(categories.c.id == record_id)
            .values(slug=_slug(title, record_id, 120, "category"))
        )

    for record_id, name in bind.execute(
        sa.select(products.c.id, product_translations.c.name)
        .join(product_translations, product_translations.c.product_id == products.c.id)
        .where(product_translations.c.locale == "en")
    ):
        bind.execute(
            products.update()
            .where(products.c.id == record_id)
            .values(slug=_slug(name, record_id, 160, "product"))
        )


def downgrade() -> None:
    # Previous user-entered slugs cannot be reconstructed safely.
    pass
