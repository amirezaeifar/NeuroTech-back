"""Order and development fake-payment endpoints."""

from __future__ import annotations

from html import escape
from uuid import UUID

from flask import Response, current_app, redirect, request
from flask_jwt_extended import get_jwt_identity, jwt_required
from marshmallow import Schema, fields, validate

from app.domain.errors import NotFoundError
from app.routes.v1 import api_v1
from app.services.commerce import commerce_service_from_container


class OrderCreateSchema(Schema):
    course_slug = fields.String(required=True, validate=validate.Length(min=1, max=160))
    currency = fields.String(required=True, validate=validate.OneOf(["IRR", "USD"]))


class FakeCallbackSchema(Schema):
    result = fields.String(required=True, validate=validate.OneOf(["success", "cancel"]))


def _service():  # type: ignore[no-untyped-def]
    return commerce_service_from_container(current_app.extensions["container"])


@api_v1.post("/orders")
@jwt_required()
@api_v1.arguments(OrderCreateSchema)
def create_order(data: dict):  # type: ignore[no-untyped-def]
    return {
        "data": _service().create_order(
            UUID(get_jwt_identity()), data["course_slug"], data["currency"]
        )
    }, 201


@api_v1.get("/orders/<uuid:order_id>")
@jwt_required()
def get_order(order_id: UUID):  # type: ignore[no-untyped-def]
    return {"data": _service().get_order(UUID(get_jwt_identity()), order_id)}


@api_v1.get("/payments/fake/<uuid:attempt_id>")
def fake_gateway(attempt_id: UUID):  # type: ignore[no-untyped-def]
    if current_app.config["ENVIRONMENT"] == "production":
        raise NotFoundError("Payment page does not exist.")
    result = request.args.get("result")
    if result:
        payment = _service().fake_payment(attempt_id, result)
        suffix = "paid=1" if payment["status"] == "paid" else "payment=cancelled"
        return redirect(
            f"{current_app.config['FRONTEND_URL']}/#/academy/course/"
            f"{payment['course_slug']}?{suffix}"
        )
    action = escape(request.path)
    return Response(
        "<!doctype html><meta charset=utf-8><title>Fake Payment</title>"
        "<main style='font-family:sans-serif;max-width:32rem;margin:4rem auto'>"
        "<h1>NeuroTech Fake Gateway</h1><p>Development only.</p>"
        f"<a href='{action}?result=success'>Approve payment</a> &nbsp; "
        f"<a href='{action}?result=cancel'>Cancel payment</a></main>",
        mimetype="text/html",
    )


@api_v1.post("/payments/fake/<uuid:attempt_id>/callback")
@api_v1.arguments(FakeCallbackSchema)
def fake_callback(data: dict, attempt_id: UUID):  # type: ignore[no-untyped-def]
    if current_app.config["ENVIRONMENT"] == "production":
        raise NotFoundError("Payment callback does not exist.")
    return {"data": _service().fake_payment(attempt_id, data["result"])}
