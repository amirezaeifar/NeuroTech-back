"""Persistence models for enrollment, progress, and course discussions."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, TimestampMixin, UuidPrimaryKeyMixin


class Enrollment(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "enrollments"
    __table_args__ = (UniqueConstraint("user_id", "course_id"),)

    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), ForeignKey("users.id"), nullable=False, index=True
    )
    course_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), ForeignKey("courses.id"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    enrolled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class LessonProgress(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "lesson_progress"
    __table_args__ = (UniqueConstraint("enrollment_id", "lesson_id"),)

    enrollment_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), ForeignKey("enrollments.id"), nullable=False
    )
    lesson_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), ForeignKey("lessons.id"), nullable=False
    )
    position_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CourseComment(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "course_comments"

    course_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), ForeignKey("courses.id"), nullable=False, index=True
    )
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), ForeignKey("users.id"), nullable=False, index=True
    )
    lesson_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False),
        ForeignKey("lessons.id", ondelete="SET NULL"),
        index=True,
    )
    parent_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), ForeignKey("course_comments.id"), index=True
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)


class ModerationDecision(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "moderation_decisions"

    comment_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), ForeignKey("course_comments.id"), nullable=False
    )
    moderator_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), ForeignKey("users.id"), nullable=False
    )
    decision: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(500))
