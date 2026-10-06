from __future__ import annotations

from sqlalchemy import delete

from app.core.learning_models import Enrollment
from app.services.auth import auth_service_from_container
from app.services.seed import seed_academy


def _login(client, email: str, password: str = "secure-pass-123") -> dict[str, str]:  # type: ignore[no-untyped-def]
    response = client.post(
        "/api/v1/auth/login/password", json={"email": email, "password": password}
    )
    assert response.status_code == 200
    return {"X-CSRF-TOKEN": client.get_cookie("csrf_access_token").value}


def _admin(client, app) -> dict[str, str]:  # type: ignore[no-untyped-def]
    auth_service_from_container(app.extensions["container"]).bootstrap_admin(
        "Principal Admin", "admin@example.com", "secure-pass-123"
    )
    return _login(client, "admin@example.com")


def test_admin_invitation_profile_and_logout_all(client, app) -> None:  # type: ignore[no-untyped-def]
    headers = _admin(client, app)
    service = auth_service_from_container(app.extensions["container"])
    service.register_password(
        display_name="Existing Member",
        email="member-to-promote@example.com",
        password="secure-pass-123",
    )

    promoted = client.post(
        "/api/v1/admin/invitations",
        json={"email": "member-to-promote@example.com", "role": "specialist"},
        headers=headers,
    )
    assert promoted.status_code == 200
    assert promoted.get_json()["data"]["outcome"] == "access_updated"
    assert promoted.get_json()["data"]["user"]["role"] == "specialist"

    users = client.get("/api/v1/admin/users").get_json()["data"]
    admin = next(user for user in users if user["email"] == "admin@example.com")
    assert admin["role"] == "super_admin"
    updated = client.patch("/api/v1/me", json={"display_name": "Updated Admin"}, headers=headers)
    assert updated.get_json()["data"]["user"]["display_name"] == "Updated Admin"

    invited = client.post(
        "/api/v1/admin/invitations",
        json={"email": "doctor@example.com", "role": "specialist"},
        headers=headers,
    )
    assert invited.status_code == 202
    assert invited.get_json()["data"]["outcome"] == "invitation_sent"
    assert (
        app.extensions["container"]
        .email_sender.sent_messages[-1]
        .body.startswith("Invitation link: http://127.0.0.1:5173/#/login?")
    )
    token = (
        app.extensions["container"].email_sender.sent_messages[-1].body.split("invitation=", 1)[1]
    )
    accepted = client.post(
        "/api/v1/auth/invitations/accept",
        json={
            "token": token,
            "display_name": "Invited Doctor",
            "password": "doctor-pass-123",
        },
    )
    assert accepted.status_code == 201
    assert accepted.get_json()["data"]["user"]["role"] == "specialist"
    assert (
        client.post(
            "/api/v1/auth/invitations/accept",
            json={
                "token": token,
                "display_name": "Invited Doctor",
                "password": "doctor-pass-123",
            },
        ).status_code
        == 401
    )

    accepted_headers = {"X-CSRF-TOKEN": client.get_cookie("csrf_access_token").value}
    assert client.post("/api/v1/auth/logout-all", headers=accepted_headers).status_code == 200
    assert client.get("/api/v1/me").status_code == 401


def test_admin_course_crud_and_comment_moderation(client, app) -> None:  # type: ignore[no-untyped-def]
    seed_academy(app.extensions["container"])
    headers = _admin(client, app)
    payload = {
        "slug": "clinical-cases",
        "tier": "premium",
        "field": "clinicalNeurology",
        "level": "advanced",
        "youtube_playlist_id": "PL0123456789ABCDEF",
        "translations": [
            {
                "locale": "en",
                "title": "Clinical Cases",
                "description": "Case based learning.",
                "instructor_name": "Dr. Test",
                "duration_label": "2 lessons",
            },
            {
                "locale": "fa",
                "title": "موارد بالینی",
                "description": "یادگیری مبتنی بر مورد.",
                "instructor_name": "دکتر تست",
                "duration_label": "۲ درس",
            },
        ],
        "prices": [
            {"currency": "IRR", "amount_minor": 10_000_000},
            {"currency": "USD", "amount_minor": 1_000},
        ],
    }
    created = client.post("/api/v1/admin/courses", json=payload, headers=headers)
    assert created.status_code == 201
    assert created.get_json()["data"]["youtube_playlist_id"] == "PL0123456789ABCDEF"
    course_id = created.get_json()["data"]["id"]
    assert (
        client.patch(
            f"/api/v1/admin/courses/{course_id}",
            json={"level": "intermediate"},
            headers=headers,
        ).status_code
        == 200
    )
    assert (
        client.post(f"/api/v1/admin/courses/{course_id}/publish", headers=headers).status_code
        == 422
    )
    admin_courses = client.get("/api/v1/admin/courses").get_json()["data"]
    assert any(course["id"] == course_id for course in admin_courses)
    content = {
        "sections": [
            {
                "position": 1,
                "translations": [
                    {"locale": "en", "title": "Cases"},
                    {"locale": "fa", "title": "موارد"},
                ],
                "lessons": [
                    {
                        "position": 1,
                        "duration_seconds": 600,
                        "video_provider": "youtube",
                        "video_reference": "case-01",
                        "free_preview": True,
                        "translations": [
                            {"locale": "en", "title": "First case"},
                            {"locale": "fa", "title": "مورد نخست"},
                        ],
                    }
                ],
            }
        ],
        "outcomes": [
            {"locale": "en", "position": 1, "text": "Reason through a case."},
            {"locale": "fa", "position": 1, "text": "یک مورد را تحلیل کنید."},
        ],
        "resources": [
            {
                "name": "Cases PDF",
                "kind": "pdf",
                "storage_path": "academy/cases.pdf",
                "external_url": None,
            }
        ],
        "media": [
            {
                "kind": "cover",
                "position": 1,
                "locale": None,
                "mime_type": "image/webp",
                "storage_path": "academy/cases.webp",
                "external_url": None,
            }
        ],
    }
    replaced = client.put(
        f"/api/v1/admin/courses/{course_id}/content", json=content, headers=headers
    )
    assert replaced.status_code == 200
    assert (
        replaced.get_json()["data"]["content"]["sections"][0]["lessons"][0]["video_reference"]
        == "case-01"
    )
    assert (
        client.post(f"/api/v1/admin/courses/{course_id}/publish", headers=headers).status_code
        == 200
    )
    public_course = client.get("/api/v1/courses/clinical-cases?locale=fa").get_json()["data"]
    assert public_course["resources"] == [
        {"name": "Cases PDF", "kind": "pdf", "url": None, "locked": True}
    ]
    assert (
        client.post(f"/api/v1/admin/courses/{course_id}/unpublish", headers=headers).status_code
        == 200
    )
    client.post(f"/api/v1/admin/courses/{course_id}/publish", headers=headers)
    ordering = [course["id"] for course in client.get("/api/v1/admin/courses").get_json()["data"]]
    assert (
        client.put(
            "/api/v1/admin/courses/order",
            json={"course_ids": list(reversed(ordering))},
            headers=headers,
        ).status_code
        == 200
    )

    assert client.post(
        "/api/v1/courses/clinical-neurology/enroll", headers=headers
    ).status_code == 201
    comment = client.post(
        "/api/v1/courses/clinical-neurology/comments",
        json={"body": "Please approve this discussion note."},
        headers=headers,
    )
    assert comment.status_code == 201
    comment = comment.get_json()["data"]
    pending = client.get("/api/v1/admin/comments/pending").get_json()["data"]
    assert pending[0]["id"] == comment["id"]
    inbox = client.get("/api/v1/admin/comments?status=attention").get_json()
    assert inbox["meta"]["total"] == 1
    assert inbox["data"][0]["course_title"]
    summary = client.get("/api/v1/admin/comments/summary").get_json()["data"]
    assert next(item for item in summary if item["course_slug"] == "clinical-neurology")["new"] == 1
    moderated = client.post(
        f"/api/v1/admin/comments/{comment['id']}/moderate",
        json={"decision": "approved", "reason": "Useful"},
        headers=headers,
    )
    assert moderated.status_code == 200
    assert len(client.get("/api/v1/courses/clinical-neurology/comments").get_json()["data"]) == 1
    reply = client.post(
        f"/api/v1/admin/comments/{comment['id']}/reply",
        json={"body": "Instructor response."},
        headers=headers,
    )
    assert reply.status_code == 201
    assert len(client.get("/api/v1/courses/clinical-neurology/comments").get_json()["data"]) == 2
    assert client.delete(f"/api/v1/admin/courses/{course_id}", headers=headers).status_code == 204


def test_replacing_lessons_preserves_linked_comments(client, app) -> None:  # type: ignore[no-untyped-def]
    seed_academy(app.extensions["container"])
    headers = _admin(client, app)
    course = next(
        item
        for item in client.get("/api/v1/admin/courses").get_json()["data"]
        if item["slug"] == "clinical-neurology"
    )
    lesson_id = course["content"]["sections"][0]["lessons"][0]["id"]
    assert client.post(
        "/api/v1/courses/clinical-neurology/enroll", headers=headers
    ).status_code == 201
    comment = client.post(
        "/api/v1/courses/clinical-neurology/comments",
        json={"body": "Keep this comment after editing lessons.", "lesson_id": lesson_id},
        headers=headers,
    )
    assert comment.status_code == 201
    # Content replacement is intentionally forbidden while a course has active
    # learners. Remove this test-only enrollment while retaining the comment so
    # the SET NULL behavior can still be verified independently.
    with app.extensions["container"].database.session() as session:
        session.execute(delete(Enrollment))
        session.commit()
    assert client.post(
        f"/api/v1/admin/courses/{course['id']}/unpublish", headers=headers
    ).status_code == 200

    source = course["content"]
    content = {
        "sections": [
            {
                "position": section["position"],
                "translations": section["translations"],
                "lessons": [
                    {
                        key: lesson[key]
                        for key in (
                            "position",
                            "duration_seconds",
                            "video_provider",
                            "video_reference",
                            "free_preview",
                            "translations",
                        )
                    }
                    for lesson in section["lessons"]
                ],
            }
            for section in source["sections"]
        ],
        "outcomes": source["outcomes"],
        "resources": source["resources"],
        "media": source["media"],
    }
    replaced = client.put(
        f"/api/v1/admin/courses/{course['id']}/content", json=content, headers=headers
    )
    assert replaced.status_code == 200
    comments = client.get("/api/v1/admin/comments?status=all").get_json()["data"]
    comment_id = comment.get_json()["data"]["id"]
    saved_comment = next(item for item in comments if item["id"] == comment_id)
    assert saved_comment["lesson_id"] is None


def test_cancelled_payment_and_order_validation(client, app) -> None:  # type: ignore[no-untyped-def]
    seed_academy(app.extensions["container"])
    _admin(client, app)
    headers = {"X-CSRF-TOKEN": client.get_cookie("csrf_access_token").value}
    assert client.put(
        "/api/v1/me/profile",
        headers=headers,
        json={
            "full_name": "Principal Admin",
            "email": "admin@example.com",
            "phone": "+989121234567",
        },
    ).status_code == 200
    assert (
        client.post(
            "/api/v1/orders",
            json={"course_slug": "clinical-neurology", "currency": "USD"},
            headers=headers,
        ).status_code
        == 422
    )
    created = client.post(
        "/api/v1/orders",
        json={"course_slug": "neurosurgery", "currency": "IRR"},
        headers=headers,
    ).get_json()["data"]
    attempt_id = created["payment_url"].rsplit("/", 1)[-1]
    callback = client.post(
        f"/api/v1/payments/fake/{attempt_id}/callback", json={"result": "cancel"}
    )
    assert callback.get_json()["data"]["status"] == "cancelled"
    order = client.get(f"/api/v1/orders/{created['id']}")
    assert order.get_json()["data"]["status"] == "cancelled"
