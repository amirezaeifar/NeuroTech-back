"""Authentication value objects and framework-independent rules."""

from __future__ import annotations

from enum import StrEnum

import phonenumbers
from email_validator import EmailNotValidError, validate_email


class Role(StrEnum):
    USER = "user"
    SPECIALIST = "specialist"
    CONTENT_MANAGER = "content_manager"
    ADMIN = "admin"
    SUPER_ADMIN = "super_admin"


class UserStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    SUSPENDED = "suspended"


def normalize_email(value: str) -> str:
    try:
        result = validate_email(value, check_deliverability=False)
    except EmailNotValidError as error:
        raise ValueError("Email address is invalid.") from error
    return result.normalized.lower()


def normalize_phone(value: str, default_region: str = "IR") -> str:
    try:
        parsed = phonenumbers.parse(value, default_region)
    except phonenumbers.NumberParseException as error:
        raise ValueError("Phone number is invalid.") from error
    if not phonenumbers.is_valid_number(parsed):
        raise ValueError("Phone number is invalid.")
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
