from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.core.academy_models import Course, Lesson
from app.core.auth_models import User
from app.core.commerce_models import Entitlement, Order
from app.core.learning_models import Enrollment
from app.domain.errors import AuthorizationError, NotFoundError
from app.services.learning import learning_service_from_container
from app.services.seed import seed_academy


def _setup(app):  # type: ignore[no-untyped-def]
    container = app.extensions["container"]
    seed_academy(container)
    with container.database.session() as session:
        user = User(display_name="Learner", role="user", status="active")
        session.add(user)
        session.commit()
        return container, user.id, learning_service_from_container(container)


def test_access_without_enrollment_and_entitlement_expiry(app) -> None:  # type: ignore[no-untyped-def]
    container, user_id, service = _setup(app)
    denied = service.access(user_id, "neuroimaging", "invalid")
    assert denied["entitled"] is False
    assert denied["can_access"] is False
    assert denied["lessons"] == []

    with container.database.session() as session:
        course = session.scalar(select(Course).where(Course.slug == "neuroimaging"))
        assert course is not None
        order = Order(user_id=user_id, currency="USD", total_minor=1, status="paid")
        session.add(order)
        session.flush()
        entitlement = Entitlement(
            user_id=user_id,
            course_id=course.id,
            source_order_id=order.id,
            status="active",
            starts_at=datetime.now(UTC),
            expires_at=None,
        )
        session.add(entitlement)
        session.commit()
        entitlement_id = entitlement.id
        course_id = course.id
    assert service.access(user_id, "neuroimaging")["entitled"] is True

    with container.database.session() as session:
        entitlement = session.get(Entitlement, entitlement_id)
        assert entitlement is not None
        entitlement.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        session.add(
            Enrollment(
                user_id=user_id,
                course_id=course_id,
                status="active",
                enrolled_at=datetime.now(UTC),
            )
        )
        session.commit()
    expired = service.access(user_id, "neuroimaging")
    assert expired["entitled"] is False
    assert expired["can_access"] is False


def test_progress_requires_enrollment_and_premium_entitlement(app) -> None:  # type: ignore[no-untyped-def]
    container, user_id, service = _setup(app)
    with container.database.session() as session:
        free = session.scalar(select(Course).where(Course.slug == "clinical-neurology"))
        premium = session.scalar(select(Course).where(Course.slug == "neuroimaging"))
        assert free is not None and premium is not None
        free_lesson = session.scalar(
            select(Lesson).join(Lesson.section).where(Lesson.section.has(course_id=free.id))
        )
        premium_lesson = session.scalar(
            select(Lesson).join(Lesson.section).where(Lesson.section.has(course_id=premium.id))
        )
        assert free_lesson is not None and premium_lesson is not None
        free_lesson_id = free_lesson.id
        premium_lesson_id = premium_lesson.id
        session.add(
            Enrollment(
                user_id=user_id,
                course_id=premium.id,
                status="active",
                enrolled_at=datetime.now(UTC),
            )
        )
        session.commit()
    with pytest.raises(AuthorizationError, match="enrollment"):
        service.save_progress(user_id, free_lesson_id, position_seconds=1, completed=False)
    with pytest.raises(AuthorizationError, match="entitlement"):
        service.save_progress(user_id, premium_lesson_id, position_seconds=1, completed=False)
    with pytest.raises(AuthorizationError, match="Enrollment"):
        service.add_comment(user_id, "clinical-neurology", "Valid comment")


def test_pathway_locked_completed_and_missing_course_branches(app) -> None:  # type: ignore[no-untyped-def]
    container, user_id, service = _setup(app)
    with pytest.raises(NotFoundError, match="User"):
        service.pathway(uuid4(), "en")
    service.enroll_free(user_id, "clinical-neurology")
    initial = service.pathway(user_id, "invalid")
    assert initial["courses"][0]["modules"][0]["status"] == "in-progress"

    with container.database.session() as session:
        course = session.scalar(select(Course).where(Course.slug == "clinical-neurology"))
        assert course is not None
        lesson_ids = list(
            session.scalars(
                select(Lesson).join(Lesson.section).where(Lesson.section.has(course_id=course.id))
            )
        )
    for lesson in lesson_ids:
        service.save_progress(
            user_id, lesson.id, position_seconds=lesson.duration_seconds, completed=True
        )
    completed = service.pathway(user_id, "fa")
    assert completed["courses"][0]["status"] == "completed"
    assert completed["courses"][0]["modules"][0]["status"] == "completed"

    with container.database.session() as session:
        session.add(
            Enrollment(
                user_id=user_id,
                course_id=uuid4(),
                status="active",
                enrolled_at=datetime.now(UTC),
            )
        )
        session.commit()
    assert len(service.pathway(user_id, "en")["courses"]) == 1
