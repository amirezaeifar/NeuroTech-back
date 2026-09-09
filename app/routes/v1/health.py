"""Liveness endpoint for the API process."""

from __future__ import annotations

from flask import current_app, jsonify
from marshmallow import Schema, fields

from app.routes.v1 import api_v1


class HealthSchema(Schema):
    status = fields.String(required=True)
    service = fields.String(required=True)
    version = fields.String(required=True)


class ReadinessSchema(HealthSchema):
    dependencies = fields.Dict(keys=fields.String(), values=fields.String(), required=True)


def _base_payload() -> dict[str, str]:
    return {
        "status": "healthy",
        "service": current_app.config["SERVICE_NAME"],
        "version": current_app.config["SERVICE_VERSION"],
    }


@api_v1.get("/health")
@api_v1.response(200, HealthSchema)
def health():  # type: ignore[no-untyped-def]
    return _base_payload()


@api_v1.get("/health/live")
@api_v1.response(200, HealthSchema)
def liveness():  # type: ignore[no-untyped-def]
    return _base_payload()


@api_v1.get("/health/ready")
@api_v1.response(200, ReadinessSchema)
def readiness():  # type: ignore[no-untyped-def]
    container = current_app.extensions["container"]
    dependencies: dict[str, str] = {}
    failures: list[str] = []

    for name, ping in (
        ("mariadb", container.database.ping),
        ("redis", container.redis.ping),
    ):
        try:
            ping()
            dependencies[name] = "healthy"
        except Exception:  # dependency details belong in server logs, not the response
            current_app.logger.exception("Readiness dependency failed: %s", name)
            dependencies[name] = "unhealthy"
            failures.append(name)

    payload = {**_base_payload(), "dependencies": dependencies}
    if failures:
        payload["status"] = "unhealthy"
        return jsonify(payload), 503
    return payload
