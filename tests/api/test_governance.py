from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from flask_jwt_extended import create_access_token, decode_token

from app.core.auth_models import AuthSession
from app.services.auth import auth_service_from_container
from tests.api.test_content_management import PASSWORD, _admin


def _staff(client, app, role: str) -> dict:  # type: ignore[no-untyped-def]
    service = auth_service_from_container(app.extensions["container"])
    user = service.register_password(
        display_name=f"{role} user",
        email=f"{role}-{uuid4().hex[:6]}@example.com",
        password=PASSWORD,
    )
    token = app.extensions["container"].email_sender.sent_messages[-1].body.split("verify_email=", 1)[1].splitlines()[0]
    service.verify_email(token)
    user = service.change_user_role(user.id, role)
    session_id = uuid4()
    now = datetime.now(UTC)
    with app.extensions["container"].database.session() as session:
        session.add(
            AuthSession(
                id=session_id,
                user_id=user.id,
                family_id=uuid4(),
                refresh_jti=uuid4().hex,
                created_at=now,
                expires_at=now + timedelta(days=7),
                absolute_expires_at=now + timedelta(days=30),
            )
        )
        session.commit()
    with app.app_context():
        token = create_access_token(
            identity=str(user.id),
            additional_claims={"sid": str(session_id), "role": role},
        )
        csrf = decode_token(token)["csrf"]
    client.set_cookie("access_token_cookie", token, domain="localhost")
    return {"X-CSRF-TOKEN": csrf}


def _blog(slug: str, title: str) -> dict:
    return {
        "slug": slug,
        "cover_url": "https://example.com/cover.jpg",
        "translations": [
            {"locale": "en", "title": title, "excerpt": "Summary", "body": "Body"},
            {"locale": "fa", "title": "مطلب", "excerpt": "خلاصه", "body": "متن"},
        ],
    }


def test_blog_change_requests_are_grouped_and_reviewed(client, app) -> None:  # type: ignore[no-untyped-def]
    principal_headers = _admin(client, app)
    staff_client = app.test_client()
    staff_headers = _staff(staff_client, app, "content_manager")

    first = staff_client.post(
        "/api/v1/admin/blog", headers=staff_headers, json=_blog("grouped-post", "First")
    )
    second = staff_client.post(
        "/api/v1/admin/blog", headers=staff_headers, json=_blog("grouped-post", "Final")
    )
    assert first.status_code == second.status_code == 202
    assert first.json["data"]["approval"]["change_count"] == 1
    assert second.json["data"]["approval"]["change_count"] == 2

    pending = client.get("/api/v1/admin/approvals", headers=principal_headers)
    assert pending.status_code == 200
    request = pending.json["data"][0]
    reviewed = client.post(
        f"/api/v1/admin/approvals/{request['id']}/review",
        headers=principal_headers,
        json={"decision": "approved", "note": "Ready"},
    )
    assert reviewed.status_code == 200
    assert reviewed.json["data"]["status"] == "approved"

    posts = client.get("/api/v1/admin/blog", headers=principal_headers).json["data"]
    assert posts[0]["title"] == "Final"
    post_id = posts[0]["id"]
    assert client.patch(
        f"/api/v1/admin/blog/{post_id}",
        headers=principal_headers,
        json={"translations": _blog("ignored", "Edited")["translations"]},
    ).status_code == 200
    assert client.post(
        f"/api/v1/admin/blog/{post_id}/publish", headers=principal_headers
    ).status_code == 200
    assert client.get("/api/v1/blog/grouped-post?locale=en").json["data"]["title"] == "Edited"
    assert client.post(
        f"/api/v1/admin/blog/{post_id}/unpublish", headers=principal_headers
    ).status_code == 200
    assert client.delete(
        f"/api/v1/admin/blog/{post_id}", headers=principal_headers
    ).status_code == 204
    from app.core.governance_models import BlogPost
    from uuid import UUID
    with app.extensions["container"].database.session() as session:
        assert session.get(BlogPost, UUID(post_id)) is None


def test_settings_and_exact_role_changes_are_principal_only(client, app) -> None:  # type: ignore[no-untyped-def]
    principal_headers = _admin(client, app)
    admin_client = app.test_client()
    admin_headers = _staff(admin_client, app, "admin")

    assert admin_client.get("/api/v1/admin/settings", headers=admin_headers).status_code == 403
    settings = client.get("/api/v1/admin/settings", headers=principal_headers)
    assert settings.status_code == 200
    updated = client.put(
        "/api/v1/admin/settings",
        headers=principal_headers,
        json={"site_name": "NeuroTech Clinical", "maintenance": True},
    )
    assert updated.status_code == 200
    assert updated.json["data"]["site_name"] == "NeuroTech Clinical"
    assert updated.json["data"]["maintenance"] is True

    users = client.get("/api/v1/admin/users", headers=principal_headers).json["data"]
    target = next(item for item in users if item["role"] == "admin")
    changed = client.patch(
        f"/api/v1/admin/users/{target['id']}/role",
        headers=principal_headers,
        json={"role": "user"},
    )
    assert changed.status_code == 200
    assert changed.json["data"]["user"]["role"] == "user"


def test_content_manager_changes_to_all_main_resources_wait_for_principal(client, app):
    from app.services.seed import seed_academy
    from tests.api.test_catalog_events_files import _category, _product
    from tests.api.test_event_management import create_event

    principal_headers = _admin(client, app)
    seed_academy(app.extensions["container"])
    course = client.get("/api/v1/admin/courses", headers=principal_headers).json["data"][0]
    category = _category(client, principal_headers)
    product = _product(client, principal_headers, slug="approval-device",
        sale_mode="direct", category_slug=category)
    event = create_event(client, principal_headers, slug="approval-event")
    blog = client.post("/api/v1/admin/blog", headers=principal_headers,
        json=_blog("approval-blog", "Original")).json["data"]

    staff = app.test_client()
    headers = _staff(staff, app, "content_manager")
    changes = [
        ("course", f"/api/v1/admin/courses/{course['id']}", {"level": "advanced"}),
        ("product", f"/api/v1/admin/products/{product['id']}", {"stock_quantity": 7}),
        ("event", f"/api/v1/admin/events/{event['id']}", {"capacity": 4}),
        ("blog", f"/api/v1/admin/blog/{blog['id']}", {"cover_alt": "Reviewed"}),
    ]
    for _, path, payload in changes:
        result = staff.patch(path, headers=headers, json=payload)
        assert result.status_code == 202, result.json
    pending = client.get("/api/v1/admin/approvals", headers=principal_headers).json["data"]
    assert {item["resource_type"] for item in pending} == {item[0] for item in changes}
    assert client.get("/api/v1/admin/events", headers=principal_headers).json["data"][0]["capacity"] != 4
    for item in pending:
        reviewed = client.post(f"/api/v1/admin/approvals/{item['id']}/review",
            headers=principal_headers, json={"decision": "approved"})
        assert reviewed.status_code == 200, reviewed.json
    assert not client.get("/api/v1/admin/approvals", headers=principal_headers).json["data"]
