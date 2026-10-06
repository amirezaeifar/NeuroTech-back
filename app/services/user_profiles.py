"""User-owned contact profile orchestration."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select

from app.core.auth_models import User, UserProfile
from app.core.unit_of_work import SqlAlchemyUnitOfWork
from app.domain.auth import normalize_email, normalize_phone
from app.domain.errors import NotFoundError, ValidationError


class UserProfileService:
    def __init__(self, uow_factory) -> None:  # type: ignore[no-untyped-def]
        self.uow_factory = uow_factory

    def get(self, user_id: UUID) -> dict:
        with self.uow_factory() as uow:
            profile = uow.session.scalar(
                select(UserProfile).where(UserProfile.user_id == user_id)
            )
            if profile is not None:
                return _payload(profile)
            user = uow.session.get(User, user_id)
            if user is None:
                raise NotFoundError("User does not exist.")
            return {
                "full_name": user.display_name,
                "email": user.emails[0].email if user.emails else "",
                "phone": user.phones[0].phone if user.phones else "",
                "national_id": "",
                "address": "",
                "complete": False,
            }

    def save(self, user_id: UUID, data: dict) -> dict:
        full_name = " ".join(data["full_name"].split())
        if not 2 <= len(full_name) <= 160:
            raise ValidationError("Full name must be between 2 and 160 characters.")
        try:
            email = normalize_email(data["email"]) if data["email"] else ""
            phone = normalize_phone(data["phone"]) if data["phone"] else ""
        except ValueError as error:
            raise ValidationError(str(error)) from error
        values = {
            "full_name": full_name,
            "email": email,
            "phone": phone,
            "national_id": (data.get("national_id") or "").strip() or None,
            "address": " ".join((data.get("address") or "").split()) or None,
        }
        with self.uow_factory() as uow:
            user = uow.session.get(User, user_id)
            if user is None:
                raise NotFoundError("User does not exist.")
            user.display_name = full_name
            profile = uow.session.scalar(
                select(UserProfile).where(UserProfile.user_id == user_id)
            )
            if profile is None:
                profile = UserProfile(user_id=user_id, **values)
                uow.session.add(profile)
            else:
                for key, value in values.items():
                    setattr(profile, key, value)
            uow.commit()
            return _payload(profile)


def user_profile_service_from_container(container) -> UserProfileService:  # type: ignore[no-untyped-def]
    return UserProfileService(
        lambda: SqlAlchemyUnitOfWork(container.database.session_factory)
    )


def _payload(profile: UserProfile) -> dict:
    return {
        "full_name": profile.full_name,
        "email": profile.email,
        "phone": profile.phone,
        "national_id": profile.national_id or "",
        "address": profile.address or "",
        "complete": bool(profile.full_name and profile.email and profile.phone),
    }
