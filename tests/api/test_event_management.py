"""Exercise real event content, capacity and host/attendee boundaries."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.models import Base
from app.core.auth_models import EmailIdentity, User
from app.core.integrations.fake_email import FakeEmailSender
from app.core.unit_of_work import SqlAlchemyUnitOfWork
from app.domain.errors import ConflictError
from app.services.events import EventService
from tests.api.test_catalog_events_files import _event_payload
from tests.api.test_content_management import _admin
from tests.api.test_content_management import _partner_translations
from tests.api.test_governance import _staff


def confirm_latest(client, app):
    message = app.extensions["container"].email_sender.sent_messages[-1]
    token = message.body.split("token=", 1)[1].splitlines()[0]
    return client.post("/api/v1/events/reservations/confirm", json={"token": token})


def test_unlinked_site_partner_can_speak_and_link_to_profile(client, app):
    headers = _admin(client, app)
    partner = client.post("/api/v1/admin/partners", headers=headers,
        json={"translations": _partner_translations()}).json["data"]
    assert client.post(f"/api/v1/admin/partners/{partner['id']}/publish",
        headers=headers).status_code == 200
    options = client.get("/api/v1/admin/events/speakers?q=Dr%20Example",
        headers=headers).json["data"]
    assert any(item["partner_id"] == partner["id"] for item in options)
    event = create_event(client, headers, speakers=[{
        "partner_id": partner["id"], "role_label": "Faculty", "position": 1,
    }])
    speaker = client.get(f"/api/v1/events/{event['slug']}?locale=en").json["data"]["speakers"][0]
    assert speaker["name"] == "Dr Example"
    assert speaker["profile_slug"] == partner["slug"]


def create_event(client, headers, **changes):
    payload = _event_payload()
    payload.update(changes)
    response = client.post("/api/v1/admin/events", headers=headers, json=payload)
    assert response.status_code == 201, response.json
    event = response.json["data"]
    assert (
        client.post(f"/api/v1/admin/events/{event['id']}/publish", headers=headers).status_code
        == 200
    )
    return event


def test_bilingual_archive_content_and_validation(client, app):
    headers = _admin(client, app)
    translations = _event_payload()["translations"]
    for translation in translations:
        translation["content"] = {
            "gallery": [
                {"name": translation["locale"] + " photo", "url": "https://example.com/photo.jpg"}
            ],
            "documents": [
                {
                    "name": "Slides",
                    "url": "https://example.com/slides.pdf",
                    "type": "PDF",
                    "size": "1 MB",
                }
            ],
            "videos": [{"name": "Recording", "url": "https://example.com/recording.mp4"}],
            "agenda": [{"time": "10:00", "title": "Introduction", "detail": "Details"}],
            "faq": [{"q": "Question", "a": "Answer"}],
            "closing_note": "Thank you",
        }
    event = create_event(
        client, headers, status="completed", translations=translations, online_url=None
    )
    for locale in ("fa", "en"):
        content = client.get(f"/api/v1/events/{event['slug']}?locale={locale}").json["data"][
            "content"
        ]
        assert content["gallery"][0]["name"] == locale + " photo"
        assert content["videos"][0]["url"].endswith(".mp4")
        assert content["faq"][0]["a"] == "Answer"
    only_english = [dict(item) for item in translations]
    only_english[1]["content"] = {}
    assert client.patch(
        f"/api/v1/admin/events/{event['id']}",
        headers=headers,
        json={"translations": only_english},
    ).status_code == 200
    fallback = client.get(f"/api/v1/events/{event['slug']}?locale=fa").json["data"]["content"]
    assert fallback["gallery"] and fallback["documents"]
    translations[0]["content"]["gallery"][0]["url"] = "javascript:alert(1)"
    assert (
        client.patch(
            f"/api/v1/admin/events/{event['id']}",
            headers=headers,
            json={"translations": translations},
        ).status_code
        == 422
    )
    assert (
        client.get("/api/v1/events/brain-health-day?locale=en")
        .json["data"]["content"]["gallery"][0]["url"]
        .startswith("https://")
    )


def test_reservation_auth_capacity_idempotence_cancellation_and_expiry(client, app):
    headers = _admin(client, app)
    event = create_event(client, headers)
    guest = app.test_client()
    base = f"/api/v1/events/{event['slug']}"
    assert guest.post(base + "/reservations").status_code == 401
    viewer = app.test_client()
    viewer_headers = _staff(viewer, app, "user")
    assert viewer.post(base + "/reservations", headers=viewer_headers).status_code == 202
    assert viewer.get(base + "/reservations/me").json["data"] is None
    assert viewer.get(base + "/live").status_code == 403
    assert confirm_latest(viewer, app).status_code == 200
    assert viewer.post(base + "/reservations", headers=viewer_headers).status_code == 200
    assert client.get(base).json["data"]["remaining"] == 0
    assert viewer.get(base + "/reservations/me").json["data"]["status"] == "confirmed"
    assert client.post(base + "/reservations", headers=headers).status_code == 409
    people = client.get(f"/api/v1/admin/events/{event['id']}/reservations").json["data"]
    assert len(people) == 1
    assert viewer.get(f"/api/v1/admin/events/{event['id']}/reservations").status_code == 403
    assert (
        client.delete(
            f"/api/v1/admin/events/{event['id']}/reservations/{people[0]['user_id']}",
            headers=headers,
        ).status_code
        == 204
    )
    assert viewer.get(base + "/live").status_code == 403
    assert client.get(base).json["data"]["remaining"] == 1
    assert (
        client.patch(
            f"/api/v1/admin/events/{event['id']}", headers=headers, json={"capacity": 2}
        ).status_code
        == 200
    )
    assert viewer.post(base + "/reservations", headers=viewer_headers).status_code == 202
    assert confirm_latest(viewer, app).status_code == 200
    assert client.post(base + "/reservations", headers=headers).status_code == 202
    assert confirm_latest(client, app).status_code == 200
    assert (
        client.patch(
            f"/api/v1/admin/events/{event['id']}", headers=headers, json={"capacity": 1}
        ).status_code
        == 409
    )
    expired = create_event(
        client,
        headers,
        slug="expired-event",
        starts_at=(datetime.now(UTC) - timedelta(days=2)).isoformat(),
        ends_at=(datetime.now(UTC) - timedelta(days=1)).isoformat(),
    )
    assert (
        viewer.post(
            f"/api/v1/events/{expired['slug']}/reservations", headers=viewer_headers
        ).status_code
        == 409
    )


def test_live_lifecycle_moderation_and_closed_controls(client, app):
    headers = _admin(client, app)
    event = create_event(client, headers, capacity=10, agenda_steps=["Intro", "Demo", "Questions"])
    base = f"/api/v1/events/{event['slug']}/live"
    viewer = app.test_client()
    viewer_headers = _staff(viewer, app, "user")
    assert viewer.post(f"/api/v1/events/{event['slug']}/reservations", headers=viewer_headers).status_code == 202
    assert confirm_latest(viewer, app).status_code == 200
    assert (
        viewer.patch(base + "/control", headers=viewer_headers, json={"status": "live"}).status_code
        == 403
    )
    assert (
        viewer.post(
            base + "/messages", headers=viewer_headers, json={"body": "Too early"}
        ).status_code
        == 409
    )
    assert (
        client.patch(base + "/control", headers=headers, json={"status": "live"}).status_code == 200
    )
    assert viewer.get(base).json["data"]["event"]["online_url"] == event["online_url"]
    started = viewer.get(base).json["data"]["event"]
    assert started["live_started_at"] and started["step_started_at"]
    assert started["step_durations"] == [0, 0, 0]
    assert client.get(f"/api/v1/events/{event['slug']}").json["data"]["online_url"] is None
    message = viewer.post(base + "/messages", headers=viewer_headers, json={"body": "Hello"}).json[
        "data"
    ]["id"]
    question = viewer.post(base + "/questions", headers=viewer_headers, json={"body": "Why?"}).json[
        "data"
    ]["id"]
    assert (
        viewer.post(base + f"/questions/{question}/vote", headers=viewer_headers).status_code == 200
    )
    assert viewer.delete(base + f"/messages/{message}", headers=viewer_headers).status_code == 403
    assert client.delete(base + f"/messages/{message}", headers=headers).status_code == 204
    assert client.delete(base + f"/questions/{question}", headers=headers).status_code == 204
    assert viewer.get(base).json["data"]["question_count"] == 0
    assert client.post(base + "/step", headers=headers, json={"step": 2}).status_code == 200
    stepped = viewer.get(base).json["data"]["event"]
    assert stepped["step_started_at"] and len(stepped["step_durations"]) == 3
    assert (
        client.patch(
            f"/api/v1/admin/events/{event['id']}",
            headers=headers,
            json={"agenda_steps": ["Only step"]},
        ).status_code
        == 200
    )
    assert viewer.get(base).json["data"]["event"]["current_step"] == 0
    assert (
        client.patch(
            base + "/control",
            headers=headers,
            json={"chat_enabled": False, "questions_enabled": False},
        ).status_code
        == 200
    )
    assert (
        viewer.post(
            base + "/messages", headers=viewer_headers, json={"body": "Blocked"}
        ).status_code
        == 409
    )
    assert (
        viewer.post(
            base + "/questions", headers=viewer_headers, json={"body": "Blocked"}
        ).status_code
        == 409
    )
    assert (
        client.patch(base + "/control", headers=headers, json={"status": "completed"}).status_code
        == 200
    )
    snapshot = viewer.get(base).json["data"]
    assert snapshot["viewer_count"] == 0 and snapshot["event"]["online_url"] is None
    assert snapshot["event"]["step_started_at"] is None
    assert snapshot["event"]["live_started_at"] == started["live_started_at"]
    assert client.post(base + "/step", headers=headers, json={"step": 0}).status_code == 409
    assert (
        client.patch(base + "/control", headers=headers, json={"status": "live"}).status_code == 409
    )


def test_simultaneous_last_seat_reservations_are_serialized(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'concurrent.db'}")
    Base.metadata.create_all(engine)
    sender = FakeEmailSender()
    service = EventService(
        lambda: SqlAlchemyUnitOfWork(sessionmaker(bind=engine, expire_on_commit=False)),
        sender, "test-secret", "https://example.com",
    )
    with sessionmaker(bind=engine)() as session:
        for number in (1, 2):
            user = User(id=UUID(int=number), display_name=f"User {number}", status="active")
            user.emails.append(EmailIdentity(email=f"user{number}@example.com", verified_at=datetime.now(UTC)))
            session.add(user)
        session.commit()
    data = _event_payload()
    data["starts_at"] = datetime.now(UTC) + timedelta(days=1)
    data["ends_at"] = datetime.now(UTC) + timedelta(days=2)
    event = service.create(data)
    service.publish(UUID(event["id"]), True)

    tokens = []
    for number in (1, 2):
        assert service.reserve(UUID(int=number), event["slug"])["status"] == "pending_email"
        tokens.append(sender.sent_messages[-1].body.split("token=", 1)[1].splitlines()[0])
    assert service.detail(event["slug"], "en")["remaining"] == 1

    def reserve(token):
        try:
            return service.confirm_reservation(token)["status"]
        except ConflictError:
            return "full"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(reserve, tokens))
    assert sorted(results) == ["confirmed", "full"]
    assert service.detail(event["slug"], "en")["remaining"] == 0
    engine.dispose()
