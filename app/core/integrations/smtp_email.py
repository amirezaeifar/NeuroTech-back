"""SMTP email delivery with a bounded network timeout."""

from __future__ import annotations

import smtplib
from email.message import EmailMessage
from email.utils import make_msgid


class SmtpEmailSender:
    def __init__(self, *, host: str, port: int, username: str, password: str, sender: str) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.sender = sender

    def send(self, recipient: str, subject: str, body: str) -> str:
        message = EmailMessage()
        message["From"] = self.sender
        message["To"] = recipient
        message["Subject"] = subject
        message["Message-ID"] = make_msgid(domain=self.sender.split("@")[-1])
        message.set_content(body)
        if self.port == 465:
            with smtplib.SMTP_SSL(self.host, self.port, timeout=15) as smtp:
                smtp.login(self.username, self.password)
                smtp.send_message(message)
        else:
            with smtplib.SMTP(self.host, self.port, timeout=15) as smtp:
                smtp.starttls()
                smtp.login(self.username, self.password)
                smtp.send_message(message)
        return str(message["Message-ID"])
