from __future__ import annotations

from uuid import UUID

import pytest
from sqlalchemy import select

from app.core.academy_models import Course
from app.core.auth_models import User
from app.domain.errors import ConflictError, ValidationError
from app.services.academy import academy_service_from_container
from app.services.learning import learning_service_from_container
from app.services.seed import seed_academy


def _course(slug: str, *, tier: str = "free", bilingual: bool = True) -> dict:
    translations = [
        {
            "locale": "en",
            "title": slug.title(),
            "description": "Course description",
            "instructor_name": "Teacher",
            "duration_label": "1 lesson",
        }
    ]
    if bilingual:
        translations.append(
            {
                "locale": "fa",
                "title": "عنوان دوره",
                "description": "توضیحات دوره",
                "instructor_name": "مدرس",
                "duration_label": "۱ درس",
            }
        )
    return {
        "slug": slug,
        "tier": tier,
        "field": "clinical",
        "level": "beginner",
        "translations": translations,
        "prices": [],
    }


def _content(*, outcomes: bool = True) -> dict:
    return {
        "sections": [
            {
                "position": 1,
                "translations": [
                    {"locale": "en", "title": "Section"},
                    {"locale": "fa", "title": "بخش"},
                ],
                "lessons": [
                    {
                        "position": 1,
                        "duration_seconds": 60,
                        "video_provider": "youtube",
                        "video_reference": "video",
                        "free_preview": False,
                        "translations": [
                            {"locale": "en", "title": "Lesson"},
                            {"locale": "fa", "title": "درس"},
                        ],
                    }
                ],
            }
        ],
        "outcomes": (
            [
                {"locale": "en", "position": 1, "text": "Outcome"},
                {"locale": "fa", "position": 1, "text": "خروجی"},
            ]
            if outcomes
            else []
        ),
        "resources": [],
        "media": [],
    }


def test_catalogue_filters_updates_and_publish_guards(app) -> None:  # type: ignore[no-untyped-def]
    service = academy_service_from_container(app.extensions["container"])
    course_id = UUID(service.create_course(_course("draft-course"))["id"])
    assert service.get_course("draft-course", "invalid") is None
    assert (
        service.get_course("draft-course", "fa", include_unpublished=True)["title"] == "عنوان دوره"
    )
    updated = service.update_course(
        course_id,
        {
            "tier": "premium",
            "field": "imaging",
            "level": "advanced",
            "translations": _course("ignored")["translations"],
            "prices": [
                {"currency": "IRR", "amount_minor": 1000},
                {"currency": "USD", "amount_minor": 100},
            ],
        },
    )
    assert updated["tier"] == "premium"
    with pytest.raises(ValidationError, match="sections"):
        service.publish(course_id)
    service.replace_content(course_id, _content(outcomes=False))
    with pytest.raises(ValidationError, match="outcomes"):
        service.publish(course_id)
    service.replace_content(course_id, _content())
    service.publish(course_id)
    with pytest.raises(ValidationError, match="IRR and USD"):
        service.update_course(course_id, {"prices": [{"currency": "USD", "amount_minor": 100}]})
    assert (
        service.list_courses(locale="fa", page=1, page_size=5, tier="premium", field="imaging")[1]
        == 1
    )
    with pytest.raises(ConflictError, match="Unpublish"):
        service.replace_content(course_id, _content())


def test_catalogue_value_and_content_validation_branches(app) -> None:  # type: ignore[no-untyped-def]
    service = academy_service_from_container(app.extensions["container"])
    with pytest.raises(ValidationError, match="tier"):
        service.update_course(UUID(int=0), {"tier": "enterprise"})
    duplicate_translations = _course("duplicate-locales")
    duplicate_translations["translations"][1]["locale"] = "en"
    with pytest.raises(ValidationError, match="translations"):
        service.create_course(duplicate_translations)

    invalid_prices = _course("duplicate-prices")
    invalid_prices["prices"] = [
        {"currency": "USD", "amount_minor": 1},
        {"currency": "USD", "amount_minor": 2},
    ]
    with pytest.raises(ValidationError, match="prices"):
        service.create_course(invalid_prices)
    negative_price = _course("negative-price")
    negative_price["prices"] = [{"currency": "USD", "amount_minor": -1}]
    with pytest.raises(ValidationError, match="negative"):
        service.create_course(negative_price)

    premium_id = UUID(service.create_course(_course("premium-empty", tier="premium"))["id"])
    with pytest.raises(ValidationError, match="prices"):
        service.publish(premium_id)
    draft_id = UUID(service.create_course(_course("content-validation"))["id"])
    bad = _content()
    bad["sections"].append({**bad["sections"][0]})
    with pytest.raises(ValidationError, match="positions"):
        service.replace_content(draft_id, bad)
    bad = _content()
    bad["sections"][0]["lessons"][0]["video_provider"] = "internal"
    with pytest.raises(ValidationError, match="YouTube"):
        service.replace_content(draft_id, bad)
    bad = _content()
    bad["resources"] = [
        {"name": "Broken", "kind": "pdf", "storage_path": None, "external_url": None}
    ]
    with pytest.raises(ValidationError, match="exactly one"):
        service.replace_content(draft_id, bad)
    bad = _content()
    bad["media"] = [
        {
            "kind": "cover",
            "position": 1,
            "locale": None,
            "mime_type": None,
            "storage_path": "cover.webp",
            "external_url": "https://example.com/cover.webp",
        }
    ]
    with pytest.raises(ValidationError, match="exactly one"):
        service.replace_content(draft_id, bad)


def test_enrolled_course_content_is_immutable(app) -> None:  # type: ignore[no-untyped-def]
    container = app.extensions["container"]
    seed_academy(container)
    with container.database.session() as session:
        user = User(display_name="Learner", role="user", status="active")
        session.add(user)
        session.commit()
        user_id = user.id
        course = session.scalar(select(Course).where(Course.slug == "clinical-neurology"))
        assert course is not None
        course_id = course.id
    learning_service_from_container(container).enroll_free(user_id, "clinical-neurology")
    service = academy_service_from_container(container)
    service.unpublish(course_id)
    with pytest.raises(ConflictError, match="enrollment"):
        service.replace_content(course_id, _content())
