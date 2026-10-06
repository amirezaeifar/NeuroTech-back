from __future__ import annotations

from urllib.parse import urlparse
from uuid import UUID

from app.services.academy import academy_service_from_container
from app.services.seed import seed_academy


def _authenticated_client(client, app):  # type: ignore[no-untyped-def]
    client.post(
        "/api/v1/auth/register/password",
        json={
            "display_name": "Academy Member",
            "email": "academy@example.com",
            "password": "secure-pass-123",
        },
    )
    token = (
        app.extensions["container"].email_sender.sent_messages[-1].body.split("verify_email=", 1)[1].splitlines()[0]
    )
    client.post("/api/v1/auth/email/verify", json={"token": token})
    client.post(
        "/api/v1/auth/login/password",
        json={"email": "academy@example.com", "password": "secure-pass-123"},
    )
    headers = {"X-CSRF-TOKEN": client.get_cookie("csrf_access_token").value}
    profile = client.put(
        "/api/v1/me/profile",
        json={
            "full_name": "Academy Member",
            "email": "academy@example.com",
            "phone": "+989121234567",
            "address": "12 Neural Avenue",
        },
        headers=headers,
    )
    assert profile.status_code == 200
    saved_profile = client.get("/api/v1/me/profile")
    assert saved_profile.status_code == 200
    assert saved_profile.get_json()["data"]["address"] == "12 Neural Avenue"
    # Response-only metadata such as ``complete`` must not turn a retry from a
    # stale/open checkout tab into an unknown-field 422.
    retried_profile = client.put(
        "/api/v1/me/profile",
        json=saved_profile.get_json()["data"],
        headers=headers,
    )
    assert retried_profile.status_code == 200
    return headers


def test_free_enrollment_progress_and_pending_comment_are_idempotent(client, app) -> None:  # type: ignore[no-untyped-def]
    seed_academy(app.extensions["container"])
    headers = _authenticated_client(client, app)

    first = client.post("/api/v1/courses/clinical-neurology/enroll", headers=headers)
    second = client.post("/api/v1/courses/clinical-neurology/enroll", headers=headers)
    assert first.status_code == 201
    assert second.get_json()["data"]["id"] == first.get_json()["data"]["id"]

    detail = client.get("/api/v1/courses/clinical-neurology").get_json()["data"]
    lesson_id = detail["sections"][0]["lessons"][0]["id"]
    progress_url = f"/api/v1/me/lessons/{lesson_id}/progress"
    assert (
        client.put(
            progress_url,
            json={"position_seconds": 42, "completed": False},
            headers=headers,
        ).status_code
        == 200
    )
    completed = client.put(
        progress_url,
        json={"position_seconds": 1200, "completed": True},
        headers=headers,
    )
    assert completed.get_json()["data"]["completed"] is True
    access = client.get("/api/v1/courses/clinical-neurology/access?locale=en").get_json()["data"]
    assert access["completed_lessons"] == 1
    assert access["lessons"][0] == {
        "id": lesson_id,
        "title": "Orientation",
        "video_provider": "youtube",
        "video_reference": "M7lc1UVf-VE",
        "duration_seconds": 1200,
        "position_seconds": 1200,
        "completed": True,
    }
    pathway = client.get("/api/v1/me/pathway?locale=en").get_json()["data"]
    assert pathway["user"] == "Academy Member"
    assert pathway["courses"][0]["slug"] == "clinical-neurology"
    assert pathway["courses"][0]["modules"][0]["status"] == "completed"

    comment = client.post(
        "/api/v1/courses/clinical-neurology/comments",
        json={"body": "A useful clinical course."},
        headers=headers,
    )
    assert comment.status_code == 201
    assert comment.get_json()["data"]["status"] == "pending"
    assert client.get("/api/v1/courses/clinical-neurology/comments").get_json()["data"] == []

    academy_service_from_container(app.extensions["container"]).archive(UUID(detail["id"]))
    assert client.get("/api/v1/courses/clinical-neurology/access").status_code == 404
    assert client.get("/api/v1/courses/clinical-neurology/comments").get_json()["data"] == []
    remaining = client.get("/api/v1/me/pathway").get_json()["data"]["courses"]
    assert all(course["slug"] != "clinical-neurology" for course in remaining)
    assert all(course["modules"] == [] for course in remaining)
    assert (
        client.put(
            progress_url,
            json={"position_seconds": 100, "completed": False},
            headers=headers,
        ).status_code
        == 404
    )


def test_fake_payment_callback_is_idempotent_and_grants_access(client, app) -> None:  # type: ignore[no-untyped-def]
    seed_academy(app.extensions["container"])
    headers = _authenticated_client(client, app)
    order = client.post(
        "/api/v1/orders",
        json={"course_slug": "neuroimaging", "currency": "USD"},
        headers=headers,
    )
    assert order.status_code == 201
    payload = order.get_json()["data"]
    assert payload["total_minor"] == 14_900
    attempt_id = urlparse(payload["payment_url"]).path.rsplit("/", 1)[-1]
    callback = f"/api/v1/payments/fake/{attempt_id}/callback"

    first = client.post(callback, json={"result": "success"})
    second = client.post(callback, json={"result": "success"})
    assert first.status_code == second.status_code == 200
    assert second.get_json()["data"]["status"] == "paid"

    access = client.get("/api/v1/courses/neuroimaging/access")
    assert access.get_json()["data"]["slug"] == "neuroimaging"
    assert access.get_json()["data"]["enrolled"] is True
    assert access.get_json()["data"]["entitled"] is True
    assert access.get_json()["data"]["can_access"] is True


def test_lessons_unlock_in_order_at_ninety_percent(client, app) -> None:  # type: ignore[no-untyped-def]
    seed_academy(app.extensions["container"])
    headers = _authenticated_client(client, app)
    client.post("/api/v1/courses/clinical-neurology/enroll", headers=headers)
    detail = client.get("/api/v1/courses/clinical-neurology").get_json()["data"]
    lessons = [lesson for section in detail["sections"] for lesson in section["lessons"]]
    first, second = lessons[:2]

    blocked = client.put(
        f"/api/v1/me/lessons/{second['id']}/progress",
        json={"position_seconds": 10, "completed": True},
        headers=headers,
    )
    assert blocked.status_code == 403

    almost = client.put(
        f"/api/v1/me/lessons/{first['id']}/progress",
        json={"position_seconds": 1079, "completed": True},
        headers=headers,
    )
    assert almost.get_json()["data"]["completed"] is False
    access = client.get(
        "/api/v1/courses/clinical-neurology/access", headers=headers
    ).get_json()["data"]
    assert access["lessons"][1]["locked"] is True
    assert access["lessons"][1]["video_reference"] is None

    threshold = client.put(
        f"/api/v1/me/lessons/{first['id']}/progress",
        json={"position_seconds": 1080, "completed": False},
        headers=headers,
    )
    assert threshold.get_json()["data"]["completed"] is True
    access = client.get(
        "/api/v1/courses/clinical-neurology/access", headers=headers
    ).get_json()["data"]
    assert "locked" not in access["lessons"][1]
    assert access["lessons"][1]["video_reference"]
