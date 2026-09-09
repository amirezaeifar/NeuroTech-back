"""Framework extensions configured at the application boundary."""

from __future__ import annotations

from flask_jwt_extended import JWTManager
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_smorest import Api

api = Api()
jwt = JWTManager()
limiter = Limiter(key_func=get_remote_address, default_limits=[])


def init_extensions(app) -> None:  # type: ignore[no-untyped-def]
    api.init_app(app)
    jwt.init_app(app)
    limiter.init_app(app)
