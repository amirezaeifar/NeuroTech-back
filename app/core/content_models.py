"""Persistence models for partner profiles and global-trade documents."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.models import Base, TimestampMixin, UuidPrimaryKeyMixin


class PartnerProfile(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "partner_profiles"

    user_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), ForeignKey("users.id"), unique=True
    )
    slug: Mapped[str] = mapped_column(String(160), unique=True, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    image_file_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), ForeignKey("stored_files.id")
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    translations: Mapped[list[PartnerTranslation]] = relationship(
        back_populates="partner", cascade="all, delete-orphan"
    )


class PartnerTranslation(UuidPrimaryKeyMixin, Base):
    __tablename__ = "partner_translations"
    __table_args__ = (UniqueConstraint("partner_id", "locale"),)

    partner_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), ForeignKey("partner_profiles.id"), nullable=False
    )
    locale: Mapped[str] = mapped_column(String(5), nullable=False)
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    qualification: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    location: Mapped[str] = mapped_column(String(240), nullable=False, default="")
    affiliation: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    bio: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    partner: Mapped[PartnerProfile] = relationship(back_populates="translations")


class TradeDocument(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "trade_documents"

    slug: Mapped[str] = mapped_column(String(190), unique=True, nullable=False)
    document_code: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    attachment_file_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), ForeignKey("stored_files.id")
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    translations: Mapped[list[TradeDocumentTranslation]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class TradeDocumentTranslation(UuidPrimaryKeyMixin, Base):
    __tablename__ = "trade_document_translations"
    __table_args__ = (UniqueConstraint("document_id", "locale"),)

    document_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), ForeignKey("trade_documents.id"), nullable=False
    )
    locale: Mapped[str] = mapped_column(String(5), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    doc_type: Mapped[str] = mapped_column(String(240), nullable=False)
    partner_name: Mapped[str] = mapped_column(String(240), nullable=False)
    category: Mapped[str] = mapped_column(String(240), nullable=False)
    location: Mapped[str | None] = mapped_column(String(240))
    region: Mapped[str | None] = mapped_column(String(240))
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    groups: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    document: Mapped[TradeDocument] = relationship(back_populates="translations")


class ManagedPage(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "managed_pages"

    page_key: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    translations: Mapped[list[ManagedPageTranslation]] = relationship(
        back_populates="page", cascade="all, delete-orphan"
    )


class ManagedPageTranslation(UuidPrimaryKeyMixin, Base):
    __tablename__ = "managed_page_translations"
    __table_args__ = (UniqueConstraint("page_id", "locale"),)

    page_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), ForeignKey("managed_pages.id"), nullable=False
    )
    locale: Mapped[str] = mapped_column(String(5), nullable=False)
    content: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    page: Mapped[ManagedPage] = relationship(back_populates="translations")
