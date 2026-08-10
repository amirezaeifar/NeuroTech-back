"""Application composition root.

This module selects concrete technical adapters and wires them into a typed
container. It intentionally contains no business rules or HTTP handling.
"""

from __future__ import annotations

from app.core.config import ConfigurationError, Settings
from app.core.container import Container
from app.core.integrations.fake_payment import FakePaymentGateway
from app.core.integrations.fake_sms import FakeSmsSender


def bootstrap(settings: Settings) -> Container:
    """Build the dependency graph for one Flask application instance."""

    if settings.sms_provider != "fake":
        raise ConfigurationError(f"SMS provider '{settings.sms_provider}' is not implemented yet.")
    if settings.payment_provider != "fake":
        raise ConfigurationError(
            f"Payment provider '{settings.payment_provider}' is not implemented yet."
        )

    return Container(
        settings=settings,
        sms_sender=FakeSmsSender(),
        payment_gateway=FakePaymentGateway(),
    )
