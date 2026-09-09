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
    }.issubset(tables)
    engine.dispose()
