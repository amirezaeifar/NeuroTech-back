"""Kavenegar SMS and verification-template delivery."""

from __future__ import annotations


class KavenegarSmsSender:
    def __init__(self, *, api_key: str, sender: str, login_template: str) -> None:
        from kavenegar import KavenegarAPI

        self.api = KavenegarAPI(api_key)
        self.sender = sender
        self.login_template = login_template

    @staticmethod
    def _message_id(response: object) -> str:
        entries = response if isinstance(response, list) else [response]
        first = entries[0] if entries else {}
        return str(first.get("messageid", "")) if isinstance(first, dict) else ""

    def send(self, recipient: str, message: str) -> str:
        return self._message_id(self.api.sms_send({
            "sender": self.sender, "receptor": recipient, "message": message,
        }))

    def send_verification(self, recipient: str, code: str) -> str:
        return self._message_id(self.api.verify_lookup({
            "receptor": recipient, "template": self.login_template,
            "token": code, "type": "sms",
        }))
