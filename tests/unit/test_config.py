from __future__ import annotations

import pytest

from app import create_app
from app.core.config import ConfigurationError, Settings


def test_testing_environment_has_safe_framework_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SECRET_KEY", "test-secret")

    settings = Settings.from_env("testing")

    assert settings.testing is True
    assert settings.debug is False


def test_unknown_environment_is_rejected() -> None:
    with pytest.raises(ConfigurationError, match="APP_ENV"):
        Settings.from_env("staging")


def test_production_rejects_default_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SECRET_KEY", raising=False)

    with pytest.raises(ConfigurationError, match="Production SECRET_KEY"):
        Settings.from_env("production")


def test_factory_applies_explicit_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("SMS_PROVIDER", "fake")
    monkeypatch.setenv("PAYMENT_PROVIDER", "fake")

    app = create_app("testing", {"SERVICE_NAME": "test-neurotech-api"})

    assert app.config["TESTING"] is True
    assert app.config["SERVICE_NAME"] == "test-neurotech-api"


def test_testing_uses_dedicated_database_and_namespace(monkeypatch: pytest.MonkeyPatch) -> None:
    database_url = "mysql+pymysql://test@127.0.0.1/neurotech_test"
    monkeypatch.setenv("TEST_DATABASE_URL", database_url)
    monkeypatch.delenv("REDIS_NAMESPACE", raising=False)

    settings = Settings.from_env("testing")

    assert settings.database_url == database_url
    assert settings.redis_namespace == "neurotech:test"


def test_refresh_lifetime_cannot_exceed_session_lifetime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JWT_REFRESH_TTL_DAYS", "31")
    monkeypatch.setenv("JWT_SESSION_MAX_DAYS", "30")

    with pytest.raises(ConfigurationError, match="cannot exceed"):
        Settings.from_env("testing")


def test_testing_rejects_development_database_and_redis_namespace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "TEST_DATABASE_URL",
        "mysql+pymysql://tester:secret@127.0.0.1:3306/neurotech_dev",
    )
    monkeypatch.setenv("TEST_REDIS_NAMESPACE", "neurotech:test:safe")
    with pytest.raises(ConfigurationError, match="neurotech_test database"):
        Settings.from_env("testing")

    monkeypatch.setenv("TEST_DATABASE_URL", "sqlite+pysqlite://")
    monkeypatch.setenv("TEST_REDIS_NAMESPACE", "neurotech:dev")
    with pytest.raises(ConfigurationError, match="neurotech:test"):
        Settings.from_env("testing")
