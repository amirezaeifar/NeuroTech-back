from uuid import uuid4

from tests.api.test_content_management import _admin


def request_data(**overrides):
    return {
        "name": "Guest",
        "phone": "09121234567",
        "email": None,
        "subject": "Product support",
        "message": "Please help with installation.",
        "category": "technical",
        "locale": "fa",
        **overrides,
    }


def test_guest_ticket_persists_and_admin_replies(client, app):
    response = client.post("/api/v1/tickets", json=request_data())
    assert response.status_code == 201
    ticket = response.json["data"]
    assert ticket["phone"] == "+989121234567"
    assert ticket["category"] == "technical"
    assert ticket["history"][0]["notification"] == "mock"
    container = app.extensions["container"]
    assert len(container.sms_sender.sent_messages) == 1
    track = f"/api/v1/tickets/track/{ticket['tracking_token']}"
    guest = client.get(track).json["data"]
    assert "phone" not in guest and "tracking_token" not in guest
    assert "actor_id" not in guest["history"][0]
    assert client.get("/api/v1/admin/tickets").status_code == 401
    assert client.get(f"/api/v1/tickets/track/{ticket['id']}").status_code == 404
    headers = _admin(client, app)
    url = f"/api/v1/admin/tickets/{ticket['id']}"
    found = client.get("/api/v1/admin/tickets?q=Guest&status=submitted").json
    assert found["meta"]["total"] == 1
    assert found["data"][0]["created_at"].endswith("+00:00")
    assert client.get("/api/v1/admin/tickets?category=technical").json["meta"]["total"] == 1
    assert client.get(url).json["data"]["message"] == request_data()["message"]
    progress = client.patch(
        url, headers=headers, json={"status": "in_progress", "version": ticket["version"]}
    )
    assert progress.status_code == 200
    assert len(container.sms_sender.sent_messages) == 2
    stale = client.patch(
        url,
        headers=headers,
        json={"status": "resolved", "version": ticket["version"], "reply": "Old"},
    )
    assert stale.status_code == 409
    current = progress.json["data"]
    resolved = client.patch(
        url,
        headers=headers,
        json={
            "status": "resolved",
            "version": current["version"],
            "reply": "Installation completed.",
        },
    )
    assert resolved.status_code == 200
    assert client.get(track).json["data"]["history"][-1]["reply"] == "Installation completed."
    assert len(container.sms_sender.sent_messages) == 3
    same = resolved.json["data"]
    assert (
        client.patch(
            url, headers=headers, json={"status": "resolved", "version": same["version"]}
        ).status_code
        == 200
    )
    assert len(container.sms_sender.sent_messages) == 3
    assert client.get("/api/v1/admin/tickets?status=submitted").json["meta"]["total"] == 0


def test_ticket_validation_and_sms_failure(client, app, monkeypatch):
    assert client.post("/api/v1/tickets", json=request_data(phone="12345678")).status_code == 422
    assert client.post("/api/v1/tickets", json=request_data(subject="  ")).status_code == 422

    def broken(*args):
        raise RuntimeError("Offline")

    monkeypatch.setattr(app.extensions["container"].sms_sender, "send", broken)
    created = client.post("/api/v1/tickets", json=request_data(locale="en"))
    assert created.status_code == 201
    ticket = created.json["data"]
    assert ticket["history"][0]["notification"] == "failed"
    headers = _admin(client, app)
    url = f"/api/v1/admin/tickets/{ticket['id']}"
    assert (
        client.patch(
            url, headers=headers, json={"status": "rejected", "version": ticket["version"]}
        ).status_code
        == 200
    )
    assert client.get("/api/v1/admin/tickets?status=closed").json["meta"]["total"] == 1
    assert client.get("/api/v1/admin/tickets?page_size=101").status_code == 422
    assert client.get(f"/api/v1/admin/tickets/{uuid4()}").status_code == 404
    assert (
        client.patch(
            f"/api/v1/admin/tickets/{uuid4()}",
            headers=headers,
            json={"status": "resolved", "version": 1},
        ).status_code
        == 404
    )


def test_partner_seed_is_repeatable_and_preserves_edits(app):
    from sqlalchemy import select

    from app.core.content_models import PartnerProfile
    from app.services.seed_partners import seed_partners

    container = app.extensions["container"]
    assert seed_partners(container) == 4
    with container.database.session() as session:
        partner = session.scalar(select(PartnerProfile).where(PartnerProfile.slug == "partner-1"))
        partner.translations[0].name = "Edited name"
        session.commit()
    assert seed_partners(container) == 0
    with container.database.session() as session:
        partner = session.scalar(select(PartnerProfile).where(PartnerProfile.slug == "partner-1"))
        assert partner.translations[0].name == "Edited name"


def test_specialist_cannot_read_or_reply_to_tickets(client, app):
    from flask_jwt_extended import create_access_token, decode_token

    _admin(client, app)
    with app.app_context():
        original = decode_token(client.get_cookie("access_token_cookie").value)
        token = create_access_token(
            identity=original["sub"],
            additional_claims={"sid": original["sid"], "role": "specialist"},
        )
        csrf = decode_token(token)["csrf"]
    client.set_cookie("access_token_cookie", token, domain="localhost")
    assert client.get("/api/v1/admin/tickets").status_code == 403
    assert client.get(f"/api/v1/admin/tickets/{uuid4()}").status_code == 403
    assert (
        client.patch(
            f"/api/v1/admin/tickets/{uuid4()}",
            headers={"X-CSRF-TOKEN": csrf},
            json={"status": "resolved", "version": 1},
        ).status_code
        == 403
    )


def test_open_ticket_filter_excludes_completed_and_paginates(client, app):
    tickets = [
        client.post("/api/v1/tickets", json=request_data(subject=f"Request {i}")).json["data"]
        for i in range(3)
    ]
    headers = _admin(client, app)
    for ticket, status in zip(tickets[1:], ["in_progress", "resolved"], strict=True):
        response = client.patch(
            f"/api/v1/admin/tickets/{ticket['id']}",
            headers=headers,
            json={"status": status, "reply": "Response", "version": ticket["version"]},
        )
        assert response.status_code == 200
    result = client.get("/api/v1/admin/tickets?status=open&page_size=1").json
    assert result["meta"]["total"] == 2
    assert len(result["data"]) == 1
    second = client.get("/api/v1/admin/tickets?status=open&page_size=1&page=2").json
    assert second["data"][0]["id"] != result["data"][0]["id"]
    assert {result["data"][0]["status"], second["data"][0]["status"]} == {
        "submitted",
        "in_progress",
    }
    assert client.get("/api/v1/admin/tickets?status=resolved").json["meta"]["total"] == 1
    assert client.get("/api/v1/admin/tickets?status=open&q=Request%202").json["meta"]["total"] == 0
    assert client.get("/api/v1/admin/tickets?status=closed").json["meta"]["total"] == 1
