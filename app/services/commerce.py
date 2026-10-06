"""Order and payment orchestration for the Academy MVP."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select

from app.core.academy_models import Course, CoursePrice, CourseTranslation
from app.core.auth_models import UserProfile
from app.core.commerce_models import (
    Entitlement,
    Order,
    OrderItem,
    PaymentAttempt,
    PaymentEvent,
)
from app.core.learning_models import Enrollment
from app.core.unit_of_work import SqlAlchemyUnitOfWork
from app.domain.errors import ConflictError, NotFoundError, ValidationError
from app.domain.ports import PaymentGateway


class CommerceService:
    def __init__(self, uow_factory, gateway: PaymentGateway) -> None:  # type: ignore[no-untyped-def]
        self.uow_factory = uow_factory
        self.gateway = gateway

    def create_order(self, user_id: UUID, slug: str, currency: str) -> dict:
        currency = currency.upper()
        if currency not in {"IRR", "USD"}:
            raise ValidationError("Currency must be IRR or USD.")
        with self.uow_factory() as uow:
            course = uow.session.scalar(
                select(Course).where(
                    Course.slug == slug,
                    Course.published_at.is_not(None),
                    Course.archived_at.is_(None),
                )
            )
            if course is None:
                raise NotFoundError("Course does not exist.")
            if course.tier != "premium":
                raise ValidationError("Free courses do not require an order.")
            entitlement = uow.session.scalar(
                select(Entitlement.id).where(
                    Entitlement.user_id == user_id,
                    Entitlement.course_id == course.id,
                    Entitlement.status == "active",
                )
            )
            if entitlement:
                raise ConflictError("This course is already owned.")
            price = uow.session.scalar(
                select(CoursePrice).where(
                    CoursePrice.course_id == course.id, CoursePrice.currency == currency
                )
            )
            if price is None:
                raise ValidationError("The selected currency is not available.")
            _require_user_profile(uow.session, user_id)
            title = uow.session.scalar(
                select(CourseTranslation.title).where(
                    CourseTranslation.course_id == course.id,
                    CourseTranslation.locale == "en",
                )
            )
            order = Order(
                user_id=user_id,
                currency=currency,
                total_minor=price.amount_minor,
                status="pending",
            )
            uow.session.add(order)
            uow.session.flush()
            uow.session.add(
                OrderItem(
                    order_id=order.id,
                    course_id=course.id,
                    title_snapshot=title or course.slug,
                    unit_amount_minor=price.amount_minor,
                )
            )
            attempt = PaymentAttempt(
                order_id=order.id,
                provider="fake",
                provider_reference=f"fake:{order.id}",
                status="pending",
                redirect_url="pending",
            )
            uow.session.add(attempt)
            uow.session.flush()
            attempt.redirect_url = self.gateway.create_payment(
                reference=str(attempt.id),
                amount_minor=order.total_minor,
                currency=order.currency,
                callback_url="/api/v1/payments/fake",
            )
            uow.commit()
            return {
                "id": str(order.id),
                "status": order.status,
                "currency": order.currency,
                "total_minor": order.total_minor,
                "payment_url": attempt.redirect_url,
            }

    def fake_payment(self, attempt_id: UUID, result: str) -> dict:
        if result not in {"success", "cancel", "failure"}:
            raise ValidationError("Fake payment result must be success, cancel or failure.")
        event_id = f"fake:{attempt_id}:{result}"
        with self.uow_factory() as uow:
            attempt = uow.session.scalar(
                select(PaymentAttempt).where(PaymentAttempt.id == attempt_id).with_for_update()
            )
            if attempt is None:
                raise NotFoundError("Payment attempt does not exist.")
            order = uow.session.scalar(
                select(Order).where(Order.id == attempt.order_id).with_for_update()
            )
            if order is None:
                raise NotFoundError("Order does not exist.")
            existing = uow.session.scalar(
                select(PaymentEvent).where(PaymentEvent.provider_event_id == event_id)
            )
            if existing is None:
                uow.session.add(
                    PaymentEvent(
                        attempt_id=attempt.id,
                        provider_event_id=event_id,
                        event_type=result,
                        payload={"result": result},
                    )
                )
            if result == "success" and order.status != "paid":
                now = datetime.now(UTC)
                order.status = "paid"
                order.paid_at = now
                attempt.status = "succeeded"
                item = uow.session.scalar(select(OrderItem).where(OrderItem.order_id == order.id))
                if item is None:
                    raise ValidationError("Order has no purchasable item.")
                entitlement = uow.session.scalar(
                    select(Entitlement).where(
                        Entitlement.user_id == order.user_id,
                        Entitlement.course_id == item.course_id,
                    )
                )
                if entitlement is None:
                    uow.session.add(
                        Entitlement(
                            user_id=order.user_id,
                            course_id=item.course_id,
                            source_order_id=order.id,
                            status="active",
                            starts_at=now,
                        )
                    )
                enrollment = uow.session.scalar(
                    select(Enrollment).where(
                        Enrollment.user_id == order.user_id,
                        Enrollment.course_id == item.course_id,
                    )
                )
                if enrollment is None:
                    uow.session.add(
                        Enrollment(
                            user_id=order.user_id,
                            course_id=item.course_id,
                            status="active",
                            enrolled_at=now,
                        )
                    )
            elif result == "cancel" and order.status == "pending":
                order.status = "cancelled"
                attempt.status = "cancelled"
            elif result == "failure" and order.status == "pending":
                order.status = "failed"
                attempt.status = "failed"
            uow.commit()
            item = uow.session.scalar(select(OrderItem).where(OrderItem.order_id == order.id))
            course = uow.session.get(Course, item.course_id) if item else None
            return {
                "order_id": str(order.id),
                "status": order.status,
                "course_slug": course.slug if course else None,
            }

    def get_order(self, user_id: UUID, order_id: UUID) -> dict:
        with self.uow_factory() as uow:
            order = uow.session.scalar(
                select(Order).where(Order.id == order_id, Order.user_id == user_id)
            )
            if order is None:
                raise NotFoundError("Order does not exist.")
            return {
                "id": str(order.id),
                "status": order.status,
                "currency": order.currency,
                "total_minor": order.total_minor,
            }


def commerce_service_from_container(container) -> CommerceService:  # type: ignore[no-untyped-def]
    return CommerceService(
        lambda: SqlAlchemyUnitOfWork(container.database.session_factory),
        container.payment_gateway,
    )


def _require_user_profile(session, user_id: UUID) -> UserProfile:  # type: ignore[no-untyped-def]
    profile = session.scalar(select(UserProfile).where(UserProfile.user_id == user_id))
    if profile is None or not all((profile.full_name, profile.email, profile.phone)):
        raise ValidationError("Complete your basic information before placing an order.")
    return profile
