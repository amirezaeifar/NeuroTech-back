"""RFC 9457 Problem Details responses for the HTTP boundary."""

from __future__ import annotations

from dataclasses import dataclass, field
from http import HTTPStatus
from typing import Any

from flask import Flask, current_app, g, jsonify, request
from werkzeug.exceptions import HTTPException


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
    return response


def _http_code(error: HTTPException) -> str:
    status = error.code or HTTPStatus.INTERNAL_SERVER_ERROR
    try:
        phrase = HTTPStatus(status).phrase
    except ValueError:
        phrase = "HTTP Error"
    return phrase.upper().replace(" ", "_").replace("-", "_")


def register_error_handlers(app: Flask) -> None:
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
        return _problem_response(
            status=status,
            code=_http_code(error),
            title=error.name,
            detail=error.description,
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
