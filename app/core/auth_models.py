"""SQLAlchemy persistence models for identity and sessions."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.models import Base, TimestampMixin, UuidPrimaryKeyMixin, utc_now
from app.domain.auth import Role, UserStatus


class User(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"

    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default=Role.USER.value)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=UserStatus.ACTIVE.value)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_active_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    avatar_file_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True, native_uuid=False))

    emails: Mapped[list[EmailIdentity]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    phones: Mapped[list[PhoneIdentity]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    credential: Mapped[PasswordCredential | None] = relationship(
        back_populates="user", cascade="all, delete-orphan", uselist=False
    )


class UserProfile(UuidPrimaryKeyMixin, TimestampMixin, Base):
    """Contact and delivery information owned by a user, independent of checkout."""

    __tablename__ = "user_profiles"
    __table_args__ = (UniqueConstraint("user_id"),)

    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), ForeignKey("users.id"), nullable=False, index=True
    )
    full_name: Mapped[str] = mapped_column(String(160), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    phone: Mapped[str] = mapped_column(String(24), nullable=False)
    national_id: Mapped[str | None] = mapped_column(String(20))
    address: Mapped[str | None] = mapped_column(String(1000))
    city: Mapped[str | None] = mapped_column(String(120))
    postal_code: Mapped[str | None] = mapped_column(String(20))


class EmailIdentity(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "email_identities"

    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False),
        ForeignKey("users.id"),
        nullable=False,
    )
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user: Mapped[User] = relationship(back_populates="emails")


class PhoneIdentity(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "phone_identities"

    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), ForeignKey("users.id"), nullable=False
    )
    phone: Mapped[str] = mapped_column(String(24), unique=True, nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user: Mapped[User] = relationship(back_populates="phones")


class PasswordCredential(Base):
    __tablename__ = "password_credentials"

    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), ForeignKey("users.id"), primary_key=True
    )
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )
    user: Mapped[User] = relationship(back_populates="credential")


class AuthSession(UuidPrimaryKeyMixin, Base):
    __tablename__ = "auth_sessions"

    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False),
        ForeignKey("users.id"),
        nullable=False,
        index=True,
    )
    family_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), nullable=False, default=uuid4
    )
    refresh_jti: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    absolute_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ip_address: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(512))


class Invitation(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "invitations"
    __table_args__ = (UniqueConstraint("token_digest", name="uq_invitation_token_digest"),)

    email: Mapped[str] = mapped_column(String(320), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    token_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditLog(UuidPrimaryKeyMixin, Base):
    __tablename__ = "audit_logs"

    actor_user_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), ForeignKey("users.id"), nullable=True
    )
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    target_type: Mapped[str] = mapped_column(String(100), nullable=False)
    target_id: Mapped[str | None] = mapped_column(String(64))
    details_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Favorite(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "favorites"
    __table_args__ = (UniqueConstraint("user_id", "item_type", "item_id"),)

    user_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True, native_uuid=False), ForeignKey("users.id"), nullable=False, index=True)
    item_type: Mapped[str] = mapped_column(String(20), nullable=False)
    item_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True, native_uuid=False), nullable=False)
