"""In-memory SMS adapter for development and tests."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4


@dataclass(frozen=True, slots=True)
class SentSms:
    message_id: str
    recipient: str
    message: str


class FakeSmsSender:
    """Record outgoing messages without contacting a real SMS provider."""

    def __init__(self) -> None:
        self.sent_messages: list[SentSms] = []

    def send(self, recipient: str, message: str) -> str:
        message_id = f"fake-sms-{uuid4()}"
        self.sent_messages.append(
            SentSms(message_id=message_id, recipient=recipient, message=message)
        )
        return message_id
