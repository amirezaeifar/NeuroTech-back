"""JWT cookie behavior and RFC 9457 failures."""

from __future__ import annotations

from http import HTTPStatus
from datetime import UTC, datetime, timedelta
from uuid import UUID

from flask import current_app
from sqlalchemy import func, update

from app.core.extensions import jwt
from app.core.auth_models import User
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
        if service.session_is_revoked(parsed):
            return True
        with service.uow_factory() as uow:
            user = uow.session.get(User, UUID(payload["sub"]))
            if user is None or user.status != "active":
                return True
            now = datetime.now(UTC)
            last = user.last_active_at
            if last and (last.replace(tzinfo=UTC) if last.tzinfo is None else last) < now - timedelta(days=30):
                uow.session.execute(
                    update(User.__table__)
                    .where(User.id == user.id, User.status == "active")
                    .values(status="suspended", version=User.version + 1)
                )
                uow.commit()
                return True
            # Activity is a heartbeat, not an edit of the versioned user record.
            # A direct update avoids optimistic-lock conflicts across parallel API calls.
            uow.session.execute(
                update(User.__table__)
                .where(User.id == user.id, User.status == "active")
                .values(activated_at=func.coalesce(User.activated_at, now), last_active_at=now)
            )
            uow.commit()
            return False

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
