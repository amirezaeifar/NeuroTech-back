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


def test_liveness_does_not_require_dependencies(client) -> None:  # type: ignore[no-untyped-def]
    response = client.get("/api/v1/health/live")

    assert response.status_code == 200
    assert response.get_json()["status"] == "healthy"


def test_readiness_reports_dependency_failures(app, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    container = app.extensions["container"]
    monkeypatch.setattr(container.database, "ping", lambda: None)

    def redis_failure() -> None:
        raise ConnectionError("redis unavailable")

    monkeypatch.setattr(container.redis, "ping", redis_failure)
    response = app.test_client().get("/api/v1/health/ready")

    assert response.status_code == 503
    assert response.get_json() == {
        "dependencies": {"mariadb": "healthy", "redis": "unhealthy"},
        "service": "neurotech-api",
        "status": "unhealthy",
        "version": "0.1.0",
    }
