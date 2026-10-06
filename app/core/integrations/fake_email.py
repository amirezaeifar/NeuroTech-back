"""In-memory email adapter for development and tests."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from uuid import uuid4


@dataclass(frozen=True, slots=True)
class SentEmail:
    message_id: str
    recipient: str
    subject: str
    body: str


class FakeEmailSender:
    def __init__(self, *, log_messages: bool = False) -> None:
        self.sent_messages: list[SentEmail] = []
        self.log_messages = log_messages

    def send(self, recipient: str, subject: str, body: str) -> str:
        message_id = f"fake-email-{uuid4()}"
        self.sent_messages.append(SentEmail(message_id, recipient, subject, body))
        if self.log_messages:
            logging.warning(
                "DEVELOPMENT EMAIL to %s | subject=%s | body=%s",
                recipient,
                subject,
                body,
            )
        return message_id
