from __future__ import annotations

from app.services.seed import seed_academy


def test_seed_is_idempotent_and_courses_are_localized(client, app) -> None:  # type: ignore[no-untyped-def]
    container = app.extensions["container"]
    assert seed_academy(container) == 6
    assert seed_academy(container) == 0

    response = client.get("/api/v1/courses?locale=fa&tier=premium")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["meta"]["total"] == 3
    assert payload["data"][0]["title"] == "تصویربرداری عصبی: تفسیر MRI و CT"
    assert payload["data"][0]["lesson_count"] == 2
    assert {price["currency"] for price in payload["data"][0]["prices"]} == {"IRR", "USD"}


def test_course_detail_uses_stable_slug(client, app) -> None:  # type: ignore[no-untyped-def]
    seed_academy(app.extensions["container"])

    response = client.get("/api/v1/courses/clinical-neurology?locale=en")

    assert response.status_code == 200
    assert response.get_json()["data"]["slug"] == "clinical-neurology"
    assert "resources" in response.get_json()["data"]


def test_course_admin_requires_authentication(client) -> None:  # type: ignore[no-untyped-def]
    response = client.post("/api/v1/admin/courses", json={})

    assert response.status_code == 401
    assert response.get_json()["code"] == "AUTHENTICATION_REQUIRED"


def test_unknown_course_uses_problem_details(client) -> None:  # type: ignore[no-untyped-def]
    response = client.get("/api/v1/courses/not-a-course")

    assert response.status_code == 404
    assert response.mimetype == "application/problem+json"
