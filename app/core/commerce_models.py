"""Persistence models for course orders, payments, and entitlements."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, TimestampMixin, UuidPrimaryKeyMixin


class Order(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "orders"

    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), ForeignKey("users.id"), nullable=False, index=True
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    total_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OrderItem(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "order_items"
    __table_args__ = (UniqueConstraint("order_id", "course_id"),)

    order_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), ForeignKey("orders.id"), nullable=False
    )
    course_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), ForeignKey("courses.id"), nullable=False
    )
    title_snapshot: Mapped[str] = mapped_column(String(240), nullable=False)
    unit_amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)


class PaymentAttempt(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "payment_attempts"

    order_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), ForeignKey("orders.id"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(30), nullable=False)
    provider_reference: Mapped[str] = mapped_column(String(160), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    redirect_url: Mapped[str] = mapped_column(Text, nullable=False)


class PaymentEvent(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "payment_events"

    attempt_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), ForeignKey("payment_attempts.id"), nullable=False
    )
    provider_event_id: Mapped[str] = mapped_column(String(190), nullable=False, unique=True)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)


class Entitlement(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "entitlements"
    __table_args__ = (UniqueConstraint("user_id", "course_id"),)

    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), ForeignKey("users.id"), nullable=False, index=True
    )
    course_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), ForeignKey("courses.id"), nullable=False, index=True
    )
    source_order_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), ForeignKey("orders.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

