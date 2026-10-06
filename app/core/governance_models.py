"""Approval workflow, blog, and persisted platform settings models."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.models import Base, TimestampMixin, UuidPrimaryKeyMixin


class ApprovalRequest(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "approval_requests"
    __table_args__ = (
        Index("ix_approval_requests_status_updated", "status", "updated_at"),
        Index("ix_approval_requests_resource", "resource_type", "resource_key"),
    )

    resource_type: Mapped[str] = mapped_column(String(40), nullable=False)
    resource_key: Mapped[str] = mapped_column(String(200), nullable=False)
    resource_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True, native_uuid=False))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    requested_by_user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), ForeignKey("users.id"), nullable=False
    )
    last_requested_by_user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), ForeignKey("users.id"), nullable=False
    )
    reviewed_by_user_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), ForeignKey("users.id")
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_note: Mapped[str | None] = mapped_column(Text)
    changes_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")


class BlogPost(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "blog_posts"

    slug: Mapped[str] = mapped_column(String(180), unique=True, nullable=False)
    author_user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), ForeignKey("users.id"), nullable=False
    )
    cover_url: Mapped[str | None] = mapped_column(String(1000))
    category: Mapped[str] = mapped_column(String(20), nullable=False, default="blog", index=True)
    cover_alt: Mapped[str] = mapped_column(String(240), nullable=False, default="")
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    translations: Mapped[list[BlogPostTranslation]] = relationship(
        back_populates="post", cascade="all, delete-orphan"
    )


class BlogPostTranslation(UuidPrimaryKeyMixin, Base):
    __tablename__ = "blog_post_translations"
    __table_args__ = (UniqueConstraint("post_id", "locale"),)

    post_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), ForeignKey("blog_posts.id"), nullable=False
    )
    locale: Mapped[str] = mapped_column(String(5), nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    excerpt: Mapped[str] = mapped_column(String(600), nullable=False, default="")
    body: Mapped[str] = mapped_column(Text, nullable=False)
    seo_title: Mapped[str] = mapped_column(String(240), nullable=False, default="")
    seo_description: Mapped[str] = mapped_column(String(600), nullable=False, default="")
    seo_keywords: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    post: Mapped[BlogPost] = relationship(back_populates="translations")


class SiteSetting(Base):
    __tablename__ = "site_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value_json: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_by_user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), ForeignKey("users.id"), nullable=False
    )
