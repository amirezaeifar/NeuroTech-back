from __future__ import annotations


def test_openapi_contract_exposes_mvp_routes(client) -> None:  # type: ignore[no-untyped-def]
    response = client.get("/api/v1/openapi.json")

    assert response.status_code == 200
    document = response.get_json()
    assert document["openapi"] == "3.1.0"
    assert document["info"]["title"] == "NeuroTech API"
    assert {
        "/api/v1/health/live",
        "/api/v1/health/ready",
        "/api/v1/auth/login/password",
        "/api/v1/auth/register/phone/request-otp",
        "/api/v1/auth/login/otp/verify",
        "/api/v1/auth/refresh",
        "/api/v1/admin/users",
        "/api/v1/courses",
        "/api/v1/courses/{slug}",
        "/api/v1/courses/{slug}/access",
        "/api/v1/me/lessons/{lesson_id}/progress",
        "/api/v1/orders",
    }.issubset(document["paths"])
    progress = document["paths"]["/api/v1/me/lessons/{lesson_id}/progress"]["put"]
    assert progress["requestBody"]["required"] is True
    assert "application/json" in progress["requestBody"]["content"]
