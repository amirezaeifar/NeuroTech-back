"""Authentication use cases and transaction orchestration."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app.core.auth_models import (
    AuthSession,
    EmailIdentity,
    Invitation,
    PasswordCredential,
    PhoneIdentity,
    User,
)
from app.core.auth_repository import AuthRepository
from app.core.security import hash_password, keyed_digest, verify_password
from app.core.unit_of_work import SqlAlchemyUnitOfWork
from app.domain.auth import Role, UserStatus, normalize_email, normalize_phone
from app.domain.errors import AuthenticationError, ConflictError, ValidationError
from app.domain.ports import EmailSender


@dataclass(frozen=True, slots=True)
class UserView:
    id: UUID
    display_name: str
    role: str
    status: str
    email: str | None
    email_verified: bool
    phone: str | None
    phone_verified: bool


def user_view(user: User) -> UserView:
    email = user.emails[0] if user.emails else None
    phone = user.phones[0] if user.phones else None
    return UserView(
        id=user.id,
        display_name=user.display_name,
        role=user.role,
        status=user.status,
        email=email.email if email else None,
        email_verified=bool(email and email.verified_at),
        phone=phone.phone if phone else None,
        phone_verified=bool(phone and phone.verified_at),
    )


class AuthService:
    def __init__(
        self,
        uow_factory,  # type: ignore[no-untyped-def]
        email_sender: EmailSender,
        secret_key: str,
        refresh_days: int,
        session_max_days: int,
        frontend_url: str,
    ) -> None:
        self.uow_factory = uow_factory
        self.email_sender = email_sender
        self.secret_key = secret_key
        self.serializer = URLSafeTimedSerializer(secret_key, salt="email-verification")
        self.refresh_days = refresh_days
        self.session_max_days = session_max_days
        self.frontend_url = frontend_url.rstrip("/")

    def register_password(self, *, display_name: str, email: str, password: str) -> UserView:
        display_name = _display_name(display_name)
        normalized = normalize_email(email)
        _validate_password(password)
        try:
            with self.uow_factory() as uow:
                repo = AuthRepository(uow.session)
                if repo.user_by_email(normalized):
                    raise ConflictError("An account with this email already exists.")
                user = User(display_name=display_name, role=Role.USER.value)
                user.emails.append(EmailIdentity(email=normalized))
                user.credential = PasswordCredential(password_hash=hash_password(password))
                repo.add_user(user)
                uow.commit()
                result = user_view(user)
        except IntegrityError as error:
            raise ConflictError("An account with this email already exists.") from error

        token = self.serializer.dumps({"email": normalized})
        self.email_sender.send(
            normalized,
            "Verify your NeuroTech email",
            f"Verification link: {self.frontend_url}/#/login?verify_email={token}",
        )
        return result

    def verify_email(self, token: str) -> UserView:
        try:
            payload = self.serializer.loads(token, max_age=86_400)
            email = normalize_email(payload["email"])
        except (BadSignature, SignatureExpired, KeyError, TypeError, ValueError) as error:
            raise AuthenticationError(
                "The email verification token is invalid or expired."
            ) from error
        with self.uow_factory() as uow:
            repo = AuthRepository(uow.session)
            user = repo.user_by_email(email)
            if user is None:
                raise AuthenticationError("The email verification token is invalid or expired.")
            identity = next(item for item in user.emails if item.email == email)
            identity.verified_at = identity.verified_at or datetime.now(UTC)
            uow.commit()
            return user_view(user)

    def resend_email_verification(self, email: str) -> None:
        normalized = normalize_email(email)
        with self.uow_factory() as uow:
            user = AuthRepository(uow.session).user_by_email(normalized)
            if user is None:
                return
            identity = next(item for item in user.emails if item.email == normalized)
            if identity.verified_at is not None:
                return
        token = self.serializer.dumps({"email": normalized})
        self.email_sender.send(
            normalized,
            "Verify your NeuroTech email",
            f"Verification link: {self.frontend_url}/#/login?verify_email={token}",
        )

    def create_invitation(self, email: str, role: str) -> None:
        normalized = normalize_email(email)
        if role not in {Role.SPECIALIST.value, Role.ADMIN.value}:
            raise ValidationError("Only specialist and admin roles can be invited.")
        raw_token = secrets.token_urlsafe(32)
        invitation = Invitation(
            email=normalized,
            role=role,
            token_digest=keyed_digest(self.secret_key, raw_token),
            expires_at=datetime.now(UTC) + timedelta(days=7),
        )
        with self.uow_factory() as uow:
            if AuthRepository(uow.session).user_by_email(normalized):
                raise ConflictError("An account with this email already exists.")
            uow.session.add(invitation)
            uow.commit()
        self.email_sender.send(
            normalized,
            "Your NeuroTech invitation",
            f"Invitation link: {self.frontend_url}/#/login?invitation={raw_token}",
        )

    def accept_invitation(self, token: str, display_name: str, password: str) -> UserView:
        _validate_password(password)
        digest = keyed_digest(self.secret_key, token)
        now = datetime.now(UTC)
        with self.uow_factory() as uow:
            invitation = uow.session.scalar(
                select(Invitation).where(Invitation.token_digest == digest).with_for_update()
            )
            if invitation is None or invitation.accepted_at is not None:
                raise AuthenticationError("Invitation is invalid or has already been used.")
            expires_at = _utc(invitation.expires_at)
            if expires_at <= now:
                raise AuthenticationError("Invitation has expired.")
            if AuthRepository(uow.session).user_by_email(invitation.email):
                raise ConflictError("An account with this email already exists.")
            user = User(display_name=_display_name(display_name), role=invitation.role)
            user.emails.append(EmailIdentity(email=invitation.email, verified_at=now))
            user.credential = PasswordCredential(password_hash=hash_password(password))
            uow.session.add(user)
            invitation.accepted_at = now
            uow.commit()
            return user_view(user)

    def bootstrap_admin(self, display_name: str, email: str, password: str) -> UserView:
        normalized = normalize_email(email)
        _validate_password(password)
        with self.uow_factory() as uow:
            if uow.session.scalar(select(User.id).where(User.role == Role.ADMIN.value)):
                raise ConflictError("An admin account already exists; use an invitation.")
            if AuthRepository(uow.session).user_by_email(normalized):
                raise ConflictError("An account with this email already exists.")
            user = User(display_name=_display_name(display_name), role=Role.ADMIN.value)
            user.emails.append(EmailIdentity(email=normalized, verified_at=datetime.now(UTC)))
            user.credential = PasswordCredential(password_hash=hash_password(password))
            uow.session.add(user)
            uow.commit()
            return user_view(user)

    def authenticate_password(self, *, email: str, password: str) -> UserView:
        normalized = normalize_email(email)
        with self.uow_factory() as uow:
            user = AuthRepository(uow.session).user_by_email(normalized)
            if (
                user is None
                or user.credential is None
                or not verify_password(user.credential.password_hash, password)
            ):
                raise AuthenticationError("Email or password is incorrect.")
            if user.status != UserStatus.ACTIVE.value:
                raise AuthenticationError("This account is not active.")
            identity = next(item for item in user.emails if item.email == normalized)
            if identity.verified_at is None:
                raise AuthenticationError("Email verification is required.")
            return user_view(user)

    def register_phone(self, *, display_name: str, phone: str) -> UserView:
        display_name = _display_name(display_name)
        normalized = normalize_phone(phone)
        try:
            with self.uow_factory() as uow:
                repo = AuthRepository(uow.session)
                if repo.user_by_phone(normalized):
                    raise ConflictError("An account with this phone already exists.")
                user = User(display_name=display_name, role=Role.USER.value)
                user.phones.append(PhoneIdentity(phone=normalized, verified_at=datetime.now(UTC)))
                repo.add_user(user)
                uow.commit()
                return user_view(user)
        except IntegrityError as error:
            raise ConflictError("An account with this phone already exists.") from error

    def user_for_phone_login(self, phone: str) -> UserView | None:
        normalized = normalize_phone(phone)
        with self.uow_factory() as uow:
            user = AuthRepository(uow.session).user_by_phone(normalized)
            if user is None or user.status != UserStatus.ACTIVE.value:
                return None
            return user_view(user)

    def get_user(self, user_id: UUID) -> UserView:
        with self.uow_factory() as uow:
            user = AuthRepository(uow.session).user_by_id(user_id)
            if user is None:
                raise AuthenticationError("User no longer exists.")
            return user_view(user)

    def list_users(self) -> list[dict]:
        with self.uow_factory() as uow:
            users = list(
                uow.session.scalars(
                    select(User)
                    .options(selectinload(User.emails), selectinload(User.phones))
                    .order_by(User.created_at.desc(), User.id)
                ).unique()
            )
            result = []
            for user in users:
                view = user_view(user)
                result.append(
                    {
                        "id": str(view.id),
                        "display_name": view.display_name,
                        "role": view.role,
                        "status": view.status,
                        "email": view.email,
                        "email_verified": view.email_verified,
                        "phone": view.phone,
                        "phone_verified": view.phone_verified,
                        "created_at": user.created_at.isoformat(),
                    }
                )
            return result

    def update_profile(self, user_id: UUID, display_name: str) -> UserView:
        with self.uow_factory() as uow:
            user = AuthRepository(uow.session).user_by_id(user_id)
            if user is None:
                raise AuthenticationError("User no longer exists.")
            user.display_name = _display_name(display_name)
            uow.commit()
            return user_view(user)

    def create_session(
        self,
        *,
        session_id: UUID,
        user_id: UUID,
        refresh_jti: str,
        ip_address: str | None,
        user_agent: str | None,
    ) -> UUID:
        now = datetime.now(UTC)
        session = AuthSession(
            id=session_id,
            user_id=user_id,
            refresh_jti=refresh_jti,
            expires_at=now + timedelta(days=self.refresh_days),
            absolute_expires_at=now + timedelta(days=self.session_max_days),
            ip_address=ip_address,
            user_agent=(user_agent or "")[:512] or None,
        )
        with self.uow_factory() as uow:
            AuthRepository(uow.session).add_session(session)
            uow.commit()
        return session.id

    def rotate_session(self, *, session_id: UUID, presented_jti: str, next_jti: str) -> None:
        now = datetime.now(UTC)
        with self.uow_factory() as uow:
            session = AuthRepository(uow.session).session_by_id(session_id, for_update=True)
            if session is None or session.revoked_at is not None:
                raise AuthenticationError("Session is no longer active.")
            if session.refresh_jti != presented_jti:
                session.revoked_at = now
                uow.commit()
                raise AuthenticationError("Refresh token reuse was detected.")
            if _utc(session.absolute_expires_at) <= now or _utc(session.expires_at) <= now:
                session.revoked_at = now
                uow.commit()
                raise AuthenticationError("Session has expired.")
            session.refresh_jti = next_jti
            session.expires_at = min(
                now + timedelta(days=self.refresh_days), _utc(session.absolute_expires_at)
            )
            uow.commit()

    def revoke_session(self, session_id: UUID) -> None:
        with self.uow_factory() as uow:
            session = AuthRepository(uow.session).session_by_id(session_id)
            if session is not None and session.revoked_at is None:
                session.revoked_at = datetime.now(UTC)
                uow.commit()

    def revoke_all_sessions(self, user_id: UUID) -> None:
        with self.uow_factory() as uow:
            AuthRepository(uow.session).revoke_all_sessions(user_id, datetime.now(UTC))
            uow.commit()

    def session_is_revoked(self, session_id: UUID) -> bool:
        now = datetime.now(UTC)
        with self.uow_factory() as uow:
            session = AuthRepository(uow.session).session_by_id(session_id)
            return bool(
                session is None
                or session.revoked_at is not None
                or _utc(session.absolute_expires_at) <= now
            )


def _validate_password(password: str) -> None:
    if len(password) < 10 or len(password) > 128:
        raise ValidationError("Password must be between 10 and 128 characters.")
    if not any(char.isalpha() for char in password) or not any(char.isdigit() for char in password):
        raise ValidationError("Password must contain letters and numbers.")


def _display_name(value: str) -> str:
    normalized = " ".join(value.split())
    if not 2 <= len(normalized) <= 120:
        raise ValidationError("Display name must be between 2 and 120 characters.")
    return normalized


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def auth_service_from_container(container) -> AuthService:  # type: ignore[no-untyped-def]
    return AuthService(
        lambda: SqlAlchemyUnitOfWork(container.database.session_factory),
        container.email_sender,
        container.settings.jwt_secret_key,
        container.settings.jwt_refresh_ttl_days,
        container.settings.jwt_session_max_days,
        container.settings.frontend_url,
    )
