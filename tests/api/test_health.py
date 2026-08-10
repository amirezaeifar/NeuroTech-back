from __future__ import annotations

from uuid import UUID


def test_health_endpoint_returns_service_status(client) -> None:  # type: ignore[no-untyped-def]
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.mimetype == "application/json"
    assert response.get_json() == {
        "service": "neurotech-api",
        "status": "healthy",
        "version": "0.1.0",
    }
    UUID(response.headers["X-Request-ID"])


def test_each_request_gets_a_distinct_request_id(client) -> None:  # type: ignore[no-untyped-def]
    first = client.get("/api/v1/health")
    second = client.get("/api/v1/health")

    assert first.headers["X-Request-ID"] != second.headers["X-Request-ID"]
