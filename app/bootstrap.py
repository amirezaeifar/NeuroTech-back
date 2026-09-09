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
from app.core.redis_store import RedisStore


def bootstrap(settings: Settings) -> Container:
    """Build the dependency graph for one Flask application instance."""

    if settings.sms_provider != "fake":
        raise ConfigurationError(f"SMS provider '{settings.sms_provider}' is not implemented yet.")
    if settings.payment_provider != "fake":
        raise ConfigurationError(
            f"Payment provider '{settings.payment_provider}' is not implemented yet."
        )
    if settings.email_provider != "fake":
        raise ConfigurationError(
            f"Email provider '{settings.email_provider}' is not implemented yet."
        )

    return Container(
        settings=settings,
        database=Database(settings.database_url),
        redis=RedisStore(settings.redis_url, settings.redis_namespace),
        sms_sender=FakeSmsSender(),
        email_sender=FakeEmailSender(),
        payment_gateway=FakePaymentGateway(),
    )
