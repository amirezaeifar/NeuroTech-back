"""Typed dependency container populated by the application bootstrap."""

from __future__ import annotations

from dataclasses import dataclass

from app.core.config import Settings
from app.core.database import Database
from app.core.redis_store import RedisStore
from app.domain.ports import EmailSender, PaymentGateway, SmsSender


@dataclass(frozen=True, slots=True)
class Container:
    settings: Settings
    database: Database
    redis: RedisStore
    sms_sender: SmsSender
    email_sender: EmailSender
    payment_gateway: PaymentGateway
