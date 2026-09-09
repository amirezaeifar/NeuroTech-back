"""Flask HTTP adapter registration."""

from __future__ import annotations

from flask import Flask
from flask_cors import CORS

from app.core.extensions import api, init_extensions
from app.routes.errors import register_error_handlers
from app.routes.jwt_callbacks import register_jwt_callbacks
from app.routes.request_context import register_request_context
from app.routes.v1 import api_v1


def register_http_layer(app: Flask) -> None:
    """Register request hooks, error handling, and versioned routes."""

    register_request_context(app)
    init_extensions(app)
    register_jwt_callbacks()
    CORS(
        app,
        origins=list(app.config["CORS_ORIGINS"]),
        supports_credentials=True,
        allow_headers=["Content-Type", "X-CSRF-TOKEN", "X-Request-ID"],
    )
    api.register_blueprint(api_v1)
    # Register last so RFC 9457 remains the single error contract even when an
    # extension installs its own HTTPException handler during initialization.
    register_error_handlers(app)
