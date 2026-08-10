"""Typed dependency container populated by the application bootstrap."""

from __future__ import annotations

from dataclasses import dataclass

from app.core.config import Settings
from app.domain.ports import PaymentGateway, SmsSender


@dataclass(frozen=True, slots=True)
class Container:
    settings: Settings
    sms_sender: SmsSender
    payment_gateway: PaymentGateway
