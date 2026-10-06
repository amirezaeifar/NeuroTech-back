"""Academy catalogue use cases."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.orm import selectinload

from app.core.academy_models import (
    Course,
    CourseMedia,
    CoursePrice,
    CourseResource,
    CourseSection,
    CourseTranslation,
    LearningOutcome,
    Lesson,
    LessonTranslation,
    SectionTranslation,
)
from app.core.content_models import PartnerProfile
from app.core.learning_models import CourseComment, Enrollment
from app.core.unit_of_work import SqlAlchemyUnitOfWork
from app.domain.academy import (
    SLUG_PATTERN,
    SUPPORTED_CURRENCIES,
    SUPPORTED_LOCALES,
    TIERS,
)
from app.domain.academy import (
    validate_positions as _validate_positions,
)
from app.domain.academy import (
    validate_publishable as _validate_publishable,
)
from app.domain.academy import (
    validate_source as _validate_source,
)
from app.domain.academy import (
    validate_translated_titles as _validate_translated_titles,
)
from app.domain.catalog import validate_youtube_playlist_id
from app.domain.errors import ConflictError, ValidationError


class AcademyService:
    def __init__(self, uow_factory) -> None:  # type: ignore[no-untyped-def]
        self.uow_factory = uow_factory

    def list_courses(
        self,
        *,
        locale: str,
        page: int,
        page_size: int,
        tier: str | None = None,
        field: str | None = None,
    ) -> tuple[list[dict], int]:
        locale = _locale(locale)
        with self.uow_factory() as uow:
            conditions = [Course.published_at.is_not(None), Course.archived_at.is_(None)]
            if tier:
                if tier not in TIERS:
                    raise ValidationError("Unknown course tier.")
                conditions.append(Course.tier == tier)
            if field:
                conditions.append(Course.field == field)
            total = (
                uow.session.scalar(select(func.count()).select_from(Course).where(*conditions)) or 0
            )
            courses = list(
                uow.session.scalars(
                    select(Course)
                    .options(
                        selectinload(Course.translations),
                        selectinload(Course.prices),
                        selectinload(Course.media),
                        selectinload(Course.sections).selectinload(CourseSection.lessons),
                        selectinload(Course.instructor_partner),
                    )
                    .where(*conditions)
                    .order_by(Course.position, Course.created_at, Course.id)
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                ).unique()
            )
            return [_course_summary(course, locale) for course in courses], total

    def list_admin_courses(self, owner_user_id: UUID | None = None) -> list[dict]:
        with self.uow_factory() as uow:
            conditions = [Course.archived_at.is_(None)]
            if owner_user_id is not None:
                conditions.append(Course.owner_user_id == owner_user_id)
            courses = list(
                uow.session.scalars(
                    select(Course)
                    .options(
                        selectinload(Course.translations),
                        selectinload(Course.prices),
                        selectinload(Course.outcomes),
                        selectinload(Course.media),
                        selectinload(Course.resources),
                        selectinload(Course.instructor_partner),
                        selectinload(Course.sections).selectinload(CourseSection.translations),
                        selectinload(Course.sections)
                        .selectinload(CourseSection.lessons)
                        .selectinload(Lesson.translations),
                    )
                    .where(*conditions)
                    .order_by(Course.position, Course.created_at, Course.id)
                ).unique()
            )
            return [_course_admin_payload(course) for course in courses]

    def get_course(
        self, slug: str, locale: str, *, include_unpublished: bool = False
    ) -> dict | None:
        locale = _locale(locale)
        with self.uow_factory() as uow:
            query = (
                select(Course)
                .options(
                    selectinload(Course.translations),
                    selectinload(Course.prices),
                    selectinload(Course.outcomes),
                    selectinload(Course.resources),
                    selectinload(Course.instructor_partner),
                    selectinload(Course.sections).selectinload(CourseSection.translations),
                    selectinload(Course.sections)
                    .selectinload(CourseSection.lessons)
                    .selectinload(Lesson.translations),
                )
                .where(Course.slug == slug, Course.archived_at.is_(None))
            )
            if not include_unpublished:
                query = query.where(Course.published_at.is_not(None))
            course = uow.session.scalar(query)
            return (
                _course_detail(course, locale, expose_resources=course.tier != "premium")
                if course
                else None
            )

    def create_course(self, data: dict, owner_user_id: UUID | None = None) -> dict:
        slug = data["slug"].strip().lower()
        if not SLUG_PATTERN.fullmatch(slug):
            raise ValidationError("Slug must contain lowercase letters, numbers and hyphens.")
        tier = data["tier"]
        if tier not in TIERS:
            raise ValidationError("Unknown course tier.")
        with self.uow_factory() as uow:
            if uow.session.scalar(select(Course.id).where(Course.slug == slug)):
                raise ConflictError("A course with this slug already exists.")
            _validate_instructor_partner(uow.session, data.get("instructor_partner_id"))
            course = Course(
                slug=slug,
                tier=tier,
                field=data["field"],
                level=data["level"],
                owner_user_id=owner_user_id,
                instructor_partner_id=data.get("instructor_partner_id"),
                youtube_playlist_id=validate_youtube_playlist_id(data.get("youtube_playlist_id")),
            )
            _replace_translations(course, data["translations"])
            _replace_prices(course, data.get("prices", []))
            uow.session.add(course)
            uow.commit()
            return _course_detail(course, "en")

    def assert_owned_by(self, course_id: UUID, owner_user_id: UUID) -> None:
        with self.uow_factory() as uow:
            exists = uow.session.scalar(
                select(Course.id).where(
                    Course.id == course_id,
                    Course.owner_user_id == owner_user_id,
                    Course.archived_at.is_(None),
                )
            )
            if exists is None:
                raise ValidationError("You can only manage courses that you created.")

    def update_course(self, course_id: UUID, data: dict) -> dict:
        if "tier" in data and data["tier"] not in TIERS:
            raise ValidationError("Unknown course tier.")
        with self.uow_factory() as uow:
            course = uow.session.get(Course, course_id)
            if course is None or course.archived_at is not None:
                raise ValidationError("Course does not exist.")
            for key in ("tier", "field", "level"):
                if key in data:
                    setattr(course, key, data[key])
            if "youtube_playlist_id" in data:
                course.youtube_playlist_id = validate_youtube_playlist_id(
                    data["youtube_playlist_id"]
                )
            if "instructor_partner_id" in data:
                _validate_instructor_partner(uow.session, data.get("instructor_partner_id"))
                course.instructor_partner_id = data.get("instructor_partner_id")
            if "translations" in data:
                _replace_translations(course, data["translations"], uow.session)
            if "prices" in data:
                _replace_prices(course, data["prices"], uow.session)
            if course.published_at is not None:
                _validate_publishable(course)
            uow.commit()
            return _course_detail(course, "en")

    def publish(self, course_id: UUID) -> dict:
        with self.uow_factory() as uow:
            course = uow.session.get(Course, course_id)
            if course is None or course.archived_at is not None:
                raise ValidationError("Course does not exist.")
            _validate_publishable(course)
            course.published_at = course.published_at or datetime.now(UTC)
            uow.commit()
            return _course_detail(course, "en")

    def archive(self, course_id: UUID) -> None:
        with self.uow_factory() as uow:
            course = uow.session.get(Course, course_id)
            if course is None:
                return
            course.archived_at = course.archived_at or datetime.now(UTC)
            course.published_at = None
            uow.commit()

    def unpublish(self, course_id: UUID) -> dict:
        with self.uow_factory() as uow:
            course = uow.session.get(Course, course_id)
            if course is None or course.archived_at is not None:
                raise ValidationError("Course does not exist.")
            course.published_at = None
            uow.commit()
            return _course_admin_payload(course)

    def reorder(self, course_ids: list[UUID]) -> None:
        if len(course_ids) != len(set(course_ids)):
            raise ValidationError("Course ordering cannot contain duplicate ids.")
        with self.uow_factory() as uow:
            courses = list(
                uow.session.scalars(
                    select(Course).where(Course.id.in_(course_ids), Course.archived_at.is_(None))
                )
            )
            if len(courses) != len(course_ids):
                raise ValidationError("Course ordering contains an unknown course.")
            by_id = {course.id: course for course in courses}
            for position, course_id in enumerate(course_ids):
                by_id[course_id].position = position
            uow.commit()

    def replace_content(self, course_id: UUID, data: dict) -> dict:
        with self.uow_factory() as uow:
            course = uow.session.scalar(
                select(Course)
                .options(
                    selectinload(Course.outcomes),
                    selectinload(Course.media),
                    selectinload(Course.resources),
                    selectinload(Course.sections).selectinload(CourseSection.translations),
                    selectinload(Course.sections)
                    .selectinload(CourseSection.lessons)
                    .selectinload(Lesson.translations),
                    selectinload(Course.translations),
                    selectinload(Course.prices),
                )
                .where(Course.id == course_id, Course.archived_at.is_(None))
            )
            if course is None:
                raise ValidationError("Course does not exist.")
            if course.published_at is not None:
                raise ConflictError("Unpublish the course before replacing its content.")
            if uow.session.scalar(
                select(Enrollment.id).where(Enrollment.course_id == course_id).limit(1)
            ):
                raise ConflictError(
                    "Content cannot be replaced after enrollment; create a new course version."
                )
            _validate_positions(data.get("sections", []), "section")
            _validate_positions(data.get("outcomes", []), "outcome", per_locale=True)
            _validate_positions(data.get("media", []), "media")

            lesson_ids = [lesson.id for section in course.sections for lesson in section.lessons]
            if lesson_ids:
                uow.session.execute(
                    update(CourseComment)
                    .where(CourseComment.lesson_id.in_(lesson_ids))
                    .values(lesson_id=None)
                )
            course.sections.clear()
            course.outcomes.clear()
            course.resources.clear()
            course.media.clear()
            uow.session.flush()
            for section_data in data.get("sections", []):
                _validate_translated_titles(section_data["translations"], "section")
                section = CourseSection(position=section_data["position"])
                section.translations.extend(
                    SectionTranslation(**item) for item in section_data["translations"]
                )
                _validate_positions(section_data.get("lessons", []), "lesson")
                for lesson_data in section_data.get("lessons", []):
                    _validate_translated_titles(lesson_data["translations"], "lesson")
                    if lesson_data["video_provider"] != "youtube":
                        raise ValidationError("Only YouTube lesson videos are supported.")
                    values = {
                        key: value for key, value in lesson_data.items() if key != "translations"
                    }
                    lesson = Lesson(**values)
                    lesson.translations.extend(
                        LessonTranslation(**item) for item in lesson_data["translations"]
                    )
                    section.lessons.append(lesson)
                course.sections.append(section)

            course.outcomes.extend(LearningOutcome(**item) for item in data.get("outcomes", []))
            for item in data.get("resources", []):
                _validate_source(item, "resource")
                course.resources.append(CourseResource(**item))
            for item in data.get("media", []):
                _validate_source(item, "media")
                course.media.append(CourseMedia(**item))
            uow.commit()
            return _course_admin_payload(course)


def _locale(locale: str) -> str:
    return locale if locale in SUPPORTED_LOCALES else "en"


def _translation(course: Course, locale: str) -> CourseTranslation:
    translation = next((item for item in course.translations if item.locale == locale), None)
    fallback = next((item for item in course.translations if item.locale == "en"), None)
    return translation or fallback or course.translations[0]


def _course_summary(course: Course, locale: str) -> dict:
    translation = _translation(course, locale)
    return {
        "id": str(course.id),
        "slug": course.slug,
        "tier": course.tier,
        "field": course.field,
        "level": course.level,
        "position": course.position,
        "youtube_playlist_id": course.youtube_playlist_id,
        "title": translation.title,
        "description": translation.description,
        "summary": translation.summary,
        "images": [
            {"kind": m.kind, "url": m.external_url or m.storage_path}
            for m in course.media
            if m.kind.startswith(("cover", "header"))
        ],
        "instructor_name": translation.instructor_name,
        "duration_label": translation.duration_label,
        "instructor_partner_id": (
            str(course.instructor_partner_id) if course.instructor_partner_id else None
        ),
        "instructor_partner_slug": (
            course.instructor_partner.slug if course.instructor_partner else None
        ),
        "lesson_count": sum(len(section.lessons) for section in course.sections),
        "prices": [
            {"currency": price.currency, "amount_minor": price.amount_minor}
            for price in sorted(course.prices, key=lambda item: item.currency)
        ],
    }


def _course_detail(course: Course, locale: str, *, expose_resources: bool = True) -> dict:
    data = _course_summary(course, locale)
    data.update(
        {
            "published": course.published_at is not None,
            "outcomes": [
                item.text
                for item in sorted(course.outcomes, key=lambda value: value.position)
                if item.locale == locale
            ],
            "sections": [
                {
                    "id": str(section.id),
                    "position": section.position,
                    "title": _localized_title(section.translations, locale),
                    "lessons": [
                        {
                            "id": str(lesson.id),
                            "position": lesson.position,
                            "title": _localized_title(lesson.translations, locale),
                            "duration_seconds": lesson.duration_seconds,
                            "free_preview": lesson.free_preview,
                        }
                        for lesson in sorted(section.lessons, key=lambda item: item.position)
                    ],
                }
                for section in sorted(course.sections, key=lambda item: item.position)
            ],
            "resources": [
                {
                    "name": item.name,
                    "kind": item.kind,
                    "url": (item.external_url or item.storage_path) if expose_resources else None,
                    "locked": not expose_resources,
                }
                for item in course.resources
            ],
            "version": course.version,
        }
    )
    return data


def _course_admin_payload(course: Course) -> dict:
    data = _course_summary(course, "en")
    data["published"] = course.published_at is not None
    data["owner_user_id"] = str(course.owner_user_id) if course.owner_user_id else None
    data["translations"] = [
        {
            "locale": item.locale,
            "title": item.title,
            "description": item.description,
            "summary": item.summary,
            "instructor_name": item.instructor_name,
            "duration_label": item.duration_label,
        }
        for item in course.translations
    ]
    data["version"] = course.version
    data["content"] = {
        "sections": [
            {
                "id": str(section.id),
                "position": section.position,
                "translations": [
                    {"locale": item.locale, "title": item.title} for item in section.translations
                ],
                "lessons": [
                    {
                        "id": str(lesson.id),
                        "position": lesson.position,
                        "duration_seconds": lesson.duration_seconds,
                        "video_provider": lesson.video_provider,
                        "video_reference": lesson.video_reference,
                        "free_preview": lesson.free_preview,
                        "translations": [
                            {"locale": item.locale, "title": item.title}
                            for item in lesson.translations
                        ],
                    }
                    for lesson in section.lessons
                ],
            }
            for section in course.sections
        ],
        "outcomes": [
            {"locale": item.locale, "position": item.position, "text": item.text}
            for item in course.outcomes
        ],
        "media": [
            {
                "kind": item.kind,
                "position": item.position,
                "locale": item.locale,
                "mime_type": item.mime_type,
                "storage_path": item.storage_path,
                "external_url": item.external_url,
            }
            for item in course.media
        ],
        "resources": [
            {
                "name": item.name,
                "kind": item.kind,
                "storage_path": item.storage_path,
                "external_url": item.external_url,
            }
            for item in course.resources
        ],
    }
    return data


def _replace_translations(course: Course, translations: list[dict], session=None) -> None:  # type: ignore[no-untyped-def]
    locales = {item["locale"] for item in translations}
    if not locales.issubset(SUPPORTED_LOCALES) or len(locales) != len(translations):
        raise ValidationError("Course translations must use unique en/fa locales.")
    course.translations.clear()
    if session is not None:
        session.flush()
    course.translations.extend(CourseTranslation(**item) for item in translations)


def _replace_prices(course: Course, prices: list[dict], session=None) -> None:  # type: ignore[no-untyped-def]
    currencies = {item["currency"] for item in prices}
    if not currencies.issubset(SUPPORTED_CURRENCIES) or len(currencies) != len(prices):
        raise ValidationError("Course prices must use unique IRR/USD currencies.")
    if any(item["amount_minor"] < 0 for item in prices):
        raise ValidationError("Course price cannot be negative.")
    course.prices.clear()
    if session is not None:
        session.flush()
    course.prices.extend(CoursePrice(**item) for item in prices)


def _localized_title(translations: list, locale: str) -> str:  # type: ignore[type-arg]
    selected = next((item for item in translations if item.locale == locale), None)
    fallback = next((item for item in translations if item.locale == "en"), None)
    return (selected or fallback or translations[0]).title if translations else ""


def _validate_instructor_partner(session, partner_id: UUID | None) -> None:  # type: ignore[no-untyped-def]
    if partner_id is None:
        return
    partner = session.get(PartnerProfile, partner_id)
    if partner is None or partner.archived_at is not None:
        raise ValidationError("Selected instructor does not exist.")


def academy_service_from_container(container) -> AcademyService:  # type: ignore[no-untyped-def]
    return AcademyService(lambda: SqlAlchemyUnitOfWork(container.database.session_factory))
