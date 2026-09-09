"""Idempotent development seed data."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select

from app.core.academy_models import (
    Course,
    CourseMedia,
    CourseResource,
    CourseSection,
    LearningOutcome,
    Lesson,
    LessonTranslation,
    SectionTranslation,
)
from app.services.academy import academy_service_from_container

COURSES = [
    {
        "slug": "clinical-neurology",
        "tier": "free",
        "field": "clinicalNeurology",
        "level": "intermediate",
        "translations": [
            {
                "locale": "en",
                "title": "Introduction to Clinical Neurology",
                "description": (
                    "Clinical reasoning from examination and localisation to common "
                    "neurological disorders."
                ),
                "instructor_name": "Dr. N. Farahani",
                "duration_label": "16 lessons · 9h 00m",
            },
            {
                "locale": "fa",
                "title": "درآمدی بر نورولوژی بالینی",
                "description": (
                    "استدلال بالینی از معاینه و لوکالیزاسیون تا اختلالات شایع نورولوژیک."
                ),
                "instructor_name": "دکتر ن. فراهانی",
                "duration_label": "۱۶ درس · ۹ ساعت",
            },
        ],
        "prices": [],
    },
    {
        "slug": "neuroscience",
        "tier": "free",
        "field": "neuroscience",
        "level": "beginner",
        "translations": [
            {
                "locale": "en",
                "title": "Foundations of Neuroscience",
                "description": (
                    "From neurons and synapses to neuroplasticity, networks and cognition."
                ),
                "instructor_name": "Dr. S. Moradi",
                "duration_label": "14 lessons · 7h 30m",
            },
            {
                "locale": "fa",
                "title": "مبانی علوم اعصاب",
                "description": (
                    "از نورون و سیناپس تا نوروپلاستیسیته، شبکه‌های عصبی و سامانه‌های شناختی."
                ),
                "instructor_name": "دکتر س. مرادی",
                "duration_label": "۱۴ درس · ۷ ساعت و ۳۰ دقیقه",
            },
        ],
        "prices": [],
    },
    {
        "slug": "neuroimaging",
        "tier": "premium",
        "field": "neuroimaging",
        "level": "intermediate",
        "translations": [
            {
                "locale": "en",
                "title": "Neuroimaging: MRI & CT Interpretation",
                "description": "A systematic approach to CT, MRI, diffusion and vascular imaging.",
                "instructor_name": "Dr. A. Karimi",
                "duration_label": "14 lessons · 8h 00m",
            },
            {
                "locale": "fa",
                "title": "تصویربرداری عصبی: تفسیر MRI و CT",
                "description": "رویکردی نظام‌مند به CT، MRI، دیفیوژن و تصویربرداری عروقی.",
                "instructor_name": "دکتر ا. کریمی",
                "duration_label": "۱۴ درس · ۸ ساعت",
            },
        ],
        "prices": [
            {"currency": "IRR", "amount_minor": 149_000_000},
            {"currency": "USD", "amount_minor": 14_900},
        ],
    },
    {
        "slug": "brain-anatomy",
        "tier": "free",
        "field": "brainAnatomy",
        "level": "beginner",
        "translations": [
            {
                "locale": "en",
                "title": "Brain Anatomy & Functional Pathways",
                "description": "Regional neuroanatomy and the major functional pathways.",
                "instructor_name": "Dr. R. Tabrizi",
                "duration_label": "18 lessons · 9h 30m",
            },
            {
                "locale": "fa",
                "title": "آناتومی مغز و مسیرهای عملکردی",
                "description": "نوروآناتومی ناحیه‌ای و مسیرهای اصلی عملکردی مغز.",
                "instructor_name": "دکتر ر. تبریزی",
                "duration_label": "۱۸ درس · ۹ ساعت و ۳۰ دقیقه",
            },
        ],
        "prices": [],
    },
    {
        "slug": "neurocritical-care",
        "tier": "premium",
        "field": "neurocriticalCare",
        "level": "advanced",
        "translations": [
            {
                "locale": "en",
                "title": "Neurocritical Care & Stroke Management",
                "description": (
                    "Neuromonitoring, intracranial pressure, stroke and brain injury "
                    "in the neuro-ICU."
                ),
                "instructor_name": "Dr. L. Hashemi",
                "duration_label": "12 lessons · 6h 30m",
            },
            {
                "locale": "fa",
                "title": "مراقبت‌های ویژه عصبی و مدیریت سکته",
                "description": "نورومانیتورینگ، فشار درون‌جمجمه‌ای، سکته و آسیب مغزی در ICU عصبی.",
                "instructor_name": "دکتر ل. هاشمی",
                "duration_label": "۱۲ درس · ۶ ساعت و ۳۰ دقیقه",
            },
        ],
        "prices": [
            {"currency": "IRR", "amount_minor": 179_000_000},
            {"currency": "USD", "amount_minor": 17_900},
        ],
    },
    {
        "slug": "neurosurgery",
        "tier": "premium",
        "field": "neurosurgery",
        "level": "advanced",
        "translations": [
            {
                "locale": "en",
                "title": "Neurosurgery Fundamentals",
                "description": (
                    "Surgical anatomy, cranial approaches, navigation and core "
                    "neurosurgical practice."
                ),
                "instructor_name": "Dr. M. Saadat",
                "duration_label": "16 lessons · 9h 00m",
            },
            {
                "locale": "fa",
                "title": "مبانی جراحی مغز و اعصاب",
                "description": "آناتومی جراحی، رویکردهای کرانیال، ناوبری و اصول جراحی مغز و اعصاب.",
                "instructor_name": "دکتر م. سعادت",
                "duration_label": "۱۶ درس · ۹ ساعت",
            },
        ],
        "prices": [
            {"currency": "IRR", "amount_minor": 199_000_000},
            {"currency": "USD", "amount_minor": 19_900},
        ],
    },
]


def seed_academy(container) -> int:  # type: ignore[no-untyped-def]
    service = academy_service_from_container(container)
    created = 0
    for item in COURSES:
        with container.database.session() as session:
            exists = session.scalar(select(Course.id).where(Course.slug == item["slug"]))
        if not exists:
            service.create_course(item)
            created += 1
        with container.database.session() as session:
            stored = session.scalar(select(Course).where(Course.slug == item["slug"]))
            changed = False
            if stored is not None and not stored.sections:
                section = CourseSection(
                    course_id=stored.id,
                    position=1,
                    translations=[
                        SectionTranslation(locale="en", title="Course Foundations"),
                        SectionTranslation(locale="fa", title="مبانی دوره"),
                    ],
                )
                section.lessons.extend(
                    [
                        Lesson(
                            position=1,
                            duration_seconds=1200,
                            video_provider="youtube",
                            video_reference="M7lc1UVf-VE",
                            free_preview=True,
                            translations=[
                                LessonTranslation(locale="en", title="Orientation"),
                                LessonTranslation(locale="fa", title="آشنایی با دوره"),
                            ],
                        ),
                        Lesson(
                            position=2,
                            duration_seconds=1800,
                            video_provider="youtube",
                            video_reference="aqz-KE-bpKQ",
                            free_preview=False,
                            translations=[
                                LessonTranslation(locale="en", title="Core Concepts"),
                                LessonTranslation(locale="fa", title="مفاهیم اصلی"),
                            ],
                        ),
                    ]
                )
                stored.sections.append(section)
                changed = True
            if stored is not None and not stored.outcomes:
                stored.outcomes.extend(
                    [
                        LearningOutcome(
                            locale="en", position=1, text="Apply the course concepts in practice."
                        ),
                        LearningOutcome(
                            locale="fa", position=1, text="مفاهیم دوره را در عمل به کار ببرید."
                        ),
                    ]
                )
                changed = True
            if stored is not None and not stored.media:
                stored.media.append(
                    CourseMedia(
                        kind="cover",
                        position=1,
                        storage_path=f"academy/{stored.slug}/cover.webp",
                    )
                )
                changed = True
            if stored is not None and not stored.resources:
                stored.resources.append(
                    CourseResource(
                        name="Course handout",
                        kind="pdf",
                        storage_path=f"academy/{stored.slug}/handout.pdf",
                    )
                )
                changed = True
            if changed:
                session.commit()
        with container.database.session() as session:
            stored = session.scalar(select(Course).where(Course.slug == item["slug"]))
            should_publish = stored is not None and stored.published_at is None
            stored_id = stored.id if stored else None
        if should_publish and stored_id:
            service.publish(UUID(str(stored_id)))
    return created
