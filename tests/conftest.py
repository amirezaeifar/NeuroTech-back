from __future__ import annotations

import pytest

from app import create_app


@pytest.fixture
def app(monkeypatch: pytest.MonkeyPatch, tmp_path):  # type: ignore[no-untyped-def]
    monkeypatch.setenv("SECRET_KEY", "test-secret-key")
    monkeypatch.setenv("SMS_PROVIDER", "fake")
    monkeypatch.setenv("PAYMENT_PROVIDER", "fake")
    monkeypatch.setenv("UPLOAD_ROOT", str(tmp_path / "uploads"))

    return create_app(
        "testing",
        {
            "PROPAGATE_EXCEPTIONS": False,
            "SERVER_NAME": "localhost",
        },
    )


@pytest.fixture
def client(app):  # type: ignore[no-untyped-def]
    return app.test_client()
