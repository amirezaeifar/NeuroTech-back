"""Role-based route guards."""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps

from flask_jwt_extended import get_jwt, jwt_required

from app.domain.errors import AuthorizationError


def roles_required(*roles: str):  # type: ignore[no-untyped-def]
    def decorator(function: Callable):  # type: ignore[no-untyped-def]
        @wraps(function)
        @jwt_required()
        def wrapped(*args, **kwargs):  # type: ignore[no-untyped-def]
            if get_jwt().get("role") not in roles:
                raise AuthorizationError("This role cannot perform the requested action.")
            return function(*args, **kwargs)

        return wrapped

    return decorator
