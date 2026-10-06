"""In-memory SMS adapter for development and tests."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from uuid import uuid4


@dataclass(frozen=True, slots=True)
class SentSms:
    message_id: str
    recipient: str
    message: str


class FakeSmsSender:
    """Record outgoing messages without contacting a real SMS provider."""

    def __init__(self, *, log_messages: bool = False) -> None:
        self.sent_messages: list[SentSms] = []
        self.log_messages = log_messages

    def send(self, recipient: str, message: str) -> str:
        message_id = f"fake-sms-{uuid4()}"
        self.sent_messages.append(
            SentSms(message_id=message_id, recipient=recipient, message=message)
        )
        if self.log_messages:
            logging.warning("DEVELOPMENT SMS to %s: %s", recipient, message)
        return message_id
