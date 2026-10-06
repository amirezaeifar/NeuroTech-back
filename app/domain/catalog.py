"""Framework-independent product, event, and YouTube rules."""

from __future__ import annotations

import re
from typing import Any

from app.domain.errors import ValidationError

SUPPORTED_LOCALES = {"en", "fa"}
SUPPORTED_CURRENCIES = {"IRR", "USD"}
SALE_MODES = {"direct", "inquiry"}
EVENT_KINDS = {"online", "onsite"}
EVENT_STATUSES = {"upcoming", "live", "completed", "cancelled"}
INQUIRY_STATUSES = {"pending", "answered", "closed", "rejected"}
SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
YOUTUBE_PLAYLIST_PATTERN = re.compile(r"^[A-Za-z0-9_-]{10,100}$")


def validate_slug(value: str) -> str:
    normalized = value.strip().lower()
    if not SLUG_PATTERN.fullmatch(normalized):
        raise ValidationError("Slug must contain lowercase letters, numbers and hyphens.")
    return normalized


def validate_translations(items: list[dict[str, Any]]) -> None:
    locales = {item["locale"] for item in items}
    if locales != SUPPORTED_LOCALES or len(items) != 2:
        raise ValidationError("Persian and English translations are required.")


def validate_prices(sale_mode: str, prices: list[dict[str, Any]]) -> None:
    if sale_mode not in SALE_MODES:
        raise ValidationError("Sale mode must be direct or inquiry.")
    currencies = {item["currency"] for item in prices}
    if len(currencies) != len(prices) or not currencies.issubset(SUPPORTED_CURRENCIES):
        raise ValidationError("Prices must use unique IRR/USD currencies.")
    if any(item["amount_minor"] < 0 for item in prices):
        raise ValidationError("Product price cannot be negative.")
    if sale_mode == "direct" and not prices:
        raise ValidationError("Direct-sale products require at least one price.")
    if sale_mode == "inquiry" and prices:
        raise ValidationError("Inquiry-only products cannot have checkout prices.")


def validate_youtube_playlist_id(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    normalized = value.strip()
    if not YOUTUBE_PLAYLIST_PATTERN.fullmatch(normalized):
        raise ValidationError("YouTube playlist id is invalid.")
    return normalized
