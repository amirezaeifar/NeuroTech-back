"""In-memory payment adapter for development and tests."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote


@dataclass(frozen=True, slots=True)
class CreatedPayment:
    payment_id: str
    reference: str
    amount_minor: int
    currency: str
    callback_url: str


class FakePaymentGateway:
    """Record payment requests and return a deterministic fake URL scheme."""

    def __init__(self) -> None:
        self.created_payments: list[CreatedPayment] = []

    def create_payment(
        self,
        *,
        reference: str,
        amount_minor: int,
        currency: str,
        callback_url: str,
    ) -> str:
        payment_id = reference
        self.created_payments.append(
            CreatedPayment(
                payment_id=payment_id,
                reference=reference,
                amount_minor=amount_minor,
                currency=currency,
                callback_url=callback_url,
            )
        )
        return f"{callback_url.rstrip('/')}/{quote(payment_id)}"
