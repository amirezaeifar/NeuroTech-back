from __future__ import annotations

from uuid import UUID

from app.routes.errors import ApiProblem


def _assert_problem(response, *, status: int, code: str) -> dict:  # type: ignore[no-untyped-def]
    assert response.status_code == status
    assert response.mimetype == "application/problem+json"
    payload = response.get_json()
    assert payload["status"] == status
    assert payload["code"] == code
    assert payload["instance"]
    assert payload["type"].endswith(code.lower().replace("_", "-"))
    assert payload["request_id"] == response.headers["X-Request-ID"]
    UUID(payload["request_id"])
    return payload


def test_not_found_uses_problem_details(client) -> None:  # type: ignore[no-untyped-def]
    response = client.get("/api/v1/missing")

    _assert_problem(response, status=404, code="NOT_FOUND")


def test_method_not_allowed_uses_problem_details(client) -> None:  # type: ignore[no-untyped-def]
    response = client.post("/api/v1/health")

    _assert_problem(response, status=405, code="METHOD_NOT_ALLOWED")


def test_expected_api_problem_preserves_validation_errors(app) -> None:  # type: ignore[no-untyped-def]
    @app.get("/api/v1/_test/validation")
    def validation_problem():  # type: ignore[no-untyped-def]
        raise ApiProblem(
            status=422,
            code="VALIDATION_ERROR",
            title="Validation failed",
            detail="One or more fields are invalid.",
            errors=[{"field": "email", "code": "EMAIL_INVALID"}],
        )

    response = app.test_client().get("/api/v1/_test/validation")
    payload = _assert_problem(response, status=422, code="VALIDATION_ERROR")
    assert payload["errors"] == [{"field": "email", "code": "EMAIL_INVALID"}]


def test_unexpected_error_does_not_leak_internal_details(app) -> None:  # type: ignore[no-untyped-def]
    @app.get("/api/v1/_test/boom")
    def boom():  # type: ignore[no-untyped-def]
        raise RuntimeError("sensitive-internal-detail")

    response = app.test_client().get("/api/v1/_test/boom")
    payload = _assert_problem(response, status=500, code="INTERNAL_SERVER_ERROR")

    assert payload["detail"] == "An unexpected error occurred."
    assert "sensitive-internal-detail" not in response.get_data(as_text=True)
