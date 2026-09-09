"""Authentication HTTP endpoints."""

from __future__ import annotations

from dataclasses import asdict
from uuid import UUID, uuid4

from flask import current_app, jsonify, request
from flask_jwt_extended import (
    create_access_token,
    create_refresh_token,
    decode_token,
    get_jwt,
    get_jwt_identity,
    jwt_required,
    set_access_cookies,
    set_refresh_cookies,
    unset_jwt_cookies,
)
from marshmallow import Schema, fields, validate

from app.core.extensions import limiter
from app.core.otp import RedisOtpService
from app.core.security import keyed_digest
from app.domain.auth import normalize_email, normalize_phone
from app.domain.errors import AuthenticationError
from app.routes.authz import roles_required
from app.routes.v1 import api_v1
from app.services.auth import UserView, auth_service_from_container


class PasswordRegistrationSchema(Schema):
    display_name = fields.String(required=True, validate=validate.Length(min=2, max=120))
    email = fields.Email(required=True)
    password = fields.String(
        required=True, load_only=True, validate=validate.Length(min=10, max=128)
    )


class PasswordLoginSchema(Schema):
    email = fields.Email(required=True)
    password = fields.String(required=True, load_only=True)


class PhoneRequestSchema(Schema):
    phone = fields.String(required=True, validate=validate.Length(min=7, max=24))


class PhoneRegistrationVerifySchema(PhoneRequestSchema):
    display_name = fields.String(required=True, validate=validate.Length(min=2, max=120))
    challenge_id = fields.UUID(required=True)
    code = fields.String(required=True, validate=validate.Regexp(r"^\d{6}$"))


class PhoneLoginVerifySchema(PhoneRequestSchema):
    challenge_id = fields.UUID(required=True)
    code = fields.String(required=True, validate=validate.Regexp(r"^\d{6}$"))


class EmailVerificationSchema(Schema):
    token = fields.String(required=True)


class EmailSchema(Schema):
    email = fields.Email(required=True)


class ProfileUpdateSchema(Schema):
    display_name = fields.String(required=True, validate=validate.Length(min=2, max=120))


class InvitationCreateSchema(EmailSchema):
    role = fields.String(required=True, validate=validate.OneOf(["specialist", "admin"]))


class InvitationAcceptSchema(Schema):
    token = fields.String(required=True, validate=validate.Length(min=20, max=200))
    display_name = fields.String(required=True, validate=validate.Length(min=2, max=120))
    password = fields.String(
        required=True, load_only=True, validate=validate.Length(min=10, max=128)
    )


def _container():  # type: ignore[no-untyped-def]
    return current_app.extensions["container"]


def _auth_service():  # type: ignore[no-untyped-def]
    return auth_service_from_container(_container())


def _otp_service() -> RedisOtpService:
    container = _container()
    return RedisOtpService(
        container.redis,
        container.sms_sender,
        container.settings.jwt_secret_key,
    )


def _user_payload(user: UserView) -> dict:
    payload = asdict(user)
    payload["id"] = str(payload["id"])
    return payload


def _issue_session(user: UserView):  # type: ignore[no-untyped-def]
    session_id = uuid4()
    claims = {"sid": str(session_id), "role": user.role}
    refresh_token = create_refresh_token(identity=str(user.id), additional_claims=claims)
    refresh_jti = decode_token(refresh_token)["jti"]
    _auth_service().create_session(
        session_id=session_id,
        user_id=user.id,
        refresh_jti=refresh_jti,
        ip_address=request.remote_addr,
        user_agent=request.user_agent.string,
    )
    access_token = create_access_token(identity=str(user.id), additional_claims=claims)
    response = jsonify({"data": {"user": _user_payload(user)}})
    set_access_cookies(response, access_token)
    set_refresh_cookies(response, refresh_token)
    return response


def _verify_phone_challenge(data: dict, purpose: str) -> str:
    phone = normalize_phone(data["phone"])
    identity_hash, actual_purpose = _otp_service().verify(
        challenge_id=str(data["challenge_id"]), code=data["code"]
    )
    expected_hash = keyed_digest(_container().settings.jwt_secret_key, phone)
    if identity_hash != expected_hash or actual_purpose != purpose:
        raise AuthenticationError("The verification code is invalid or expired.")
    return phone


@api_v1.post("/auth/register/password")
@limiter.limit("5 per hour")
@api_v1.arguments(PasswordRegistrationSchema)
def register_password(data: dict):  # type: ignore[no-untyped-def]
    user = _auth_service().register_password(**data)
    return {"data": {"user": _user_payload(user), "verification_required": True}}, 201


@api_v1.post("/auth/email/verify")
@limiter.limit("10 per hour")
@api_v1.arguments(EmailVerificationSchema)
def verify_email(data: dict):  # type: ignore[no-untyped-def]
    user = _auth_service().verify_email(data["token"])
    return {"data": {"user": _user_payload(user)}}


@api_v1.post("/auth/email/resend")
@limiter.limit("5 per hour")
@api_v1.arguments(EmailSchema)
def resend_email(data: dict):  # type: ignore[no-untyped-def]
    _auth_service().resend_email_verification(data["email"])
    return {"data": {"accepted": True}}, 202


@api_v1.post("/auth/invitations/accept")
@limiter.limit("5 per hour")
@api_v1.arguments(InvitationAcceptSchema)
def accept_invitation(data: dict):  # type: ignore[no-untyped-def]
    user = _auth_service().accept_invitation(**data)
    response = _issue_session(user)
    response.status_code = 201
    return response


@api_v1.post("/admin/invitations")
@roles_required("admin")
@api_v1.arguments(InvitationCreateSchema)
def create_invitation(data: dict):  # type: ignore[no-untyped-def]
    _auth_service().create_invitation(data["email"], data["role"])
    return {"data": {"accepted": True}}, 202


@api_v1.get("/admin/users")
@roles_required("admin")
def list_users():  # type: ignore[no-untyped-def]
    return {"data": _auth_service().list_users()}


@api_v1.post("/auth/login/password")
@limiter.limit("10 per 15 minutes")
@api_v1.arguments(PasswordLoginSchema)
def login_password(data: dict):  # type: ignore[no-untyped-def]
    normalized = normalize_email(data["email"])
    otp = _otp_service()
    otp.assert_password_login_allowed(normalized)
    try:
        user = _auth_service().authenticate_password(email=normalized, password=data["password"])
    except AuthenticationError:
        otp.record_password_failure(normalized)
        raise
    otp.clear_password_failures(normalized)
    return _issue_session(user)


@api_v1.post("/auth/register/phone/request-otp")
@limiter.limit("10 per hour")
@api_v1.arguments(PhoneRequestSchema)
def request_registration_otp(data: dict):  # type: ignore[no-untyped-def]
    phone = normalize_phone(data["phone"])
    if _auth_service().user_for_phone_login(phone) is not None:
        raise AuthenticationError("This phone cannot be used for registration.")
    challenge = _otp_service().request(
        phone=phone, purpose="register", ip_address=request.remote_addr or "unknown"
    )
    return {"data": asdict(challenge)}, 202


@api_v1.post("/auth/register/phone/verify-otp")
@limiter.limit("10 per 15 minutes")
@api_v1.arguments(PhoneRegistrationVerifySchema)
def verify_registration_otp(data: dict):  # type: ignore[no-untyped-def]
    phone = _verify_phone_challenge(data, "register")
    user = _auth_service().register_phone(display_name=data["display_name"], phone=phone)
    return _issue_session(user)


@api_v1.post("/auth/login/otp/request")
@limiter.limit("10 per hour")
@api_v1.arguments(PhoneRequestSchema)
def request_login_otp(data: dict):  # type: ignore[no-untyped-def]
    phone = normalize_phone(data["phone"])
    user = _auth_service().user_for_phone_login(phone)
    if user is None:
        # Preserve a uniform public response without spending an SMS for an
        # unknown account. Verification of this opaque id will simply fail.
        return {"data": {"challenge_id": str(uuid4()), "expires_in": 300, "resend_after": 60}}, 202
    challenge = _otp_service().request(
        phone=phone, purpose="login", ip_address=request.remote_addr or "unknown"
    )
    return {"data": asdict(challenge)}, 202


@api_v1.post("/auth/login/otp/verify")
@limiter.limit("10 per 15 minutes")
@api_v1.arguments(PhoneLoginVerifySchema)
def verify_login_otp(data: dict):  # type: ignore[no-untyped-def]
    phone = _verify_phone_challenge(data, "login")
    user = _auth_service().user_for_phone_login(phone)
    if user is None:
        raise AuthenticationError("The verification code is invalid or expired.")
    return _issue_session(user)


@api_v1.post("/auth/refresh")
@limiter.limit("30 per minute")
@jwt_required(refresh=True)
def refresh():  # type: ignore[no-untyped-def]
    payload = get_jwt()
    user = _auth_service().get_user(UUID(get_jwt_identity()))
    next_refresh = create_refresh_token(
        identity=str(user.id),
        additional_claims={"sid": payload["sid"], "role": user.role},
    )
    next_jti = decode_token(next_refresh)["jti"]
    _auth_service().rotate_session(
        session_id=UUID(payload["sid"]), presented_jti=payload["jti"], next_jti=next_jti
    )
    access = create_access_token(
        identity=str(user.id),
        additional_claims={"sid": payload["sid"], "role": user.role},
    )
    response = jsonify({"data": {"user": _user_payload(user)}})
    set_access_cookies(response, access)
    set_refresh_cookies(response, next_refresh)
    return response


@api_v1.post("/auth/logout")
@jwt_required()
def logout():  # type: ignore[no-untyped-def]
    _auth_service().revoke_session(UUID(get_jwt()["sid"]))
    response = jsonify({"data": {"logged_out": True}})
    unset_jwt_cookies(response)
    return response


@api_v1.post("/auth/logout-all")
@jwt_required()
def logout_all():  # type: ignore[no-untyped-def]
    _auth_service().revoke_all_sessions(UUID(get_jwt_identity()))
    response = jsonify({"data": {"logged_out": True}})
    unset_jwt_cookies(response)
    return response


@api_v1.get("/me")
@jwt_required()
def me():  # type: ignore[no-untyped-def]
    user = _auth_service().get_user(UUID(get_jwt_identity()))
    return {"data": {"user": _user_payload(user)}}


@api_v1.patch("/me")
@jwt_required()
@api_v1.arguments(ProfileUpdateSchema)
def update_me(data: dict):  # type: ignore[no-untyped-def]
    user = _auth_service().update_profile(UUID(get_jwt_identity()), data["display_name"])
    return {"data": {"user": _user_payload(user)}}
