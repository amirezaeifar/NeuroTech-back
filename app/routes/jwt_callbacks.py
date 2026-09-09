"""JWT cookie behavior and RFC 9457 failures."""

from __future__ import annotations

from http import HTTPStatus
from uuid import UUID

from flask import current_app

from app.core.extensions import jwt
from app.routes.errors import _problem_response
from app.services.auth import auth_service_from_container


def register_jwt_callbacks() -> None:
    @jwt.token_in_blocklist_loader
    def token_is_revoked(_header: dict, payload: dict) -> bool:
        session_id = payload.get("sid")
        if not session_id:
            return True
        try:
            parsed = UUID(session_id)
        except (TypeError, ValueError):
            return True
        service = auth_service_from_container(current_app.extensions["container"])
        return service.session_is_revoked(parsed)

    @jwt.unauthorized_loader
    def missing_token(detail: str):  # type: ignore[no-untyped-def]
        return _problem_response(
            status=HTTPStatus.UNAUTHORIZED,
            code="AUTHENTICATION_REQUIRED",
            title="Authentication required",
            detail=detail,
        )

    @jwt.invalid_token_loader
    def invalid_token(detail: str):  # type: ignore[no-untyped-def]
        return _problem_response(
            status=HTTPStatus.UNAUTHORIZED,
            code="TOKEN_INVALID",
            title="Invalid token",
            detail=detail,
        )

    @jwt.expired_token_loader
    def expired_token(_header: dict, _payload: dict):  # type: ignore[no-untyped-def]
        return _problem_response(
            status=HTTPStatus.UNAUTHORIZED,
            code="TOKEN_EXPIRED",
            title="Token expired",
            detail="The authentication token has expired.",
        )

    @jwt.revoked_token_loader
    def revoked_token(_header: dict, _payload: dict):  # type: ignore[no-untyped-def]
        return _problem_response(
            status=HTTPStatus.UNAUTHORIZED,
            code="TOKEN_REVOKED",
            title="Token revoked",
            detail="The authentication session is no longer active.",
        )
