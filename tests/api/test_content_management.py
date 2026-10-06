from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from flask_jwt_extended import create_access_token, decode_token

from app.core.auth_models import AuthSession
from app.services.auth import auth_service_from_container
from app.services.seed import seed_academy

PASSWORD = "secure-pass-123"


def _admin(client, app):  # type: ignore[no-untyped-def]
    admin = auth_service_from_container(app.extensions["container"]).bootstrap_admin(
        "Content Admin", "content-admin@example.com", PASSWORD
    )
    session_id = uuid4()
    now = datetime.now(UTC)
    with app.extensions["container"].database.session() as session:
        session.add(
            AuthSession(
                id=session_id,
                user_id=admin.id,
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
            identity=str(admin.id),
            additional_claims={"sid": str(session_id), "role": admin.role},
        )
        csrf = decode_token(token)["csrf"]
    client.set_cookie("access_token_cookie", token, domain="localhost")
    return {"X-CSRF-TOKEN": csrf}


def _partner_translations() -> list[dict]:
    return [
        {
            "locale": "en",
            "name": "Dr Example",
            "title": "Clinical Partner",
            "qualification": "Neurologist",
            "location": "Mashhad, Iran",
            "affiliation": "NeuroTech",
            "bio": "Clinical and research partner.",
            "details": {"collaborations": ["Clinical Research"]},
        },
        {
            "locale": "fa",
            "name": "دکتر نمونه",
            "title": "همکار بالینی",
            "qualification": "متخصص مغز و اعصاب",
            "location": "مشهد، ایران",
            "affiliation": "نوروتک",
            "bio": "همکار بالینی و پژوهشی.",
            "details": {"collaborations": ["پژوهش بالینی"]},
        },
    ]


def _trade_translations() -> list[dict]:
    return [
        {
            "locale": "en",
            "title": "MRI Infrastructure Assessment",
            "doc_type": "Technical report",
            "partner_name": "Example Partner",
            "category": "Medical imaging",
            "location": "Mashhad, Iran",
            "summary": "Infrastructure readiness report.",
            "groups": [{"label": "Outcome", "kind": "text", "text": "Ready."}],
        },
        {
            "locale": "fa",
            "title": "ارزیابی زیرساخت ام‌آر‌آی",
            "doc_type": "گزارش فنی",
            "partner_name": "همکار نمونه",
            "category": "تصویربرداری پزشکی",
            "location": "مشهد، ایران",
            "summary": "گزارش آمادگی زیرساخت.",
            "groups": [{"label": "نتیجه", "kind": "text", "text": "آماده است."}],
        },
    ]


def test_partner_content_lifecycle(client, app) -> None:  # type: ignore[no-untyped-def]
    headers = _admin(client, app)
    created = client.post(
        "/api/v1/admin/partners",
        headers=headers,
        json={"slug": "doctor-example", "position": 1, "translations": _partner_translations()},
    )
    assert created.status_code == 201
    partner = created.get_json()["data"]
    assert partner["slug"].startswith("dr-example-")
    assert client.get("/api/v1/partners").get_json()["data"] == []

    published = client.post(
        f"/api/v1/admin/partners/{partner['id']}/publish", headers=headers
    )
    assert published.status_code == 200
    localized = client.get(f"/api/v1/partners/{partner['slug']}?locale=fa").get_json()["data"]
    assert localized["name"] == "دکتر نمونه"

    seed_academy(app.extensions["container"])
    course = client.get("/api/v1/admin/courses", headers=headers).get_json()["data"][0]
    linked = client.patch(
        f"/api/v1/admin/courses/{course['id']}",
        headers=headers,
        json={"instructor_partner_id": partner["id"]},
    )
    assert linked.status_code == 200
    assert linked.get_json()["data"]["instructor_partner_slug"] == partner["slug"]
    assert localized["collaborations"] == ["پژوهش بالینی"]

    updated = client.patch(
        f"/api/v1/admin/partners/{partner['id']}", headers=headers, json={"position": 3}
    )
    assert updated.get_json()["data"]["position"] == 3
    assert client.get("/api/v1/admin/partners").status_code == 200

    archived = client.delete(f"/api/v1/admin/partners/{partner['id']}", headers=headers)
    assert archived.status_code == 204
    assert client.get("/api/v1/partners").get_json()["data"] == []


def test_trade_document_content_lifecycle(client, app) -> None:  # type: ignore[no-untyped-def]
    headers = _admin(client, app)
    created = client.post(
        "/api/v1/admin/trade-documents",
        headers=headers,
        json={
            "slug": "mri-assessment",
            "document_code": "STD-TEST-001",
            "position": 1,
            "translations": _trade_translations(),
        },
    )
    assert created.status_code == 201
    document = created.get_json()["data"]
    assert document["id"] == "STD-TEST-001"
    assert client.get("/api/v1/trade-documents").get_json()["data"] == []

    published = client.post(
        f"/api/v1/admin/trade-documents/{document['record_id']}/publish", headers=headers
    )
    assert published.status_code == 200
    localized = client.get("/api/v1/trade-documents/mri-assessment?locale=fa")
    assert localized.status_code == 200
    assert localized.get_json()["data"]["title"] == "ارزیابی زیرساخت ام‌آر‌آی"
    assert client.get("/api/v1/admin/trade-documents").status_code == 200

    unpublished = client.post(
        f"/api/v1/admin/trade-documents/{document['record_id']}/unpublish", headers=headers
    )
    assert unpublished.status_code == 200
    assert client.get("/api/v1/trade-documents/mri-assessment").status_code == 404


def test_managed_page_copy_overrides_and_static_pages_are_rejected(client, app) -> None:  # type: ignore[no-untyped-def]
    headers = _admin(client, app)
    saved = client.put(
        "/api/v1/admin/page-content/products",
        headers=headers,
        json={
            "translations": [
                {"locale": "en", "content": {"hero": {"title": "Managed products"}}},
                {"locale": "fa", "content": {"hero": {"title": "محصولات مدیریت‌شده"}}},
            ]
        },
    )
    assert saved.status_code == 200
    assert client.get("/api/v1/page-content/products").status_code == 404
    published = client.post("/api/v1/admin/page-content/products/publish", headers=headers)
    assert published.status_code == 200
    public = client.get("/api/v1/page-content/products?locale=fa").get_json()["data"]
    assert public["content"]["hero"]["title"] == "محصولات مدیریت‌شده"
    assert client.get("/api/v1/admin/page-content", headers=headers).status_code == 200

    static_page = client.put(
        "/api/v1/admin/page-content/home",
        headers=headers,
        json={
            "translations": [
                {"locale": "en", "content": {}},
                {"locale": "fa", "content": {}},
            ]
        },
    )
    assert static_page.status_code == 422
