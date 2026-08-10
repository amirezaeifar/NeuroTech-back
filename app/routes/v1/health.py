"""Liveness endpoint for the API process."""

from __future__ import annotations

from flask import current_app, jsonify

from app.routes.v1 import api_v1


@api_v1.get("/health")
def health():  # type: ignore[no-untyped-def]
    return jsonify(
        {
            "status": "healthy",
            "service": current_app.config["SERVICE_NAME"],
            "version": current_app.config["SERVICE_VERSION"],
        }
    )
