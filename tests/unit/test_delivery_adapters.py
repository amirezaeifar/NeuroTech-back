from app.core.integrations.kavenegar_sms import KavenegarSmsSender
from app.core.integrations.smtp_email import SmtpEmailSender


def test_smtp_sender_uses_authenticated_tls(monkeypatch):
    sent = []

    class Smtp:
        def __init__(self, host, port, timeout):
            assert (host, port, timeout) == ("smtp.gmail.com", 587, 15)

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def starttls(self):
            sent.append("tls")

        def login(self, username, password):
            assert (username, password) == ("neuro.tech.pishro@gmail.com", "app-password")

        def send_message(self, message):
            sent.append(message)

    monkeypatch.setattr("smtplib.SMTP", Smtp)
    sender = SmtpEmailSender(host="smtp.gmail.com", port=587,
        username="neuro.tech.pishro@gmail.com", password="app-password",
        sender="neuro.tech.pishro@gmail.com")
    message_id = sender.send("member@example.com", "Verify", "A link")
    assert sent[0] == "tls"
    assert sent[1]["To"] == "member@example.com"
    assert sent[1].get_content().strip() == "A link"
    assert message_id == sent[1]["Message-ID"]


def test_kavenegar_sender_uses_login_template_and_sender(monkeypatch):
    calls = []

    class Api:
        def verify_lookup(self, params):
            calls.append(("verify", params))
            return [{"messageid": 42}]

        def sms_send(self, params):
            calls.append(("send", params))
            return [{"messageid": 43}]

    monkeypatch.setattr("kavenegar.KavenegarAPI", lambda key: Api() if key == "secret" else None)
    sender = KavenegarSmsSender(api_key="secret", sender="20006535",
        login_template="surgitrack-login")
    assert sender.send_verification("+989121234567", "123456") == "42"
    assert calls[0][1] == {"receptor": "+989121234567",
        "template": "surgitrack-login", "token": "123456", "type": "sms"}
    assert sender.send("+989121234567", "Ticket updated") == "43"
    assert calls[1][1]["sender"] == "20006535"
