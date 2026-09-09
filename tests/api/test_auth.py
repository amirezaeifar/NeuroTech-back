from __future__ import annotations

import re


def _register_and_verify(client, app, email="member@example.com"):
    response = client.post(
        "/api/v1/auth/register/password",
        json={"display_name": "Test Member", "email": email, "password": "secure-pass-123"},
    )
    assert response.status_code == 201
    sent = app.extensions["container"].email_sender.sent_messages[-1]
    assert sent.body.startswith("Verification link: http://127.0.0.1:5173/#/login?")
    token = sent.body.split("verify_email=", 1)[1]
    response = client.post("/api/v1/auth/email/verify", json={"token": token})
    assert response.status_code == 200
    assert response.get_json()["data"]["user"]["email_verified"] is True


def _login(client, email="member@example.com"):
    response = client.post(
        "/api/v1/auth/login/password",
        json={"email": email, "password": "secure-pass-123"},
    )
    assert response.status_code == 200
    return response


def test_password_registration_verification_login_and_me(client, app) -> None:  # type: ignore[no-untyped-def]
    _register_and_verify(client, app)
    response = _login(client)

    assert "access_token_cookie=" in "\n".join(response.headers.getlist("Set-Cookie"))
    me = client.get("/api/v1/me")
    assert me.status_code == 200
    assert me.get_json()["data"]["user"]["email"] == "member@example.com"


def test_unverified_email_cannot_log_in(client, app) -> None:  # type: ignore[no-untyped-def]
    response = client.post(
        "/api/v1/auth/register/password",
        json={
            "display_name": "Pending Member",
            "email": "pending@example.com",
            "password": "secure-pass-123",
        },
    )
    assert response.status_code == 201

    response = client.post(
        "/api/v1/auth/login/password",
        json={"email": "pending@example.com", "password": "secure-pass-123"},
    )
    assert response.status_code == 401
    assert response.get_json()["code"] == "AUTHENTICATION_FAILED"


def test_phone_otp_is_hashed_and_creates_session(client, app) -> None:  # type: ignore[no-untyped-def]
    phone = "+989121234567"
    response = client.post("/api/v1/auth/register/phone/request-otp", json={"phone": phone})
    assert response.status_code == 202
    challenge_id = response.get_json()["data"]["challenge_id"]

    container = app.extensions["container"]
    message = container.sms_sender.sent_messages[-1].message
    code = re.search(r"(\d{6})$", message).group(1)
    challenge_key = container.redis.key("otp", "challenge", challenge_id)
    stored = container.redis.client.hgetall(challenge_key)
    assert code not in stored.values()
    assert "identity_hash" in stored

    response = client.post(
        "/api/v1/auth/register/phone/verify-otp",
        json={
            "display_name": "Mobile Member",
            "phone": phone,
            "challenge_id": challenge_id,
            "code": code,
        },
    )
    assert response.status_code == 200
    assert response.get_json()["data"]["user"]["phone"] == phone
    assert client.get("/api/v1/me").status_code == 200


def test_refresh_requires_csrf_and_rotates_cookie(client, app) -> None:  # type: ignore[no-untyped-def]
    _register_and_verify(client, app, "refresh@example.com")
    _login(client, "refresh@example.com")

    without_csrf = client.post("/api/v1/auth/refresh")
    assert without_csrf.status_code == 401

    csrf = client.get_cookie("csrf_refresh_token").value
    before = client.get_cookie("refresh_token_cookie", path="/api/v1/auth/refresh").value
    response = client.post("/api/v1/auth/refresh", headers={"X-CSRF-TOKEN": csrf})
    assert response.status_code == 200
    after = client.get_cookie("refresh_token_cookie", path="/api/v1/auth/refresh").value
    assert before != after


def test_logout_revokes_session(client, app) -> None:  # type: ignore[no-untyped-def]
    _register_and_verify(client, app, "logout@example.com")
    _login(client, "logout@example.com")
    csrf = client.get_cookie("csrf_access_token").value

    response = client.post("/api/v1/auth/logout", headers={"X-CSRF-TOKEN": csrf})
    assert response.status_code == 200
    assert client.get("/api/v1/me").status_code == 401
