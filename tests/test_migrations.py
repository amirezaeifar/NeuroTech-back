from __future__ import annotations

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


def test_migrations_upgrade_an_empty_database(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    database_path = tmp_path / "migration.db"
    url = f"sqlite+pysqlite:///{database_path}"
    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("TEST_DATABASE_URL", url)
    config = Config("alembic.ini")

    command.upgrade(config, "head")

    engine = create_engine(url)
    tables = set(inspect(engine).get_table_names())
    assert {
        "users",
        "courses",
        "course_media",
        "enrollments",
        "orders",
        "payment_events",
        "entitlements",
        "user_profiles",
        "products",
        "product_inquiries",
        "product_orders",
        "stored_files",
        "events",
        "event_reservations",
        "event_speakers",
        "partner_profiles",
        "partner_translations",
        "trade_documents",
        "trade_document_translations",
        "managed_pages",
        "managed_page_translations",
        "support_tickets",
    }.issubset(tables)
    assert "details" in {
        column["name"] for column in inspect(engine).get_columns("product_translations")
    }
    assert "summary" in {
        column["name"] for column in inspect(engine).get_columns("course_translations")
    }
    assert "fulfillment_status" in {
        column["name"] for column in inspect(engine).get_columns("product_orders")
    }
    assert {"chat_enabled", "questions_enabled"}.issubset(
        {column["name"] for column in inspect(engine).get_columns("events")}
    )
    assert "content" in {
        column["name"] for column in inspect(engine).get_columns("event_translations")
    }
    engine.dispose()
