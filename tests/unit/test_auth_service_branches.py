from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.core.auth_models import AuthSession, EmailIdentity, Invitation, User
from app.domain.errors import AuthenticationError, ConflictError, ValidationError
from app.services.auth import auth_service_from_container

PASSWORD = "secure-pass-123"


def _service(app):  # type: ignore[no-untyped-def]
    return auth_service_from_container(app.extensions["container"])


def _verify(service, app, email: str) -> None:  # type: ignore[no-untyped-def]
    token = (
        app.extensions["container"].email_sender.sent_messages[-1].body.split("verify_email=", 1)[1]
    )
    service.verify_email(token)


def test_email_status_and_bootstrap_branches(app) -> None:  # type: ignore[no-untyped-def]
    service = _service(app)
    service.register_password(display_name="Member", email="member@example.com", password=PASSWORD)
    with pytest.raises(AuthenticationError, match="verification"):
        service.authenticate_password(email="member@example.com", password=PASSWORD)
    _verify(service, app, "member@example.com")
    sent = len(app.extensions["container"].email_sender.sent_messages)
    service.resend_email_verification("member@example.com")
    assert len(app.extensions["container"].email_sender.sent_messages) == sent

    with app.extensions["container"].database.session() as session:
        user = session.scalar(
            select(User).join(EmailIdentity).where(EmailIdentity.email == "member@example.com")
        )
        assert user is not None
        user.status = "suspended"
        session.commit()
    with pytest.raises(AuthenticationError, match="not active"):
        service.authenticate_password(email="member@example.com", password=PASSWORD)
    with pytest.raises(ConflictError):
        service.bootstrap_admin("Admin", "member@example.com", PASSWORD)
    with pytest.raises(ValidationError):
        service.register_password(
            display_name="x", email="short-name@example.com", password=PASSWORD
        )


def test_verification_and_invitation_expiry_conflict_branches(app) -> None:  # type: ignore[no-untyped-def]
    service = _service(app)
    missing_token = service.serializer.dumps({"email": "absent@example.com"})
    with pytest.raises(AuthenticationError):
        service.verify_email(missing_token)

    service.create_invitation("expired@example.com", "specialist")
    expired_token = (
        app.extensions["container"].email_sender.sent_messages[-1].body.split("invitation=", 1)[1]
    )
    with app.extensions["container"].database.session() as session:
        invitation = session.scalar(
            select(Invitation).where(Invitation.email == "expired@example.com")
        )
        assert invitation is not None
        invitation.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        session.commit()
    with pytest.raises(AuthenticationError, match="expired"):
        service.accept_invitation(expired_token, "Expired User", PASSWORD)

    service.create_invitation("collision@example.com", "admin")
    collision_token = (
        app.extensions["container"].email_sender.sent_messages[-1].body.split("invitation=", 1)[1]
    )
    with app.extensions["container"].database.session() as session:
        user = User(display_name="Collision", role="user", status="active")
        user.emails.append(EmailIdentity(email="collision@example.com"))
        session.add(user)
        session.commit()
    with pytest.raises(ConflictError):
        service.accept_invitation(collision_token, "Collision", PASSWORD)


def test_phone_and_session_rotation_branches(app) -> None:  # type: ignore[no-untyped-def]
    service = _service(app)
    phone = "+989121234567"
    registered = service.register_phone(display_name="Phone User", phone=phone)
    assert service.user_for_phone_login(phone) == registered
    with pytest.raises(ConflictError):
        service.register_phone(display_name="Duplicate", phone=phone)
    with app.extensions["container"].database.session() as session:
        user = session.get(User, registered.id)
        assert user is not None
        user.status = "suspended"
        session.commit()
    assert service.user_for_phone_login(phone) is None
    assert service.user_for_phone_login("+989121234568") is None

    session_id = uuid4()
    service.create_session(
        session_id=session_id,
        user_id=registered.id,
        refresh_jti="first",
        ip_address=None,
        user_agent=None,
    )
    service.rotate_session(session_id=session_id, presented_jti="first", next_jti="second")
    with pytest.raises(AuthenticationError, match="reuse"):
        service.rotate_session(session_id=session_id, presented_jti="first", next_jti="third")
    with pytest.raises(AuthenticationError, match="no longer active"):
        service.rotate_session(session_id=session_id, presented_jti="second", next_jti="third")

    expired_id = uuid4()
    service.create_session(
        session_id=expired_id,
        user_id=registered.id,
        refresh_jti="expired",
        ip_address="127.0.0.1",
        user_agent="test",
    )
    with app.extensions["container"].database.session() as session:
        auth_session = session.get(AuthSession, expired_id)
        assert auth_session is not None
        auth_session.absolute_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        session.commit()
    with pytest.raises(AuthenticationError, match="expired"):
        service.rotate_session(session_id=expired_id, presented_jti="expired", next_jti="never")
    assert service.session_is_revoked(expired_id) is True
