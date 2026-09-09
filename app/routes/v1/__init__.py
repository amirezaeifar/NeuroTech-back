"""Version 1 API blueprint."""

from __future__ import annotations

from flask_smorest import Blueprint

api_v1 = Blueprint(
    "api_v1",
    __name__,
    url_prefix="/api/v1",
    description="Version 1 of the NeuroTech public API.",
)

from app.routes.v1 import academy as academy  # noqa: E402,F401
from app.routes.v1 import auth as auth  # noqa: E402,F401
from app.routes.v1 import commerce as commerce  # noqa: E402,F401
from app.routes.v1 import health as health  # noqa: E402,F401
from app.routes.v1 import learning as learning  # noqa: E402,F401
