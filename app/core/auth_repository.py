"""SQLAlchemy repository for identity data."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session, selectinload

from app.core.auth_models import AuthSession, EmailIdentity, PhoneIdentity, User


class AuthRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add_user(self, user: User) -> None:
        self.session.add(user)

    def user_by_id(self, user_id: UUID) -> User | None:
        return self.session.scalar(
            select(User)
            .options(selectinload(User.emails), selectinload(User.phones))
            .where(User.id == user_id, User.archived_at.is_(None))
        )

    def user_by_email(self, email: str) -> User | None:
        return self.session.scalar(
            select(User)
            .join(EmailIdentity)
            .options(
                selectinload(User.emails),
                selectinload(User.phones),
                selectinload(User.credential),
            )
            .where(EmailIdentity.email == email, User.archived_at.is_(None))
        )

    def user_by_phone(self, phone: str) -> User | None:
        return self.session.scalar(
            select(User)
            .join(PhoneIdentity)
            .options(selectinload(User.emails), selectinload(User.phones))
            .where(PhoneIdentity.phone == phone, User.archived_at.is_(None))
        )

    def session_by_id(self, session_id: UUID, *, for_update: bool = False) -> AuthSession | None:
        statement = select(AuthSession).where(AuthSession.id == session_id)
        if for_update:
            statement = statement.with_for_update()
        return self.session.scalar(statement)

    def add_session(self, auth_session: AuthSession) -> None:
        self.session.add(auth_session)

    def revoke_all_sessions(self, user_id: UUID, revoked_at: datetime) -> None:
        self.session.execute(
            update(AuthSession)
            .where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
            .values(revoked_at=revoked_at)
        )
