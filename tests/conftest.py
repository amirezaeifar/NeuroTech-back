from __future__ import annotations

import os

import pytest
from argon2 import PasswordHasher

from app import create_app
from app.core.models import Base


@pytest.fixture
def app(monkeypatch: pytest.MonkeyPatch, tmp_path):  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        "app.core.security._password_hasher",
        PasswordHasher(time_cost=1, memory_cost=8192, parallelism=1),
    )
    monkeypatch.setenv("SECRET_KEY", "test-secret-key")
    monkeypatch.setenv("SMS_PROVIDER", "fake")
    monkeypatch.setenv("PAYMENT_PROVIDER", "fake")
    monkeypatch.setenv("UPLOAD_ROOT", str(tmp_path / "uploads"))
    database_url = os.getenv("INTEGRATION_DATABASE_URL") or ("sqlite+pysqlite://")
    monkeypatch.setenv("TEST_DATABASE_URL", database_url)
    monkeypatch.setenv("TEST_REDIS_NAMESPACE", f"neurotech:test:{tmp_path.name}")

    application = create_app(
        "testing",
        {
            "PROPAGATE_EXCEPTIONS": False,
            "SERVER_NAME": "localhost",
        },
    )
    database = application.extensions["container"].database
    Base.metadata.create_all(database.engine)
    yield application
    Base.metadata.drop_all(database.engine)
    database.dispose()
    redis_store = application.extensions["container"].redis
    keys = list(redis_store.client.scan_iter(match=redis_store.key("*")))
    if keys:
        redis_store.client.delete(*keys)
    redis_store.close()


@pytest.fixture
def client(app):  # type: ignore[no-untyped-def]
    return app.test_client()
