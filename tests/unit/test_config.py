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
