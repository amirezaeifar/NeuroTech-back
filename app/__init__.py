"""NeuroTech backend application factory."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from flask import Flask

from app.bootstrap import bootstrap
from app.cli import register_cli
from app.core.config import Settings
from app.routes import register_http_layer


def create_app(
    environment: str | None = None,
    config_overrides: Mapping[str, Any] | None = None,
) -> Flask:
    """Create an isolated Flask application for the selected environment."""

    settings = Settings.from_env(environment)
    app = Flask(__name__)
    app.config.from_mapping(settings.as_flask_config())
    if config_overrides:
        app.config.from_mapping(config_overrides)

    logging.basicConfig(level=app.config["LOG_LEVEL"])

    app.extensions["container"] = bootstrap(settings)
    register_http_layer(app)
    register_cli(app)
    return app


__all__ = ["create_app"]
