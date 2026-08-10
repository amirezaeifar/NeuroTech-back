"""Flask HTTP adapter registration."""

from __future__ import annotations

from flask import Flask

from app.routes.errors import register_error_handlers
from app.routes.request_context import register_request_context
from app.routes.v1 import api_v1


def register_http_layer(app: Flask) -> None:
    """Register request hooks, error handling, and versioned routes."""

    register_request_context(app)
    register_error_handlers(app)
    app.register_blueprint(api_v1)
