from __future__ import annotations

import pytest

from app.domain.auth import normalize_email, normalize_phone


def test_identity_normalization() -> None:
    assert normalize_email("Member@Example.COM") == "member@example.com"
    assert normalize_phone("09121234567") == "+989121234567"


@pytest.mark.parametrize("value", ["not-an-email", "missing@", "@missing.test"])
def test_invalid_email_is_rejected(value: str) -> None:
    with pytest.raises(ValueError, match="invalid"):
        normalize_email(value)


@pytest.mark.parametrize("value", ["not-a-phone", "123", "+98999"])
def test_invalid_phone_is_rejected(value: str) -> None:
    with pytest.raises(ValueError, match="invalid"):
        normalize_phone(value)
