"""Application composition root.

This module selects concrete technical adapters and wires them into a typed
container. It intentionally contains no business rules or HTTP handling.
"""

from __future__ import annotations

from app.core.config import ConfigurationError, Settings
from app.core.container import Container
from app.core.database import Database
from app.core.integrations.fake_email import FakeEmailSender
from app.core.integrations.fake_payment import FakePaymentGateway
from app.core.integrations.fake_sms import FakeSmsSender
from app.core.integrations.kavenegar_sms import KavenegarSmsSender
from app.core.integrations.smtp_email import SmtpEmailSender
from app.core.redis_store import RedisStore


def bootstrap(settings: Settings) -> Container:
    """Build the dependency graph for one Flask application instance."""

    if settings.sms_provider not in {"fake", "kavenegar"}:
        raise ConfigurationError(f"Unknown SMS provider '{settings.sms_provider}'.")
    if settings.payment_provider != "fake":
        raise ConfigurationError(
            f"Payment provider '{settings.payment_provider}' is not implemented yet."
        )
    if settings.email_provider not in {"fake", "smtp"}:
        raise ConfigurationError(f"Unknown email provider '{settings.email_provider}'.")
    if settings.email_provider == "smtp" and not (settings.smtp_username and settings.smtp_password):
        raise ConfigurationError("SMTP_USERNAME and SMTP_PASSWORD are required for SMTP email.")
    if settings.sms_provider == "kavenegar" and not settings.kavenegar_api_key:
        raise ConfigurationError("KAVENEGAR_API_KEY is required for Kavenegar SMS.")

    return Container(
        settings=settings,
        database=Database(settings.database_url),
        redis=RedisStore(settings.redis_url, settings.redis_namespace),
        # The fake provider may expose OTPs only during local development.
        # Tests and production-like environments keep message contents out of logs.
        sms_sender=(KavenegarSmsSender(api_key=settings.kavenegar_api_key,
            sender=settings.kavenegar_sender, login_template=settings.kavenegar_login_template)
            if settings.sms_provider == "kavenegar" else FakeSmsSender(
                log_messages=settings.debug or settings.environment == "development")),
        email_sender=(SmtpEmailSender(host=settings.smtp_host, port=settings.smtp_port,
            username=settings.smtp_username, password=settings.smtp_password,
            sender=settings.email_from) if settings.email_provider == "smtp" else FakeEmailSender(
                log_messages=settings.debug or settings.environment == "development")),
        payment_gateway=FakePaymentGateway(),
    )
