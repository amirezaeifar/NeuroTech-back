from __future__ import annotations

from uuid import uuid4

from argon2 import PasswordHasher
from redis.exceptions import RedisError

from app import create_app
from app.core.models import Base
from app.core.security import keyed_digest
from app.services.auth import auth_service_from_container


def test_auth_rate_limit_returns_retry_after(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("TEST_DATABASE_URL", "sqlite+pysqlite://")
    monkeypatch.setenv("TEST_REDIS_NAMESPACE", f"neurotech:test:rate-limit:{uuid4()}")
    monkeypatch.setattr(
        "app.core.security._password_hasher",
        PasswordHasher(time_cost=1, memory_cost=8192, parallelism=1),
    )
    application = create_app("testing", {"RATELIMIT_ENABLED": True, "PROPAGATE_EXCEPTIONS": False})
    container = application.extensions["container"]
    Base.metadata.create_all(container.database.engine)
    redis_keys = list(container.redis.client.scan_iter(match=container.redis.key("*")))
    if redis_keys:
        container.redis.client.delete(*redis_keys)
    client = application.test_client()

    for index in range(5):
        response = client.post(
            "/api/v1/auth/register/password",
            json={
                "display_name": "Rate Test",
                "email": f"rate-{index}@example.com",
                "password": "secure-pass-123",
            },
        )
        assert response.status_code == 201
    limited = client.post(
        "/api/v1/auth/register/password",
        json={
            "display_name": "Rate Test",
            "email": "rate-limited@example.com",
            "password": "secure-pass-123",
        },
    )
    assert limited.status_code == 429
    assert limited.headers.get("Retry-After") is not None
    redis_keys = list(container.redis.client.scan_iter(match=f"*{container.redis.namespace}*"))
    if redis_keys:
        container.redis.client.delete(*redis_keys)
    container.database.dispose()
    container.redis.close()


def test_otp_fails_closed_when_redis_is_unavailable(client, app, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def unavailable(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        def execute(*_script_args, **_script_kwargs):  # type: ignore[no-untyped-def]
            raise RedisError("offline")

        return execute

    monkeypatch.setattr(app.extensions["container"].redis.client, "register_script", unavailable)
    response = client.post(
        "/api/v1/auth/register/phone/request-otp", json={"phone": "+989121234567"}
    )
    assert response.status_code == 503
    assert response.get_json()["code"] == "AUTH_TEMPORARILY_UNAVAILABLE"


def test_otp_cooldown_returns_429_with_retry_after(client) -> None:  # type: ignore[no-untyped-def]
    payload = {"phone": "+989121234568"}
    assert client.post("/api/v1/auth/register/phone/request-otp", json=payload).status_code == 202

    response = client.post("/api/v1/auth/register/phone/request-otp", json=payload)

    assert response.status_code == 429
    assert response.get_json()["code"] == "RATE_LIMIT_EXCEEDED"
    assert int(response.headers["Retry-After"]) > 0


def test_password_attempt_lock_returns_429_with_retry_after(client, app) -> None:  # type: ignore[no-untyped-def]
    auth_service_from_container(app.extensions["container"]).bootstrap_admin(
        "Lock Test", "lock-test@example.com", "secure-pass-123"
    )
    payload = {"email": "lock-test@example.com", "password": "wrong-password-123"}
    for _ in range(5):
        assert client.post("/api/v1/auth/login/password", json=payload).status_code == 401

    response = client.post("/api/v1/auth/login/password", json=payload)

    assert response.status_code == 429
    assert response.get_json()["code"] == "RATE_LIMIT_EXCEEDED"
    assert int(response.headers["Retry-After"]) > 0


def test_otp_identity_hourly_limit_is_five(client, app) -> None:  # type: ignore[no-untyped-def]
    phone = "+989121234569"
    container = app.extensions["container"]
    identity_hash = keyed_digest(container.settings.jwt_secret_key, phone)
    cooldown_key = container.redis.key("otp", "cooldown", identity_hash)

    for _ in range(5):
        assert (
            client.post(
                "/api/v1/auth/register/phone/request-otp", json={"phone": phone}
            ).status_code
            == 202
        )
        container.redis.client.delete(cooldown_key)

    response = client.post("/api/v1/auth/register/phone/request-otp", json={"phone": phone})
    assert response.status_code == 429
    assert 1 <= int(response.headers["Retry-After"]) <= 3600


def test_otp_ip_hourly_limit_is_ten(client) -> None:  # type: ignore[no-untyped-def]
    for index in range(10):
        response = client.post(
            "/api/v1/auth/register/phone/request-otp",
            json={"phone": f"+98912000{index:04d}"},
        )
        assert response.status_code == 202

    response = client.post(
        "/api/v1/auth/register/phone/request-otp", json={"phone": "+989120009999"}
    )
    assert response.status_code == 429
    assert 1 <= int(response.headers["Retry-After"]) <= 3600


def test_five_wrong_otp_attempts_lock_identity_for_fifteen_minutes(client, app) -> None:  # type: ignore[no-untyped-def]
    phone = "+989121234570"
    requested = client.post("/api/v1/auth/register/phone/request-otp", json={"phone": phone})
    challenge_id = requested.get_json()["data"]["challenge_id"]
    actual_code = app.extensions["container"].sms_sender.sent_messages[-1].message[-6:]
    wrong_code = "111111" if actual_code == "000000" else "000000"
    wrong = {
        "display_name": "Locked Mobile",
        "phone": phone,
        "challenge_id": challenge_id,
        "code": wrong_code,
    }

    for _ in range(5):
        assert client.post("/api/v1/auth/register/phone/verify-otp", json=wrong).status_code == 401

    response = client.post("/api/v1/auth/register/phone/request-otp", json={"phone": phone})
    assert response.status_code == 429
    assert 800 <= int(response.headers["Retry-After"]) <= 900
