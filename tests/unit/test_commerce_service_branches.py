from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select

from app.core.academy_models import Course, CoursePrice
from app.core.auth_models import User
from app.core.commerce_models import Order, OrderItem, PaymentAttempt
from app.domain.errors import ConflictError, NotFoundError, ValidationError
from app.services.commerce import commerce_service_from_container
from app.services.seed import seed_academy


def _setup(app):  # type: ignore[no-untyped-def]
    container = app.extensions["container"]
    seed_academy(container)
    with container.database.session() as session:
        user = User(display_name="Buyer", role="user", status="active")
        session.add(user)
        session.commit()
        return container, user.id, commerce_service_from_container(container)


def _attempt(session, order: Order, suffix: str) -> PaymentAttempt:  # type: ignore[no-untyped-def]
    attempt = PaymentAttempt(
        order_id=order.id,
        provider="fake",
        provider_reference=f"branch:{suffix}:{order.id}",
        status="pending",
        redirect_url="/fake",
    )
    session.add(attempt)
    session.flush()
    return attempt


def test_owned_course_and_missing_price_branches(app) -> None:  # type: ignore[no-untyped-def]
    container, user_id, service = _setup(app)
    created = service.create_order(user_id, "neuroimaging", "usd")
    with container.database.session() as session:
        attempt = session.scalar(
            select(PaymentAttempt).where(PaymentAttempt.order_id == UUID(created["id"]))
        )
        assert attempt is not None
        attempt_id = attempt.id
    service.fake_payment(attempt_id, "success")
    with pytest.raises(ConflictError, match="already owned"):
        service.create_order(user_id, "neuroimaging", "USD")

    with container.database.session() as session:
        course = session.scalar(select(Course).where(Course.slug == "neurosurgery"))
        assert course is not None
        session.execute(
            delete(CoursePrice).where(
                CoursePrice.course_id == course.id, CoursePrice.currency == "USD"
            )
        )
        session.commit()
    with pytest.raises(ValidationError, match="not available"):
        service.create_order(user_id, "neurosurgery", "USD")


def test_corrupt_payment_and_existing_grants_branches(app) -> None:  # type: ignore[no-untyped-def]
    container, user_id, service = _setup(app)
    with container.database.session() as session:
        orphan = PaymentAttempt(
            order_id=uuid4(),
            provider="fake",
            provider_reference="orphan-attempt",
            status="pending",
            redirect_url="/fake",
        )
        session.add(orphan)
        session.commit()
        orphan_id = orphan.id
    with pytest.raises(NotFoundError, match="Order"):
        service.fake_payment(orphan_id, "success")

    with container.database.session() as session:
        empty_order = Order(user_id=user_id, currency="USD", total_minor=100, status="pending")
        session.add(empty_order)
        session.flush()
        empty_attempt = _attempt(session, empty_order, "empty")
        session.commit()
        empty_attempt_id = empty_attempt.id
    with pytest.raises(ValidationError, match="no purchasable item"):
        service.fake_payment(empty_attempt_id, "success")

    paid = service.create_order(user_id, "neuroimaging", "USD")
    with container.database.session() as session:
        first_attempt = session.scalar(
            select(PaymentAttempt).where(PaymentAttempt.order_id == UUID(paid["id"]))
        )
        assert first_attempt is not None
        first_attempt_id = first_attempt.id
    service.fake_payment(first_attempt_id, "success")

    with container.database.session() as session:
        course = session.scalar(select(Course).where(Course.slug == "neuroimaging"))
        assert course is not None
        duplicate_order = Order(
            user_id=user_id, currency="USD", total_minor=14_900, status="pending"
        )
        session.add(duplicate_order)
        session.flush()
        session.add(
            OrderItem(
                order_id=duplicate_order.id,
                course_id=course.id,
                title_snapshot="Neuroimaging",
                unit_amount_minor=14_900,
            )
        )
        duplicate_attempt = _attempt(session, duplicate_order, "duplicate")
        session.commit()
        duplicate_attempt_id = duplicate_attempt.id
    assert service.fake_payment(duplicate_attempt_id, "success")["status"] == "paid"
    assert service.fake_payment(duplicate_attempt_id, "cancel")["status"] == "paid"
