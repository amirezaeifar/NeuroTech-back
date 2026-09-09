from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.domain.academy import (
    validate_positions,
    validate_publishable,
    validate_source,
    validate_translated_titles,
)
from app.domain.errors import ValidationError


def _translated(locale: str) -> SimpleNamespace:
    return SimpleNamespace(locale=locale, title=f"Title {locale}")


def _publishable_course() -> SimpleNamespace:
    lesson = SimpleNamespace(translations=[_translated("en"), _translated("fa")])
    section = SimpleNamespace(translations=[_translated("en"), _translated("fa")], lessons=[lesson])
    return SimpleNamespace(
        tier="premium",
        translations=[_translated("en"), _translated("fa")],
        prices=[SimpleNamespace(currency="IRR"), SimpleNamespace(currency="USD")],
        sections=[section],
        outcomes=[_translated("en"), _translated("fa")],
    )


def test_publishable_course_rule_accepts_complete_bilingual_content() -> None:
    validate_publishable(_publishable_course())


def test_domain_catalogue_rules_reject_invalid_values() -> None:
    with pytest.raises(ValidationError, match="positions"):
        validate_positions([{"position": 1}, {"position": 1}], "lesson")
    with pytest.raises(ValidationError, match="Persian and English"):
        validate_translated_titles([{"locale": "en", "title": "Only English"}], "lesson")
    with pytest.raises(ValidationError, match="exactly one"):
        validate_source({"storage_path": None, "external_url": None}, "resource")

    course = _publishable_course()
    course.prices = [SimpleNamespace(currency="USD")]
    with pytest.raises(ValidationError, match="IRR and USD"):
        validate_publishable(course)
