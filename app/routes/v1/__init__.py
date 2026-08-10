"""Version 1 API blueprint."""

from __future__ import annotations

from flask import Blueprint

api_v1 = Blueprint("api_v1", __name__, url_prefix="/api/v1")

from app.routes.v1 import health as health  # noqa: E402,F401
