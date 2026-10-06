"""Unified administrative view of course and product orders."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select

from app.core.auth_models import User, UserProfile
from app.core.catalog_models import (
    ProductOrder,
    ProductOrderItem,
    ProductPaymentAttempt,
)
from app.core.commerce_models import Order, OrderItem, PaymentAttempt
from app.core.unit_of_work import SqlAlchemyUnitOfWork
from app.domain.errors import ConflictError, NotFoundError, ValidationError

PRODUCT_FLOW = (
    "awaiting_confirmation",
    "confirmed",
    "shipped",
    "closed",
)


class AdminOrderService:
    def __init__(self, uow_factory) -> None:  # type: ignore[no-untyped-def]
        self.uow_factory = uow_factory

    def list_orders(
        self,
        kind: str | None = None,
        payment_status: str | None = None,
        fulfillment_status: str | None = None,
    ) -> dict:
        with self.uow_factory() as uow:
            rows: list[dict] = []
            if kind in {None, "course"}:
                rows.extend(self._course_orders(uow.session))
            if kind in {None, "product"}:
                rows.extend(self._product_orders(uow.session))
            counts = {
                status: sum(row["payment_status"] == status for row in rows)
                for status in ("pending", "paid", "cancelled", "failed")
            }
            if payment_status:
                rows = [row for row in rows if row["payment_status"] == payment_status]
            if fulfillment_status:
                rows = [
                    row for row in rows if row["fulfillment_status"] == fulfillment_status
                ]
            rows.sort(key=lambda row: row["created_at"], reverse=True)
            return {"items": rows, "total": len(rows), "payment_counts": counts}

    def advance_product(self, order_id: UUID, next_status: str) -> dict:
        if next_status not in PRODUCT_FLOW:
            raise ValidationError("Fulfillment status is invalid.")
        with self.uow_factory() as uow:
            order = uow.session.scalar(
                select(ProductOrder).where(ProductOrder.id == order_id).with_for_update()
            )
            if order is None:
                raise NotFoundError("Product order does not exist.")
            if order.status != "paid":
                raise ConflictError("Only paid product orders can enter fulfillment.")
            current = order.fulfillment_status
            if current == next_status:
                return self._product_payload(uow.session, order)
            try:
                current_index = PRODUCT_FLOW.index(current)
            except ValueError as error:
                raise ConflictError("Product order is not ready for fulfillment.") from error
            expected = PRODUCT_FLOW[min(current_index + 1, len(PRODUCT_FLOW) - 1)]
            if next_status != expected:
                raise ConflictError(f"The next fulfillment status must be {expected}.")
            order.fulfillment_status = next_status
            uow.commit()
            return self._product_payload(uow.session, order)

    def _course_orders(self, session) -> list[dict]:  # type: ignore[no-untyped-def]
        orders = list(session.scalars(select(Order).order_by(Order.created_at.desc())))
        return [self._course_payload(session, order) for order in orders]

    def _product_orders(self, session) -> list[dict]:  # type: ignore[no-untyped-def]
        orders = list(
            session.scalars(select(ProductOrder).order_by(ProductOrder.created_at.desc()))
        )
        return [self._product_payload(session, order) for order in orders]

    def _course_payload(self, session, order: Order) -> dict:  # type: ignore[no-untyped-def]
        items = list(session.scalars(select(OrderItem).where(OrderItem.order_id == order.id)))
        attempt = session.scalar(
            select(PaymentAttempt)
            .where(PaymentAttempt.order_id == order.id)
            .order_by(PaymentAttempt.created_at.desc())
        )
        return {
            **_base_payload(session, order, "course", attempt),
            "fulfillment_status": "access_granted" if order.status == "paid" else "automatic",
            "automatic": True,
            "shipping_address": None,
            "items": [
                {
                    "id": str(item.course_id),
                    "title": item.title_snapshot,
                    "quantity": 1,
                    "unit_amount_minor": item.unit_amount_minor,
                }
                for item in items
            ],
        }

    def _product_payload(self, session, order: ProductOrder) -> dict:  # type: ignore[no-untyped-def]
        items = list(
            session.scalars(
                select(ProductOrderItem).where(ProductOrderItem.order_id == order.id)
            )
        )
        attempt = session.scalar(
            select(ProductPaymentAttempt)
            .where(ProductPaymentAttempt.order_id == order.id)
            .order_by(ProductPaymentAttempt.created_at.desc())
        )
        return {
            **_base_payload(session, order, "product", attempt),
            "fulfillment_status": order.fulfillment_status,
            "automatic": False,
            "shipping_address": order.shipping_address,
            "items": [
                {
                    "id": str(item.product_id),
                    "title": item.title_snapshot,
                    "quantity": item.quantity,
                    "unit_amount_minor": item.unit_amount_minor,
                }
                for item in items
            ],
        }


def _base_payload(session, order, kind: str, attempt) -> dict:  # type: ignore[no-untyped-def]
    profile = session.scalar(select(UserProfile).where(UserProfile.user_id == order.user_id))
    user = session.get(User, order.user_id)
    email = profile.email if profile else (user.emails[0].email if user and user.emails else "")
    phone = profile.phone if profile else (user.phones[0].phone if user and user.phones else "")
    return {
        "id": str(order.id),
        "kind": kind,
        "payment_status": _payment_status(order.status, attempt.status if attempt else None),
        "payment_provider": attempt.provider if attempt else None,
        "currency": order.currency,
        "total_minor": order.total_minor,
        "created_at": order.created_at.isoformat(),
        "updated_at": order.updated_at.isoformat(),
        "paid_at": order.paid_at.isoformat() if order.paid_at else None,
        "customer": {
            "id": str(order.user_id),
            "name": profile.full_name if profile else (user.display_name if user else ""),
            "email": email,
            "phone": phone,
        },
    }


def _payment_status(order_status: str, attempt_status: str | None) -> str:
    if order_status == "paid" or attempt_status == "succeeded":
        return "paid"
    if order_status == "cancelled" or attempt_status == "cancelled":
        return "cancelled"
    if order_status == "failed" or attempt_status == "failed":
        return "failed"
    return "pending"


def admin_order_service_from_container(container) -> AdminOrderService:  # type: ignore[no-untyped-def]
    return AdminOrderService(lambda: SqlAlchemyUnitOfWork(container.database.session_factory))
