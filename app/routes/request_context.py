"""Request-scoped metadata shared by responses and logs."""

from __future__ import annotations

from uuid import uuid4

from flask import Flask, g


def register_request_context(app: Flask) -> None:
    @app.before_request
    def assign_request_id() -> None:
        g.request_id = str(uuid4())

    @app.after_request
    def attach_request_id(response):  # type: ignore[no-untyped-def]
        response.headers["X-Request-ID"] = g.request_id
        return response
