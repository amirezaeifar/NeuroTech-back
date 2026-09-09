from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.core.academy_models import Course
from app.core.auth_models import User
from app.domain.errors import (
    AuthenticationError,
    ConflictError,
    NotFoundError,
    ValidationError,
)
from app.services.academy import academy_service_from_container
from app.services.auth import auth_service_from_container
from app.services.commerce import commerce_service_from_container
from app.services.learning import learning_service_from_container
from app.services.seed import seed_academy


def _user_id(app):  # type: ignore[no-untyped-def]
    container = app.extensions["container"]
    with container.database.session() as session:
        user = User(display_name="Service User", role="user", status="active")
        session.add(user)
        session.commit()
        return user.id


def test_auth_service_rejects_invalid_and_duplicate_identity(app) -> None:  # type: ignore[no-untyped-def]
    service = auth_service_from_container(app.extensions["container"])
    for password in ("short1", "onlylettersxx", "12345678901"):
        with pytest.raises(ValidationError):
            service.register_password(
                display_name="Test User", email="password@example.com", password=password
            )
    service.register_password(
        display_name="Test User",
        email="duplicate@example.com",
        password="secure-pass-123",
    )
    with pytest.raises(ConflictError):
        service.register_password(
            display_name="Other User",
            email="duplicate@example.com",
            password="secure-pass-123",
        )
    with pytest.raises(AuthenticationError):
        service.verify_email("invalid-token")
    with pytest.raises(AuthenticationError):
        service.authenticate_password(email="missing@example.com", password="secure-pass-123")
    service.resend_email_verification("missing@example.com")
    before = len(app.extensions["container"].email_sender.sent_messages)
    service.resend_email_verification("duplicate@example.com")
    assert len(app.extensions["container"].email_sender.sent_messages) == before + 1
    with pytest.raises(AuthenticationError):
        service.get_user(uuid4())
    with pytest.raises(AuthenticationError):
        service.update_profile(uuid4(), "Missing User")
    service.revoke_session(uuid4())
    assert service.session_is_revoked(uuid4()) is True


def test_admin_bootstrap_and_invitation_invariants(app) -> None:  # type: ignore[no-untyped-def]
    service = auth_service_from_container(app.extensions["container"])
    service.bootstrap_admin("Admin", "admin-edge@example.com", "secure-pass-123")
    with pytest.raises(ConflictError):
        service.bootstrap_admin("Admin 2", "admin2@example.com", "secure-pass-123")
    with pytest.raises(ValidationError):
        service.create_invitation("person@example.com", "user")
    with pytest.raises(ConflictError):
        service.create_invitation("admin-edge@example.com", "specialist")

    service.create_invitation("specialist-edge@example.com", "specialist")
    token = (
        app.extensions["container"].email_sender.sent_messages[-1].body.split("invitation=", 1)[1]
    )
    accepted = service.accept_invitation(token, "Specialist", "secure-pass-123")
    assert accepted.role == "specialist"
    with pytest.raises(AuthenticationError):
        service.accept_invitation(token, "Specialist", "secure-pass-123")


def test_academy_validation_and_missing_entities(app) -> None:  # type: ignore[no-untyped-def]
    service = academy_service_from_container(app.extensions["container"])
    base = {
        "slug": "valid-course",
        "tier": "free",
        "field": "neuroscience",
        "level": "beginner",
        "translations": [
            {
                "locale": "en",
                "title": "Valid",
                "description": "Description",
                "instructor_name": "Teacher",
                "duration_label": "1 lesson",
            }
        ],
        "prices": [],
    }
    with pytest.raises(ValidationError):
        service.create_course({**base, "slug": "Invalid Slug"})
    with pytest.raises(ValidationError):
        service.create_course({**base, "tier": "unknown"})
    created = service.create_course(base)
    with pytest.raises(ConflictError):
        service.create_course(base)
    with pytest.raises(ValidationError):
        service.list_courses(locale="en", page=1, page_size=20, tier="unknown")
    with pytest.raises(ValidationError):
        service.update_course(uuid4(), {"level": "advanced"})
    with pytest.raises(ValidationError):
        service.publish(uuid4())
    with pytest.raises(ValidationError):
        service.unpublish(uuid4())
    service.archive(uuid4())
    with pytest.raises(ValidationError):
        service.reorder([uuid4(), uuid4()])
    duplicate_id = uuid4()
    with pytest.raises(ValidationError):
        service.reorder([duplicate_id, duplicate_id])
    with pytest.raises(ValidationError):
        service.replace_content(
            UUID(created["id"]),
            {
                "sections": [
                    {
                        "position": 1,
                        "translations": [{"locale": "en", "title": "Only English"}],
                        "lessons": [],
                    }
                ],
                "outcomes": [],
                "resources": [],
                "media": [],
            },
        )


def test_learning_and_commerce_reject_invalid_operations(app) -> None:  # type: ignore[no-untyped-def]
    container = app.extensions["container"]
    seed_academy(container)
    user_id = _user_id(app)
    learning = learning_service_from_container(container)
    commerce = commerce_service_from_container(container)

    with pytest.raises(ValidationError):
        learning.enroll_free(user_id, "neuroimaging")
    with pytest.raises(NotFoundError):
        learning.access(user_id, "missing-course")
    with pytest.raises(NotFoundError):
        learning.save_progress(user_id, uuid4(), position_seconds=0, completed=False)
    with pytest.raises(ValidationError):
        learning.save_progress(user_id, uuid4(), position_seconds=-1, completed=False)
    with pytest.raises(ValidationError):
        learning.add_comment(user_id, "clinical-neurology", "x")
    with pytest.raises(NotFoundError):
        learning.add_comment(user_id, "missing-course", "A valid comment")
    with pytest.raises(ValidationError):
        learning.moderate(user_id, uuid4(), "unknown", None)
    with pytest.raises(NotFoundError):
        learning.moderate(user_id, uuid4(), "approved", None)

    with pytest.raises(ValidationError):
        commerce.create_order(user_id, "neuroimaging", "EUR")
    with pytest.raises(NotFoundError):
        commerce.create_order(user_id, "missing-course", "USD")
    with pytest.raises(ValidationError):
        commerce.create_order(user_id, "clinical-neurology", "USD")
    with pytest.raises(ValidationError):
        commerce.fake_payment(uuid4(), "unknown")
    with pytest.raises(NotFoundError):
        commerce.fake_payment(uuid4(), "success")
    with pytest.raises(NotFoundError):
        commerce.get_order(user_id, uuid4())

    with container.database.session() as session:
        course = session.scalar(select(Course).where(Course.slug == "neuroimaging"))
        assert course is not None
