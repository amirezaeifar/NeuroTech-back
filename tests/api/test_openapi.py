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
        "/api/v1/products",
        "/api/v1/product-orders",
        "/api/v1/events",
        "/api/v1/admin/files",
        "/api/v1/partners",
        "/api/v1/admin/partners",
        "/api/v1/trade-documents",
        "/api/v1/admin/trade-documents",
        "/api/v1/page-content/{page_key}",
        "/api/v1/admin/page-content",
        "/api/v1/tickets",
        "/api/v1/tickets/track/{token}",
        "/api/v1/admin/tickets",
        "/api/v1/admin/tickets/{ticket_id}",
    }.issubset(document["paths"])
    progress = document["paths"]["/api/v1/me/lessons/{lesson_id}/progress"]["put"]
    assert progress["requestBody"]["required"] is True
    assert "application/json" in progress["requestBody"]["content"]
