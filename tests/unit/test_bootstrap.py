from __future__ import annotations

import pytest

from app.bootstrap import bootstrap
from app.core.config import ConfigurationError, Settings
from app.core.integrations.fake_payment import FakePaymentGateway
from app.core.integrations.fake_sms import FakeSmsSender


def _settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("SMS_PROVIDER", "fake")
    monkeypatch.setenv("PAYMENT_PROVIDER", "fake")
    return Settings.from_env("testing")


def test_bootstrap_wires_fake_adapters(monkeypatch: pytest.MonkeyPatch) -> None:
    container = bootstrap(_settings(monkeypatch))

    assert isinstance(container.sms_sender, FakeSmsSender)
    assert isinstance(container.payment_gateway, FakePaymentGateway)


def test_fake_adapters_record_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    container = bootstrap(_settings(monkeypatch))

    sms_id = container.sms_sender.send("+989120000000", "123456")
    payment_url = container.payment_gateway.create_payment(
        reference="order-1",
        amount_minor=125_000,
        currency="IRR",
        callback_url="https://example.test/payment/callback",
    )

    assert sms_id.startswith("fake-sms-")
    assert len(container.sms_sender.sent_messages) == 1  # type: ignore[attr-defined]
    assert payment_url.startswith("https://payments.invalid/")
    assert len(container.payment_gateway.created_payments) == 1  # type: ignore[attr-defined]


def test_bootstrap_rejects_unimplemented_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings(monkeypatch)
    unsupported = Settings(
        environment=settings.environment,
        secret_key=settings.secret_key,
        log_level=settings.log_level,
        upload_root=settings.upload_root,
        sms_provider="real",
        payment_provider=settings.payment_provider,
        service_name=settings.service_name,
        service_version=settings.service_version,
        problem_base_uri=settings.problem_base_uri,
    )

    with pytest.raises(ConfigurationError, match="not implemented"):
        bootstrap(unsupported)
