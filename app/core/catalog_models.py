"""Persistence models for products, local files, product commerce, and events."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.models import Base, TimestampMixin, UuidPrimaryKeyMixin, utc_now


class StoredFile(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "stored_files"
    uploader_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), ForeignKey("users.id"), nullable=False
    )
    storage_key: Mapped[str] = mapped_column(String(500), unique=True, nullable=False)
    original_name: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(120), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    is_public: Mapped[bool] = mapped_column(nullable=False, default=True)


class ProductCategory(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "product_categories"
    slug: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    translations: Mapped[list[ProductCategoryTranslation]] = relationship(
        back_populates="category", cascade="all, delete-orphan"
    )
    products: Mapped[list[Product]] = relationship(back_populates="category")


class ProductCategoryTranslation(UuidPrimaryKeyMixin, Base):
    __tablename__ = "product_category_translations"
    __table_args__ = (UniqueConstraint("category_id", "locale"),)
    category_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), ForeignKey("product_categories.id"), nullable=False
    )
    locale: Mapped[str] = mapped_column(String(5), nullable=False)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    category: Mapped[ProductCategory] = relationship(back_populates="translations")


class Product(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "products"
    category_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False),
        ForeignKey("product_categories.id"),
        nullable=False,
        index=True,
    )
    slug: Mapped[str] = mapped_column(String(160), unique=True, nullable=False)
    sku: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    sale_mode: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    stock_quantity: Mapped[int | None] = mapped_column(Integer)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    category: Mapped[ProductCategory] = relationship(back_populates="products")
    translations: Mapped[list[ProductTranslation]] = relationship(
        back_populates="product", cascade="all, delete-orphan"
    )
    prices: Mapped[list[ProductPrice]] = relationship(
        back_populates="product", cascade="all, delete-orphan"
    )
    media: Mapped[list[ProductMedia]] = relationship(
        back_populates="product", cascade="all, delete-orphan", order_by="ProductMedia.position"
    )


class ProductTranslation(UuidPrimaryKeyMixin, Base):
    __tablename__ = "product_translations"
    __table_args__ = (UniqueConstraint("product_id", "locale"),)
    product_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), ForeignKey("products.id"), nullable=False
    )
    locale: Mapped[str] = mapped_column(String(5), nullable=False)
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    short_description: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    product: Mapped[Product] = relationship(back_populates="translations")


class ProductPrice(UuidPrimaryKeyMixin, Base):
    __tablename__ = "product_prices"
    __table_args__ = (UniqueConstraint("product_id", "currency"),)
    product_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), ForeignKey("products.id"), nullable=False
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    product: Mapped[Product] = relationship(back_populates="prices")


class ProductMedia(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "product_media"
    __table_args__ = (UniqueConstraint("product_id", "position"),)
    product_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), ForeignKey("products.id"), nullable=False
    )
    stored_file_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), ForeignKey("stored_files.id")
    )
    external_url: Mapped[str | None] = mapped_column(String(1000))
    alt_text: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    product: Mapped[Product] = relationship(back_populates="media")


class ShoppingCart(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "shopping_carts"
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), ForeignKey("users.id"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active", index=True)
    items: Mapped[list[CartItem]] = relationship(
        back_populates="cart", cascade="all, delete-orphan"
    )


class CartItem(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "cart_items"
    __table_args__ = (UniqueConstraint("cart_id", "product_id"),)
    cart_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), ForeignKey("shopping_carts.id"), nullable=False
    )
    product_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), ForeignKey("products.id"), nullable=False
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    cart: Mapped[ShoppingCart] = relationship(back_populates="items")


class ProductInquiry(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "product_inquiries"
    product_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), ForeignKey("products.id"), nullable=False, index=True
    )
    user_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), ForeignKey("users.id"), index=True
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    phone: Mapped[str | None] = mapped_column(String(32))
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)
    response: Mapped[str | None] = mapped_column(Text)
    responded_by: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), ForeignKey("users.id")
    )
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProductOrder(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "product_orders"
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), ForeignKey("users.id"), nullable=False, index=True
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    total_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)
    fulfillment_status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="awaiting_payment", index=True
    )
    shipping_address: Mapped[dict] = mapped_column(JSON, nullable=False)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProductOrderItem(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "product_order_items"
    __table_args__ = (UniqueConstraint("order_id", "product_id"),)
    order_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False),
        ForeignKey("product_orders.id"),
        nullable=False,
        index=True,
    )
    product_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), ForeignKey("products.id"), nullable=False
    )
    title_snapshot: Mapped[str] = mapped_column(String(240), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)


class ProductPaymentAttempt(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "product_payment_attempts"
    order_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False),
        ForeignKey("product_orders.id"),
        nullable=False,
        index=True,
    )
    provider: Mapped[str] = mapped_column(String(30), nullable=False)
    provider_reference: Mapped[str] = mapped_column(String(160), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    redirect_url: Mapped[str] = mapped_column(Text, nullable=False)


class ProductPaymentEvent(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "product_payment_events"
    attempt_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False),
        ForeignKey("product_payment_attempts.id"),
        nullable=False,
    )
    provider_event_id: Mapped[str] = mapped_column(String(190), nullable=False, unique=True)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)


class Event(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "events"
    slug: Mapped[str] = mapped_column(String(160), unique=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    timezone: Mapped[str] = mapped_column(String(60), nullable=False, default="Asia/Tehran")
    capacity: Mapped[int | None] = mapped_column(Integer)
    online_url: Mapped[str | None] = mapped_column(String(1000))
    venue: Mapped[str | None] = mapped_column(String(500))
    cover_url: Mapped[str | None] = mapped_column(String(1000))
    agenda_steps: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    current_step: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    live_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    step_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    step_durations: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    chat_enabled: Mapped[bool] = mapped_column(nullable=False, default=True)
    questions_enabled: Mapped[bool] = mapped_column(nullable=False, default=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    translations: Mapped[list[EventTranslation]] = relationship(
        back_populates="event", cascade="all, delete-orphan"
    )
    speakers: Mapped[list[EventSpeaker]] = relationship(
        back_populates="event", cascade="all, delete-orphan"
    )


class EventTranslation(UuidPrimaryKeyMixin, Base):
    __tablename__ = "event_translations"
    __table_args__ = (UniqueConstraint("event_id", "locale"),)
    event_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), ForeignKey("events.id"), nullable=False
    )
    locale: Mapped[str] = mapped_column(String(5), nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    summary: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    host_label: Mapped[str] = mapped_column(String(240), nullable=False)
    content: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    event: Mapped[Event] = relationship(back_populates="translations")


class EventReservation(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "event_reservations"
    __table_args__ = (UniqueConstraint("event_id", "user_id"),)
    event_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), ForeignKey("events.id"), nullable=False, index=True
    )
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), ForeignKey("users.id"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="confirmed", index=True)
    reserved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class EventSpeaker(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "event_speakers"
    __table_args__ = (
        UniqueConstraint("event_id", "user_id"),
        UniqueConstraint("event_id", "partner_id"),
        UniqueConstraint("event_id", "position"),
    )
    event_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False),
        ForeignKey("events.id"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False),
        ForeignKey("users.id"),
        nullable=True,
        index=True,
    )
    partner_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), ForeignKey("partner_profiles.id"), index=True
    )
    role_label: Mapped[str] = mapped_column(String(160), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    event: Mapped[Event] = relationship(back_populates="speakers")


class EventLivePresence(UuidPrimaryKeyMixin, Base):
    __tablename__ = "event_live_presence"
    __table_args__ = (UniqueConstraint("event_id", "user_id"),)
    event_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), ForeignKey("events.id"), nullable=False, index=True
    )
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), ForeignKey("users.id"), nullable=False
    )
    country_code: Mapped[str | None] = mapped_column(String(2))
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class EventLiveMessage(UuidPrimaryKeyMixin, Base):
    __tablename__ = "event_live_messages"
    event_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), ForeignKey("events.id"), nullable=False, index=True
    )
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), ForeignKey("users.id"), nullable=False
    )
    body: Mapped[str] = mapped_column(String(1000), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class EventLiveQuestion(UuidPrimaryKeyMixin, Base):
    __tablename__ = "event_live_questions"
    event_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), ForeignKey("events.id"), nullable=False, index=True
    )
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), ForeignKey("users.id"), nullable=False
    )
    body: Mapped[str] = mapped_column(String(1000), nullable=False)
    answered: Mapped[bool] = mapped_column(nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class EventLiveVote(UuidPrimaryKeyMixin, Base):
    __tablename__ = "event_live_votes"
    __table_args__ = (UniqueConstraint("question_id", "user_id"),)
    question_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False),
        ForeignKey("event_live_questions.id"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), ForeignKey("users.id"), nullable=False
    )
