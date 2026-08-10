"""Framework-independent ports implemented by technical adapters."""

from __future__ import annotations

from typing import Protocol


class SmsSender(Protocol):
    """Send a text message and return the provider message identifier."""

    def send(self, recipient: str, message: str) -> str: ...


class PaymentGateway(Protocol):
    """Create a payment request and return the redirect URL."""

    def create_payment(
        self,
        *,
        reference: str,
        amount_minor: int,
        currency: str,
        callback_url: str,
    ) -> str: ...
