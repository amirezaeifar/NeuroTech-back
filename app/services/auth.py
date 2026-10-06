"""Authentication use cases and transaction orchestration."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import attributes, selectinload

from app.core.auth_models import (
    AuthSession,
    EmailIdentity,
    Invitation,
    PasswordCredential,
    PhoneIdentity,
    User,
    UserProfile,
)
from app.core.auth_repository import AuthRepository
from app.core.security import hash_password, keyed_digest, verify_password
from app.core.unit_of_work import SqlAlchemyUnitOfWork
from app.domain.auth import Role, UserStatus, normalize_email, normalize_phone
from app.domain.errors import AuthenticationError, ConflictError, ValidationError
from app.domain.ports import EmailSender
from app.services.email_templates import account_verification


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
    avatar_url: str | None


@dataclass(frozen=True, slots=True)
class InvitationOutcome:
    outcome: str
    user: UserView | None = None


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
        avatar_url=f"/api/v1/me/avatar?file={user.avatar_file_id}" if user.avatar_file_id else None,
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
                user = User(display_name=display_name, role=Role.USER.value,
                    status=UserStatus.PENDING.value)
                user.emails.append(EmailIdentity(email=normalized))
                user.credential = PasswordCredential(password_hash=hash_password(password))
                repo.add_user(user)
                uow.commit()
                result = user_view(user)
        except IntegrityError as error:
            raise ConflictError("An account with this email already exists.") from error

        token = self.serializer.dumps({"email": normalized})
        subject, body = account_verification(
            f"{self.frontend_url}/#/login?verify_email={token}"
        )
        self.email_sender.send(normalized, subject, body)
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
            if user.status == UserStatus.PENDING.value:
                user.status = UserStatus.ACTIVE.value
                user.activated_at = datetime.now(UTC)
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
        subject, body = account_verification(
            f"{self.frontend_url}/#/login?verify_email={token}"
        )
        self.email_sender.send(normalized, subject, body)

    def create_invitation(self, email: str, role: str) -> InvitationOutcome:
        normalized = normalize_email(email)
        allowed_roles = {item.value for item in Role}
        if role not in allowed_roles:
            raise ValidationError("The requested role is invalid.")

        with self.uow_factory() as uow:
            existing_user = AuthRepository(uow.session).user_by_email(normalized)
            if existing_user is not None:
                changed = role != existing_user.role
                if changed:
                    self._assert_super_admin_remains(uow.session, existing_user, role)
                    existing_user.role = role
                    uow.commit()
                result = user_view(existing_user)

        if existing_user is not None:
            if changed:
                self.email_sender.send(
                    normalized,
                    "Your NeuroTech access has been updated",
                    f"Your NeuroTech role is now {role}.",
                )
                return InvitationOutcome("access_updated", result)
            return InvitationOutcome("access_unchanged", result)

        raw_token = secrets.token_urlsafe(32)
        invitation = Invitation(
            email=normalized,
            role=role,
            token_digest=keyed_digest(self.secret_key, raw_token),
            expires_at=datetime.now(UTC) + timedelta(days=7),
        )
        with self.uow_factory() as uow:
            # Only the newest outstanding link for an email remains valid.
            uow.session.execute(
                delete(Invitation).where(
                    Invitation.email == normalized,
                    Invitation.accepted_at.is_(None),
                )
            )
            uow.session.add(invitation)
            uow.commit()
        self.email_sender.send(
            normalized,
            "Your NeuroTech invitation",
            f"Invitation link: {self.frontend_url}/#/login?invitation={raw_token}",
        )
        return InvitationOutcome("invitation_sent")

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
            if uow.session.scalar(select(User.id).where(User.role == Role.SUPER_ADMIN.value)):
                raise ConflictError(
                    "A principal administrator already exists; use role management."
                )
            if AuthRepository(uow.session).user_by_email(normalized):
                raise ConflictError("An account with this email already exists.")
            user = User(display_name=_display_name(display_name), role=Role.SUPER_ADMIN.value)
            user.emails.append(EmailIdentity(email=normalized, verified_at=datetime.now(UTC)))
            user.credential = PasswordCredential(password_hash=hash_password(password))
            uow.session.add(user)
            uow.commit()
            return user_view(user)

    def change_user_role(self, user_id: UUID, role: str) -> UserView:
        if role not in {item.value for item in Role}:
            raise ValidationError("The requested role is invalid.")
        with self.uow_factory() as uow:
            user = AuthRepository(uow.session).user_by_id(user_id)
            if user is None:
                raise AuthenticationError("User no longer exists.")
            if user.status != UserStatus.ACTIVE.value:
                raise AuthenticationError("This account is not active.")
            self._assert_super_admin_remains(uow.session, user, role)
            user.role = role
            uow.commit()
            return user_view(user)

    @staticmethod
    def _assert_super_admin_remains(  # type: ignore[no-untyped-def]
        session, user: User, next_role: str
    ) -> None:
        if user.role != Role.SUPER_ADMIN.value or next_role == Role.SUPER_ADMIN.value:
            return
        principals = session.scalar(
            select(func.count(User.id)).where(
                User.role == Role.SUPER_ADMIN.value,
                User.status == UserStatus.ACTIVE.value,
                User.archived_at.is_(None),
            )
        )
        if int(principals or 0) <= 1:
            raise ConflictError("The last active principal administrator cannot be reassigned.")

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
            self._expire_inactive(uow, user)
            identity = next(item for item in user.emails if item.email == normalized)
            if identity.verified_at is None:
                raise AuthenticationError("Email verification is required.")
            if user.status != UserStatus.ACTIVE.value:
                raise AuthenticationError("This account is not active.")
            return user_view(user)

    def register_phone(self, *, display_name: str, phone: str, email: str) -> UserView:
        display_name = _display_name(display_name)
        normalized = normalize_phone(phone)
        normalized_email = normalize_email(email)
        try:
            with self.uow_factory() as uow:
                repo = AuthRepository(uow.session)
                if repo.user_by_phone(normalized):
                    raise ConflictError("An account with this phone already exists.")
                if repo.user_by_email(normalized_email):
                    raise ConflictError("An account with this email already exists.")
                user = User(display_name=display_name, role=Role.USER.value,
                    status=UserStatus.PENDING.value)
                user.phones.append(PhoneIdentity(phone=normalized, verified_at=datetime.now(UTC)))
                user.emails.append(EmailIdentity(email=normalized_email))
                repo.add_user(user)
                uow.commit()
                result = user_view(user)
        except IntegrityError as error:
            raise ConflictError("An account with this phone or email already exists.") from error
        token = self.serializer.dumps({"email": normalized_email})
        subject, body = account_verification(
            f"{self.frontend_url}/#/login?verify_email={token}"
        )
        self.email_sender.send(normalized_email, subject, body)
        return result

    def user_for_phone_login(self, phone: str) -> UserView | None:
        normalized = normalize_phone(phone)
        with self.uow_factory() as uow:
            user = AuthRepository(uow.session).user_by_phone(normalized)
            if user is None:
                return None
            self._expire_inactive(uow, user)
            if user.status != UserStatus.ACTIVE.value:
                return None
            return user_view(user)

    @staticmethod
    def _expire_inactive(uow, user: User) -> None:
        if user.status == UserStatus.ACTIVE.value and user.last_active_at and _utc(user.last_active_at) < datetime.now(UTC) - timedelta(days=30):
            uow.session.execute(
                update(User.__table__)
                .where(User.id == user.id, User.status == UserStatus.ACTIVE.value)
                .values(status=UserStatus.SUSPENDED.value, version=User.version + 1)
            )
            uow.commit()
            attributes.set_committed_value(user, "status", UserStatus.SUSPENDED.value)

    def get_user(self, user_id: UUID) -> UserView:
        with self.uow_factory() as uow:
            user = AuthRepository(uow.session).user_by_id(user_id)
            if user is None:
                raise AuthenticationError("User no longer exists.")
            if user.status != UserStatus.ACTIVE.value:
                raise AuthenticationError("This account is not active.")
            now = datetime.now(UTC)
            if user.last_active_at and _utc(user.last_active_at) < now - timedelta(days=30):
                self._expire_inactive(uow, user)
                raise AuthenticationError("This account is inactive after 30 days without activity.")
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
                self._expire_inactive(uow, user)
                view = user_view(user)
                profile = uow.session.scalar(select(UserProfile).where(UserProfile.user_id == user.id))
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
                        "activated_at": user.activated_at.isoformat() if user.activated_at else None,
                        "last_active_at": user.last_active_at.isoformat() if user.last_active_at else None,
                        "profile": {
                            "full_name": profile.full_name,
                            "email": profile.email,
                            "phone": profile.phone,
                            "national_id": profile.national_id,
                            "address": profile.address,
                            "city": profile.city,
                            "postal_code": profile.postal_code,
                        } if profile else None,
                    }
                )
            return result

    def update_user_details(self, user_id: UUID, data: dict, actor_role: str) -> dict:
        with self.uow_factory() as uow:
            user = AuthRepository(uow.session).user_by_id(user_id)
            if user is None:
                raise AuthenticationError("User no longer exists.")
            if user.role == Role.SUPER_ADMIN.value and actor_role != Role.SUPER_ADMIN.value:
                raise ValidationError("Only the principal administrator can edit a principal account.")
            if "display_name" in data:
                user.display_name = _display_name(data["display_name"])
            if "status" in data:
                if data["status"] not in {"active", "suspended"}:
                    raise ValidationError("Invalid account status.")
                self._assert_super_admin_remains(uow.session, user, user.role if data["status"] == "active" else "user")
                user.status = data["status"]
            if "profile" in data:
                profile = uow.session.scalar(select(UserProfile).where(UserProfile.user_id == user_id))
                if profile is not None:
                    for key, value in data["profile"].items():
                        setattr(profile, key, value)
            uow.commit()
            return {"id": str(user.id), "display_name": user.display_name, "status": user.status}

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
            user = uow.session.get(User, user_id)
            if user is not None:
                user.activated_at = user.activated_at or now
                user.last_active_at = now
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
