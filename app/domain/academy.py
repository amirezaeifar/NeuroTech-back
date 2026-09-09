"""Pure Academy catalogue rules, independent from storage and HTTP."""

from __future__ import annotations

import re
from typing import Any

from app.domain.errors import ValidationError

SUPPORTED_LOCALES = {"en", "fa"}
SUPPORTED_CURRENCIES = {"IRR", "USD"}
TIERS = {"free", "premium"}
SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def validate_positions(items: list[dict], kind: str, *, per_locale: bool = False) -> None:
    keys = [
        (item.get("locale"), item["position"]) if per_locale else item["position"] for item in items
    ]
    if len(keys) != len(set(keys)) or any(item["position"] < 1 for item in items):
        raise ValidationError(f"{kind.title()} positions must be positive and unique.")


def validate_translated_titles(translations: list[dict], kind: str) -> None:
    locales = {item["locale"] for item in translations}
    if locales != SUPPORTED_LOCALES or len(translations) != 2:
        raise ValidationError(f"{kind.title()} requires Persian and English titles.")


def validate_source(item: dict, kind: str) -> None:
    if bool(item.get("storage_path")) == bool(item.get("external_url")):
        raise ValidationError(f"A {kind} requires exactly one storage_path or external_url.")


def validate_publishable(course: Any) -> None:
    locales = {translation.locale for translation in course.translations}
    if locales != SUPPORTED_LOCALES:
        raise ValidationError("Persian and English translations are required.")
    currencies = {price.currency for price in course.prices}
    if course.tier == "premium" and currencies != SUPPORTED_CURRENCIES:
        raise ValidationError("Premium courses require independent IRR and USD prices.")
    if not course.sections or any(not section.lessons for section in course.sections):
        raise ValidationError("A publishable course requires sections and lessons.")
    for section in course.sections:
        validate_translated_titles(
            [{"locale": item.locale, "title": item.title} for item in section.translations],
            "section",
        )
        for lesson in section.lessons:
            validate_translated_titles(
                [{"locale": item.locale, "title": item.title} for item in lesson.translations],
                "lesson",
            )
    if {item.locale for item in course.outcomes} != SUPPORTED_LOCALES:
        raise ValidationError("Persian and English learning outcomes are required.")
