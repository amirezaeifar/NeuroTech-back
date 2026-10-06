"""Enrollment, entitlement, progress, and discussion use cases."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.orm import selectinload

from app.core.academy_models import Course, CourseSection, Lesson
from app.core.auth_models import User
from app.core.commerce_models import Entitlement
from app.core.content_models import PartnerProfile
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
                    selectinload(Course.resources),
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
                ordered_lessons = [
                    lesson
                    for section in sorted(course.sections, key=lambda item: item.position)
                    for lesson in sorted(section.lessons, key=lambda item: item.position)
                ]
                previous_completed = True
                for index, lesson in enumerate(ordered_lessons):
                    progress = progress_by_lesson.get(lesson.id)
                    unlocked = index == 0 or previous_completed
                    lessons.append(
                        {
                            "id": str(lesson.id),
                            "title": _localized_title(lesson.translations, selected_locale),
                            "video_provider": lesson.video_provider if unlocked else None,
                            "video_reference": lesson.video_reference if unlocked else None,
                            "duration_seconds": lesson.duration_seconds,
                            "position_seconds": progress.position_seconds if progress else 0,
                            "completed": bool(progress and progress.completed_at is not None),
                            **({"locked": True} if not unlocked else {}),
                        }
                    )
                    previous_completed = bool(progress and progress.completed_at is not None)
            completed_lessons = sum(item.completed_at is not None for item in progress_items)
            return {
                "course_id": str(course.id),
                "slug": slug,
                "youtube_playlist_id": course.youtube_playlist_id,
                "enrolled": bool(enrollment and enrollment.status == "active"),
                "entitled": entitled,
                "can_access": can_access,
                "lesson_total": lesson_total,
                "completed_lessons": completed_lessons,
                "progress_percent": round(
                    completed_lessons / lesson_total * 100
                )
                if lesson_total
                else 0,
                "lessons": lessons,
                "resources": [
                    {
                        "name": item.name,
                        "kind": item.kind,
                        "url": item.external_url or item.storage_path,
                        "locked": False,
                    }
                    for item in course.resources
                ]
                if can_access
                else [],
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
            enrollment_by_course = {item.course_id: item for item in enrollments}
            courses = list(
                uow.session.scalars(
                    select(Course)
                    .options(
                        selectinload(Course.translations),
                        selectinload(Course.sections)
                        .selectinload(CourseSection.lessons)
                        .selectinload(Lesson.translations),
                    )
                    .where(
                        Course.published_at.is_not(None),
                        Course.archived_at.is_(None),
                    )
                    .order_by(Course.position, Course.created_at)
                ).unique()
            )
            result = []
            active_candidates: list[tuple[datetime, str]] = []
            for course in courses:
                enrollment = enrollment_by_course.get(course.id)
                ordered_lessons = [
                    lesson
                    for section in sorted(course.sections, key=lambda item: item.position)
                    for lesson in sorted(section.lessons, key=lambda item: item.position)
                ]
                progress_items = [] if enrollment is None else list(
                    uow.session.scalars(
                        select(LessonProgress)
                        .where(
                            LessonProgress.enrollment_id == enrollment.id,
                            LessonProgress.completed_at.is_not(None),
                        )
                        .order_by(LessonProgress.completed_at)
                    )
                )
                completed_ids = {item.lesson_id for item in progress_items}
                modules = [
                    {
                        "id": str(lesson.id),
                        "lesson_id": str(lesson.id),
                        "step": index + 1,
                        "title": _localized_title(lesson.translations, selected_locale),
                        "status": "completed",
                    }
                    for index, lesson in enumerate(ordered_lessons)
                    if lesson.id in completed_ids
                ]
                if enrollment is None:
                    course_status = "locked"
                elif modules:
                    course_status = (
                        "completed" if len(modules) == len(ordered_lessons) else "in-progress"
                    )
                    latest = max(progress_items, key=lambda item: item.updated_at)
                    active_candidates.append((latest.updated_at, str(latest.lesson_id)))
                else:
                    course_status = "in-progress"
                    active_candidates.append((enrollment.enrolled_at, str(course.id)))
                result.append(
                    {
                        "id": str(course.id),
                        "slug": course.slug,
                        "code": course.slug[:3].upper() + "-101",
                        "title": _localized_title(course.translations, selected_locale),
                        "field": course.field,
                        "status": course_status,
                        "enrolled": enrollment is not None,
                        "lesson_total": len(ordered_lessons),
                        "completed_lessons": len(modules),
                        "progress_percent": round(len(modules) / len(ordered_lessons) * 100)
                        if ordered_lessons
                        else 0,
                        "modules": modules,
                    }
                )
            current_node_id = max(
                active_candidates, default=(None, None), key=lambda item: item[0]
            )[1]
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
            ordered_lessons = list(
                uow.session.scalars(
                    select(Lesson)
                    .join(CourseSection, CourseSection.id == Lesson.section_id)
                    .where(CourseSection.course_id == course.id)
                    .order_by(CourseSection.position, Lesson.position)
                )
            )
            lesson_index = next(
                (index for index, item in enumerate(ordered_lessons) if item.id == lesson.id), None
            )
            if lesson_index is None:
                raise NotFoundError("Lesson does not exist.")
            if lesson_index:
                previous_ids = [item.id for item in ordered_lessons[:lesson_index]]
                completed_previous = set(
                    uow.session.scalars(
                        select(LessonProgress.lesson_id).where(
                            LessonProgress.enrollment_id == enrollment.id,
                            LessonProgress.lesson_id.in_(previous_ids),
                            LessonProgress.completed_at.is_not(None),
                        )
                    )
                )
                if len(completed_previous) != len(previous_ids):
                    raise AuthorizationError(
                        "Complete the previous lesson before opening this one."
                    )
            safe_position = min(position_seconds, lesson.duration_seconds or position_seconds)
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
                    position_seconds=safe_position,
                )
                uow.session.add(progress)
            else:
                progress.position_seconds = max(progress.position_seconds, safe_position)
            watched_enough = bool(
                lesson.duration_seconds > 0
                and safe_position >= (lesson.duration_seconds * 9 + 9) // 10
            )
            if watched_enough and progress.completed_at is None:
                progress.completed_at = datetime.now(UTC)
            uow.commit()
            return {
                "lesson_id": str(lesson.id),
                "position_seconds": progress.position_seconds,
                "completed": progress.completed_at is not None,
            }

    def add_comment(
        self, user_id: UUID, slug: str, body: str, lesson_id: UUID | None = None
    ) -> dict:
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
            if lesson_id is not None:
                lesson = uow.session.scalar(
                    select(Lesson)
                    .join(CourseSection, CourseSection.id == Lesson.section_id)
                    .where(Lesson.id == lesson_id, CourseSection.course_id == course.id)
                )
                if lesson is None:
                    raise ValidationError("The selected lesson does not belong to this course.")
            comment = CourseComment(
                user_id=user_id,
                course_id=course.id,
                lesson_id=lesson_id,
                body=normalized,
                status="pending",
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
        return self.admin_comments(status="pending", page=1, page_size=100)["data"]

    def moderation_courses(self, specialist_id: UUID | None = None) -> list[dict]:
        with self.uow_factory() as uow:
            statement = select(Course).options(selectinload(Course.translations)).where(Course.archived_at.is_(None))
            if specialist_id:
                statement = statement.where((Course.owner_user_id == specialist_id) | (Course.instructor_partner_id.in_(select(PartnerProfile.id).where(PartnerProfile.user_id == specialist_id))))
            courses = uow.session.scalars(statement.order_by(Course.position, Course.created_at)).all()
            return [{"id": str(course.id), "slug": course.slug, "title": _localized_title(course.translations, "fa") or course.slug} for course in courses]

    def admin_comments(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        course: str | None = None,
        status: str = "attention",
        date_from: date | None = None,
        date_to: date | None = None,
        specialist_id: UUID | None = None,
    ) -> dict:
        conditions = [CourseComment.parent_id.is_(None)]
        if specialist_id:
            conditions.append((Course.owner_user_id == specialist_id) | (Course.instructor_partner_id.in_(select(PartnerProfile.id).where(PartnerProfile.user_id == specialist_id))))
        if course:
            conditions.append(Course.slug == course)
        if status == "attention":
            conditions.append(CourseComment.status.in_(["pending", "needs_reply"]))
        elif status != "all":
            conditions.append(CourseComment.status == status)
        if date_from:
            conditions.append(CourseComment.created_at >= datetime.combine(date_from, time.min))
        if date_to:
            conditions.append(
                CourseComment.created_at < datetime.combine(date_to + timedelta(days=1), time.min)
            )
        with self.uow_factory() as uow:
            base = (
                select(CourseComment, User.display_name, Course, Lesson)
                .join(Course, Course.id == CourseComment.course_id)
                .join(User, User.id == CourseComment.user_id)
                .outerjoin(Lesson, Lesson.id == CourseComment.lesson_id)
                .options(selectinload(Course.translations), selectinload(Lesson.translations))
                .where(*conditions)
            )
            total = uow.session.scalar(
                select(func.count())
                .select_from(CourseComment)
                .join(Course, Course.id == CourseComment.course_id)
                .where(*conditions)
            ) or 0
            rows = uow.session.execute(
                base.order_by(CourseComment.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            ).all()
            return {
                "data": [
                    {
                        **_comment_payload(comment),
                        "author": display_name,
                        "course_slug": item_course.slug,
                        "course_title": _localized_title(item_course.translations, "fa"),
                        "lesson_title": (
                            _localized_title(lesson.translations, "fa") if lesson else None
                        ),
                    }
                    for comment, display_name, item_course, lesson in rows
                ],
                "meta": {"page": page, "page_size": page_size, "total": total},
            }

    def comment_summary(self, specialist_id: UUID | None = None) -> list[dict]:
        with self.uow_factory() as uow:
            rows = uow.session.execute(
                select(Course.slug, CourseComment.status, func.count())
                .join(CourseComment, CourseComment.course_id == Course.id)
                .where(CourseComment.parent_id.is_(None))
                .where((Course.owner_user_id == specialist_id) | (Course.instructor_partner_id.in_(select(PartnerProfile.id).where(PartnerProfile.user_id == specialist_id))) if specialist_id else True)
                .group_by(Course.slug, CourseComment.status)
            ).all()
            result: dict[str, dict] = {}
            for slug, status, count in rows:
                item = result.setdefault(slug, {"course_slug": slug, "new": 0, "needs_reply": 0})
                if status == "pending":
                    item["new"] = count
                elif status == "needs_reply":
                    item["needs_reply"] = count
            return list(result.values())

    def moderate(
        self, moderator_id: UUID, comment_id: UUID, decision: str, reason: str | None, specialist_id: UUID | None = None
    ) -> dict:
        if decision not in {"approved", "rejected", "hidden", "needs_reply"}:
            raise ValidationError("Unknown moderation decision.")
        with self.uow_factory() as uow:
            comment = uow.session.get(CourseComment, comment_id)
            if comment is None:
                raise NotFoundError("Comment does not exist.")
            self._assert_comment_scope(uow.session, comment, specialist_id)
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

    def reply_comment(self, moderator_id: UUID, comment_id: UUID, body: str, specialist_id: UUID | None = None) -> dict:
        normalized = " ".join(body.split())
        if not 2 <= len(normalized) <= 4000:
            raise ValidationError("Reply must be between 2 and 4000 characters.")
        with self.uow_factory() as uow:
            parent = uow.session.get(CourseComment, comment_id)
            if parent is None or parent.parent_id is not None:
                raise NotFoundError("Comment does not exist.")
            self._assert_comment_scope(uow.session, parent, specialist_id)
            reply = CourseComment(
                course_id=parent.course_id,
                lesson_id=parent.lesson_id,
                parent_id=parent.id,
                user_id=moderator_id,
                body=normalized,
                status="approved",
            )
            parent.status = "approved"
            uow.session.add(reply)
            uow.commit()
            return _comment_payload(reply)

    def delete_comment(self, comment_id: UUID, specialist_id: UUID | None = None) -> None:
        with self.uow_factory() as uow:
            comment = uow.session.get(CourseComment, comment_id)
            if comment is None:
                return
            self._assert_comment_scope(uow.session, comment, specialist_id)
            uow.session.execute(delete(CourseComment).where(CourseComment.parent_id == comment_id))
            uow.session.execute(
                delete(ModerationDecision).where(ModerationDecision.comment_id == comment_id)
            )
            uow.session.delete(comment)
            uow.commit()

    @staticmethod
    def _assert_comment_scope(session, comment: CourseComment, specialist_id: UUID | None) -> None:
        if specialist_id is None:
            return
        course = session.get(Course, comment.course_id)
        partner = session.get(PartnerProfile, course.instructor_partner_id) if course and course.instructor_partner_id else None
        if course is None or (course.owner_user_id != specialist_id and (partner is None or partner.user_id != specialist_id)):
            raise AuthorizationError("You can moderate only your own or taught courses.")


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
        "lesson_id": str(comment.lesson_id) if comment.lesson_id else None,
        "parent_id": str(comment.parent_id) if comment.parent_id else None,
        "created_at": comment.created_at.isoformat(),
    }


def _localized_title(translations: list, locale: str) -> str:  # type: ignore[type-arg]
    selected = next((item for item in translations if item.locale == locale), None)
    fallback = next((item for item in translations if item.locale == "en"), None)
    return (selected or fallback or translations[0]).title if translations else ""


def learning_service_from_container(container) -> LearningService:  # type: ignore[no-untyped-def]
    return LearningService(lambda: SqlAlchemyUnitOfWork(container.database.session_factory))
