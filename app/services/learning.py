"""Enrollment, entitlement, progress, and discussion use cases."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.core.academy_models import Course, CourseSection, Lesson
from app.core.auth_models import User
from app.core.commerce_models import Entitlement
from app.core.learning_models import (
    CourseComment,
    Enrollment,
    LessonProgress,
    ModerationDecision,
)
from app.core.unit_of_work import SqlAlchemyUnitOfWork
from app.domain.errors import AuthorizationError, NotFoundError, ValidationError


class LearningService:
    def __init__(self, uow_factory) -> None:  # type: ignore[no-untyped-def]
        self.uow_factory = uow_factory

    def enroll_free(self, user_id: UUID, slug: str) -> dict:
        with self.uow_factory() as uow:
            course = uow.session.scalar(
                select(Course).where(
                    Course.slug == slug,
                    Course.tier == "free",
                    Course.published_at.is_not(None),
                    Course.archived_at.is_(None),
                )
            )
            if course is None:
                raise ValidationError("Only a published free course can be enrolled directly.")
            enrollment = uow.session.scalar(
                select(Enrollment).where(
                    Enrollment.user_id == user_id, Enrollment.course_id == course.id
                )
            )
            if enrollment is None:
                enrollment = Enrollment(
                    user_id=user_id,
                    course_id=course.id,
                    status="active",
                    enrolled_at=datetime.now(UTC),
                )
                uow.session.add(enrollment)
                uow.commit()
            return _enrollment_payload(enrollment, course.slug)

    def access(self, user_id: UUID, slug: str, locale: str = "en") -> dict:
        selected_locale = locale if locale in {"en", "fa"} else "en"
        with self.uow_factory() as uow:
            course = uow.session.scalar(
                select(Course)
                .options(
                    selectinload(Course.sections)
                    .selectinload(CourseSection.lessons)
                    .selectinload(Lesson.translations)
                )
                .where(Course.slug == slug, Course.archived_at.is_(None))
            )
            if course is None:
                raise NotFoundError("Course does not exist.")
            enrollment = _enrollment(uow.session, user_id, course.id)
            entitled = course.tier == "free" or _has_entitlement(uow.session, user_id, course.id)
            lesson_total = (
                uow.session.scalar(
                    select(func.count())
                    .select_from(Lesson)
                    .join(CourseSection, CourseSection.id == Lesson.section_id)
                    .where(CourseSection.course_id == course.id)
                )
                or 0
            )
            progress_items: list[LessonProgress] = []
            if enrollment:
                progress_items = list(
                    uow.session.scalars(
                        select(LessonProgress).where(LessonProgress.enrollment_id == enrollment.id)
                    )
                )
            progress_by_lesson = {item.lesson_id: item for item in progress_items}
            can_access = bool(enrollment and enrollment.status == "active" and entitled)
            lessons = []
            if can_access:
                for section in sorted(course.sections, key=lambda item: item.position):
                    for lesson in sorted(section.lessons, key=lambda item: item.position):
                        progress = progress_by_lesson.get(lesson.id)
                        lessons.append(
                            {
                                "id": str(lesson.id),
                                "title": _localized_title(lesson.translations, selected_locale),
                                "video_provider": lesson.video_provider,
                                "video_reference": lesson.video_reference,
                                "duration_seconds": lesson.duration_seconds,
                                "position_seconds": progress.position_seconds if progress else 0,
                                "completed": bool(progress and progress.completed_at is not None),
                            }
                        )
            return {
                "course_id": str(course.id),
                "slug": slug,
                "enrolled": bool(enrollment and enrollment.status == "active"),
                "entitled": entitled,
                "can_access": can_access,
                "lesson_total": lesson_total,
                "completed_lessons": sum(item.completed_at is not None for item in progress_items),
                "lessons": lessons,
            }

    def pathway(self, user_id: UUID, locale: str) -> dict:
        selected_locale = locale if locale in {"en", "fa"} else "en"
        with self.uow_factory() as uow:
            user = uow.session.get(User, user_id)
            if user is None:
                raise NotFoundError("User does not exist.")
            enrollments = list(
                uow.session.scalars(
                    select(Enrollment)
                    .where(Enrollment.user_id == user_id, Enrollment.status == "active")
                    .order_by(Enrollment.enrolled_at)
                )
            )
            result = []
            current_node_id = None
            for enrollment in enrollments:
                course = uow.session.scalar(
                    select(Course)
                    .options(
                        selectinload(Course.translations),
                        selectinload(Course.sections).selectinload(CourseSection.translations),
                        selectinload(Course.sections)
                        .selectinload(CourseSection.lessons)
                        .selectinload(Lesson.translations),
                    )
                    .where(
                        Course.id == enrollment.course_id,
                        Course.archived_at.is_(None),
                    )
                )
                if course is None:
                    continue
                completed_ids = set(
                    uow.session.scalars(
                        select(LessonProgress.lesson_id).where(
                            LessonProgress.enrollment_id == enrollment.id,
                            LessonProgress.completed_at.is_not(None),
                        )
                    )
                )
                modules = []
                total = 0
                for section in course.sections:
                    lesson_ids = {lesson.id for lesson in section.lessons}
                    total += len(lesson_ids)
                    done = len(lesson_ids & completed_ids)
                    status = (
                        "completed"
                        if lesson_ids and done == len(lesson_ids)
                        else "in-progress"
                        if done
                        else "locked"
                    )
                    module_id = str(section.id)
                    if current_node_id is None and status != "completed":
                        current_node_id = module_id
                        status = "in-progress"
                    modules.append(
                        {
                            "id": module_id,
                            "title": _localized_title(section.translations, selected_locale),
                            "status": status,
                        }
                    )
                course_status = (
                    "completed" if total and len(completed_ids) == total else "in-progress"
                )
                result.append(
                    {
                        "id": str(course.id),
                        "slug": course.slug,
                        "code": course.slug[:3].upper() + "-101",
                        "title": _localized_title(course.translations, selected_locale),
                        "field": course.field,
                        "status": course_status,
                        "modules": modules,
                    }
                )
            return {
                "user": user.display_name,
                "currentNodeId": current_node_id,
                "courses": result,
            }

    def save_progress(
        self,
        user_id: UUID,
        lesson_id: UUID,
        *,
        position_seconds: int,
        completed: bool,
    ) -> dict:
        if position_seconds < 0:
            raise ValidationError("Playback position cannot be negative.")
        with self.uow_factory() as uow:
            lesson = uow.session.get(Lesson, lesson_id)
            if lesson is None:
                raise NotFoundError("Lesson does not exist.")
            enrollment = _enrollment(
                uow.session, user_id, lesson.section.course_id, for_update=True
            )
            if enrollment is None or enrollment.status != "active":
                raise AuthorizationError("An active enrollment is required.")
            course = uow.session.get(Course, lesson.section.course_id)
            if course is None or course.archived_at is not None:
                raise NotFoundError("Course does not exist.")
            if course.tier == "premium" and not _has_entitlement(uow.session, user_id, course.id):
                raise AuthorizationError("A course entitlement is required.")
            progress = uow.session.scalar(
                select(LessonProgress).where(
                    LessonProgress.enrollment_id == enrollment.id,
                    LessonProgress.lesson_id == lesson.id,
                )
            )
            if progress is None:
                progress = LessonProgress(
                    enrollment_id=enrollment.id,
                    lesson_id=lesson.id,
                    position_seconds=position_seconds,
                )
                uow.session.add(progress)
            else:
                progress.position_seconds = position_seconds
            if completed and progress.completed_at is None:
                progress.completed_at = datetime.now(UTC)
            uow.commit()
            return {
                "lesson_id": str(lesson.id),
                "position_seconds": progress.position_seconds,
                "completed": progress.completed_at is not None,
            }

    def add_comment(self, user_id: UUID, slug: str, body: str) -> dict:
        normalized = " ".join(body.split())
        if not 2 <= len(normalized) <= 4000:
            raise ValidationError("Comment must be between 2 and 4000 characters.")
        with self.uow_factory() as uow:
            course = uow.session.scalar(
                select(Course).where(Course.slug == slug, Course.archived_at.is_(None))
            )
            if course is None:
                raise NotFoundError("Course does not exist.")
            enrollment = _enrollment(uow.session, user_id, course.id)
            if enrollment is None or enrollment.status != "active":
                raise AuthorizationError("Enrollment is required to comment.")
            comment = CourseComment(
                user_id=user_id, course_id=course.id, body=normalized, status="pending"
            )
            uow.session.add(comment)
            uow.commit()
            return _comment_payload(comment)

    def comments(self, slug: str) -> list[dict]:
        with self.uow_factory() as uow:
            rows = uow.session.execute(
                select(CourseComment, User.display_name)
                .join(Course, Course.id == CourseComment.course_id)
                .join(User, User.id == CourseComment.user_id)
                .where(
                    Course.slug == slug,
                    Course.archived_at.is_(None),
                    Course.published_at.is_not(None),
                    CourseComment.status == "approved",
                )
                .order_by(CourseComment.created_at)
            ).all()
            return [
                {**_comment_payload(comment), "author": display_name}
                for comment, display_name in rows
            ]

    def pending_comments(self) -> list[dict]:
        with self.uow_factory() as uow:
            rows = uow.session.execute(
                select(CourseComment, User.display_name, Course.slug)
                .join(Course, Course.id == CourseComment.course_id)
                .join(User, User.id == CourseComment.user_id)
                .where(CourseComment.status == "pending")
                .order_by(CourseComment.created_at)
            ).all()
            return [
                {
                    **_comment_payload(comment),
                    "author": display_name,
                    "course_slug": slug,
                }
                for comment, display_name, slug in rows
            ]

    def moderate(
        self, moderator_id: UUID, comment_id: UUID, decision: str, reason: str | None
    ) -> dict:
        if decision not in {"approved", "rejected"}:
            raise ValidationError("Decision must be approved or rejected.")
        with self.uow_factory() as uow:
            comment = uow.session.get(CourseComment, comment_id)
            if comment is None:
                raise NotFoundError("Comment does not exist.")
            comment.status = decision
            uow.session.add(
                ModerationDecision(
                    comment_id=comment.id,
                    moderator_id=moderator_id,
                    decision=decision,
                    reason=(reason or "").strip() or None,
                )
            )
            uow.commit()
            return _comment_payload(comment)


def _enrollment(  # type: ignore[no-untyped-def]
    session, user_id: UUID, course_id: UUID, *, for_update: bool = False
) -> Enrollment | None:
    statement = select(Enrollment).where(
        Enrollment.user_id == user_id, Enrollment.course_id == course_id
    )
    if for_update:
        statement = statement.with_for_update()
    return session.scalar(statement)


def _has_entitlement(session, user_id: UUID, course_id: UUID) -> bool:  # type: ignore[no-untyped-def]
    now = datetime.now(UTC)
    entitlement = session.scalar(
        select(Entitlement).where(
            Entitlement.user_id == user_id,
            Entitlement.course_id == course_id,
            Entitlement.status == "active",
        )
    )
    if entitlement is None:
        return False
    expires_at = entitlement.expires_at
    if expires_at is None:
        return True
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    return expires_at > now


def _enrollment_payload(enrollment: Enrollment, slug: str) -> dict:
    return {
        "id": str(enrollment.id),
        "course_slug": slug,
        "status": enrollment.status,
        "enrolled_at": enrollment.enrolled_at.isoformat(),
    }


def _comment_payload(comment: CourseComment) -> dict:
    return {
        "id": str(comment.id),
        "body": comment.body,
        "status": comment.status,
        "created_at": comment.created_at.isoformat(),
    }


def _localized_title(translations: list, locale: str) -> str:  # type: ignore[type-arg]
    selected = next((item for item in translations if item.locale == locale), None)
    fallback = next((item for item in translations if item.locale == "en"), None)
    return (selected or fallback or translations[0]).title if translations else ""


def learning_service_from_container(container) -> LearningService:  # type: ignore[no-untyped-def]
    return LearningService(lambda: SqlAlchemyUnitOfWork(container.database.session_factory))
