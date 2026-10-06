"""Helpers for staging staff content mutations for principal approval."""

from __future__ import annotations

from uuid import UUID

from flask import current_app
from flask_jwt_extended import get_jwt, get_jwt_identity

from app.services.governance import governance_service_from_container


def stage_change(
    resource_type: str,
    resource_key: str,
    action: str,
    payload: dict | None = None,
    *,
    resource_id: UUID | None = None,
):  # type: ignore[no-untyped-def]
    role = get_jwt().get("role")
    if role == "super_admin":
        return None
    approval = governance_service_from_container(
        current_app.extensions["container"]
    ).submit_change(
        resource_type=resource_type,
        resource_key=resource_key,
        resource_id=resource_id,
        action=action,
        payload=payload,
        actor_id=UUID(get_jwt_identity()),
        actor_role=role,
    )
    return {"data": {"approval": approval}}, 202
