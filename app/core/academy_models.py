"""SQLAlchemy models for the Academy catalogue."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.models import Base, TimestampMixin, UuidPrimaryKeyMixin


class Course(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "courses"

    slug: Mapped[str] = mapped_column(String(160), unique=True, nullable=False)
    tier: Mapped[str] = mapped_column(String(20), nullable=False)
    field: Mapped[str] = mapped_column(String(60), nullable=False)
    level: Mapped[str] = mapped_column(String(30), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    owner_user_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    instructor_partner_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False),
        ForeignKey("partner_profiles.id", ondelete="SET NULL"),
        nullable=True,
    )
    youtube_playlist_id: Mapped[str | None] = mapped_column(String(100))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    translations: Mapped[list[CourseTranslation]] = relationship(
        back_populates="course", cascade="all, delete-orphan"
    )
    prices: Mapped[list[CoursePrice]] = relationship(
        back_populates="course", cascade="all, delete-orphan"
    )
    sections: Mapped[list[CourseSection]] = relationship(
        back_populates="course",
        cascade="all, delete-orphan",
        order_by="CourseSection.position",
    )
    outcomes: Mapped[list[LearningOutcome]] = relationship(
        back_populates="course",
        cascade="all, delete-orphan",
        order_by="LearningOutcome.position",
    )
    media: Mapped[list[CourseMedia]] = relationship(
        back_populates="course", cascade="all, delete-orphan", order_by="CourseMedia.position"
    )
    resources: Mapped[list[CourseResource]] = relationship(
        back_populates="course", cascade="all, delete-orphan"
    )
    instructor_partner = relationship("PartnerProfile")


class CourseTranslation(UuidPrimaryKeyMixin, Base):
    __tablename__ = "course_translations"
    __table_args__ = (UniqueConstraint("course_id", "locale"),)

    course_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), ForeignKey("courses.id"), nullable=False
    )
    locale: Mapped[str] = mapped_column(String(5), nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    description: Mapped[str] = mapped_column(Text, nullable=False)
    instructor_name: Mapped[str] = mapped_column(String(160), nullable=False)
    duration_label: Mapped[str] = mapped_column(String(80), nullable=False)
    course: Mapped[Course] = relationship(back_populates="translations")


class CoursePrice(UuidPrimaryKeyMixin, Base):
    __tablename__ = "course_prices"
    __table_args__ = (UniqueConstraint("course_id", "currency"),)

    course_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), ForeignKey("courses.id"), nullable=False
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    course: Mapped[Course] = relationship(back_populates="prices")


class CourseSection(UuidPrimaryKeyMixin, Base):
    __tablename__ = "course_sections"
    __table_args__ = (UniqueConstraint("course_id", "position"),)

    course_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), ForeignKey("courses.id"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    course: Mapped[Course] = relationship(back_populates="sections")
    translations: Mapped[list[SectionTranslation]] = relationship(
        back_populates="section", cascade="all, delete-orphan"
    )
    lessons: Mapped[list[Lesson]] = relationship(
        back_populates="section", cascade="all, delete-orphan", order_by="Lesson.position"
    )


class SectionTranslation(UuidPrimaryKeyMixin, Base):
    __tablename__ = "section_translations"
    __table_args__ = (UniqueConstraint("section_id", "locale"),)

    section_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), ForeignKey("course_sections.id"), nullable=False
    )
    locale: Mapped[str] = mapped_column(String(5), nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    section: Mapped[CourseSection] = relationship(back_populates="translations")


class Lesson(UuidPrimaryKeyMixin, Base):
    __tablename__ = "lessons"
    __table_args__ = (UniqueConstraint("section_id", "position"),)

    section_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), ForeignKey("course_sections.id"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    video_provider: Mapped[str] = mapped_column(String(30), nullable=False, default="youtube")
    video_reference: Mapped[str] = mapped_column(String(255), nullable=False)
    free_preview: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    section: Mapped[CourseSection] = relationship(back_populates="lessons")
    translations: Mapped[list[LessonTranslation]] = relationship(
        back_populates="lesson", cascade="all, delete-orphan"
    )


class LessonTranslation(UuidPrimaryKeyMixin, Base):
    __tablename__ = "lesson_translations"
    __table_args__ = (UniqueConstraint("lesson_id", "locale"),)

    lesson_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), ForeignKey("lessons.id"), nullable=False
    )
    locale: Mapped[str] = mapped_column(String(5), nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    lesson: Mapped[Lesson] = relationship(back_populates="translations")


class LearningOutcome(UuidPrimaryKeyMixin, Base):
    __tablename__ = "learning_outcomes"
    __table_args__ = (UniqueConstraint("course_id", "locale", "position"),)

    course_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), ForeignKey("courses.id"), nullable=False
    )
    locale: Mapped[str] = mapped_column(String(5), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(String(500), nullable=False)
    course: Mapped[Course] = relationship(back_populates="outcomes")


class CourseResource(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "course_resources"

    course_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), ForeignKey("courses.id"), nullable=False
    )
    lesson_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), ForeignKey("lessons.id")
    )
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    storage_path: Mapped[str | None] = mapped_column(String(500))
    external_url: Mapped[str | None] = mapped_column(String(1000))
    course: Mapped[Course] = relationship(back_populates="resources")


class CourseMedia(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "course_media"
    __table_args__ = (UniqueConstraint("course_id", "position"),)

    course_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), ForeignKey("courses.id"), nullable=False
    )
    lesson_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), ForeignKey("lessons.id")
    )
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    locale: Mapped[str | None] = mapped_column(String(5))
    mime_type: Mapped[str | None] = mapped_column(String(120))
    storage_path: Mapped[str | None] = mapped_column(String(500))
    external_url: Mapped[str | None] = mapped_column(String(1000))
    course: Mapped[Course] = relationship(back_populates="media")
