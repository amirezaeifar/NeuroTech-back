"""RFC 9457 Problem Details responses for the HTTP boundary."""

from __future__ import annotations

from dataclasses import dataclass, field
from http import HTTPStatus
from typing import Any

from flask import Flask, current_app, g, jsonify, request
from redis.exceptions import RedisError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError
from werkzeug.exceptions import HTTPException

from app.domain.errors import (
    ApplicationError,
    AuthenticationError,
    AuthorizationError,
    ConflictError,
    NotFoundError,
    RateLimitExceededError,
    TemporarilyUnavailableError,
    ValidationError,
)


@dataclass(slots=True)
class ApiProblem(Exception):
    """An expected API-facing problem with a stable machine code."""

    status: int
    code: str
    title: str
    detail: str
    errors: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        Exception.__init__(self, self.detail)


def _problem_type(code: str) -> str:
    slug = code.lower().replace("_", "-")
    return f"{current_app.config['PROBLEM_BASE_URI']}/{slug}"


def _problem_response(
    *,
    status: int,
    code: str,
    title: str,
    detail: str,
    errors: list[dict[str, Any]] | None = None,
    headers: dict[str, str] | None = None,
):  # type: ignore[no-untyped-def]
    payload: dict[str, Any] = {
        "type": _problem_type(code),
        "title": title,
        "status": status,
        "detail": detail,
        "instance": request.path,
        "code": code,
        "request_id": g.request_id,
    }
    if errors:
        payload["errors"] = errors

    response = jsonify(payload)
    response.status_code = status
    response.mimetype = "application/problem+json"
    for name, value in (headers or {}).items():
        response.headers[name] = value
    return response


def _http_code(error: HTTPException) -> str:
    status = error.code or HTTPStatus.INTERNAL_SERVER_ERROR
    try:
        phrase = HTTPStatus(status).phrase
    except ValueError:
        phrase = "HTTP Error"
    return phrase.upper().replace(" ", "_").replace("-", "_")


def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(StaleDataError)
    def handle_stale_data(error: StaleDataError):  # type: ignore[no-untyped-def]
        current_app.logger.info("Version conflict request_id=%s", g.request_id, exc_info=error)
        return _problem_response(
            status=HTTPStatus.CONFLICT,
            code="VERSION_CONFLICT",
            title="Version conflict",
            detail="The resource changed while it was being updated. Reload and retry.",
        )

    @app.errorhandler(IntegrityError)
    def handle_integrity_error(error: IntegrityError):  # type: ignore[no-untyped-def]
        current_app.logger.info("Data conflict request_id=%s", g.request_id, exc_info=error)
        return _problem_response(
            status=HTTPStatus.CONFLICT,
            code="DATA_CONFLICT",
            title="Data conflict",
            detail="The operation conflicts with existing data.",
        )

    @app.errorhandler(RedisError)
    def handle_redis_error(error: RedisError):  # type: ignore[no-untyped-def]
        current_app.logger.error("Redis unavailable request_id=%s", g.request_id, exc_info=error)
        return _problem_response(
            status=HTTPStatus.SERVICE_UNAVAILABLE,
            code="AUTH_TEMPORARILY_UNAVAILABLE",
            title="Authentication temporarily unavailable",
            detail="Authentication is temporarily unavailable. Please retry shortly.",
        )

    @app.errorhandler(ApplicationError)
    def handle_application_error(error: ApplicationError):  # type: ignore[no-untyped-def]
        headers = None
        if isinstance(error, RateLimitExceededError):
            status, title = HTTPStatus.TOO_MANY_REQUESTS, "Too many requests"
            headers = {"Retry-After": str(error.retry_after)}
        elif isinstance(error, ValidationError):
            status, title = HTTPStatus.UNPROCESSABLE_ENTITY, "Validation failed"
        elif isinstance(error, ConflictError):
            status, title = HTTPStatus.CONFLICT, "Conflict"
        elif isinstance(error, NotFoundError):
            status, title = HTTPStatus.NOT_FOUND, "Not found"
        elif isinstance(error, AuthorizationError):
            status, title = HTTPStatus.FORBIDDEN, "Forbidden"
        elif isinstance(error, TemporarilyUnavailableError):
            status, title = HTTPStatus.SERVICE_UNAVAILABLE, "Service unavailable"
        elif isinstance(error, AuthenticationError):
            status, title = HTTPStatus.UNAUTHORIZED, "Authentication failed"
        else:
            status, title = HTTPStatus.BAD_REQUEST, "Request failed"
        return _problem_response(
            status=status,
            code=error.code,
            title=title,
            detail=error.detail,
            headers=headers,
        )

    @app.errorhandler(ApiProblem)
    def handle_api_problem(error: ApiProblem):  # type: ignore[no-untyped-def]
        return _problem_response(
            status=error.status,
            code=error.code,
            title=error.title,
            detail=error.detail,
            errors=error.errors,
        )

    @app.errorhandler(HTTPException)
    def handle_http_exception(error: HTTPException):  # type: ignore[no-untyped-def]
        status = error.code or HTTPStatus.INTERNAL_SERVER_ERROR
        retry_after = error.get_response().headers.get("Retry-After")
        return _problem_response(
            status=status,
            code=_http_code(error),
            title=error.name,
            detail=error.description,
            headers={"Retry-After": retry_after} if retry_after else None,
        )

    @app.errorhandler(Exception)
    def handle_unexpected_exception(error: Exception):  # type: ignore[no-untyped-def]
        current_app.logger.exception(
            "Unhandled exception request_id=%s",
            g.request_id,
            exc_info=error,
        )
        return _problem_response(
            status=HTTPStatus.INTERNAL_SERVER_ERROR,
            code="INTERNAL_SERVER_ERROR",
            title="Internal Server Error",
            detail="An unexpected error occurred.",
        )
