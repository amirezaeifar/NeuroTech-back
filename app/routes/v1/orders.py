"""Administrative order tracking endpoints."""

from __future__ import annotations

from uuid import UUID

from flask import current_app
from marshmallow import Schema, fields, validate

from app.routes.authz import roles_required
from app.routes.v1 import api_v1
from app.services.orders import admin_order_service_from_container


class OrderQuerySchema(Schema):
    kind = fields.String(load_default=None, validate=validate.OneOf(["course", "product"]))
    payment_status = fields.String(
        load_default=None,
        validate=validate.OneOf(["pending", "paid", "cancelled", "failed"]),
    )
    fulfillment_status = fields.String(load_default=None)


class FulfillmentUpdateSchema(Schema):
    status = fields.String(
        required=True,
        validate=validate.OneOf(
            ["awaiting_confirmation", "confirmed", "shipped", "closed"]
        ),
    )


def _service():  # type: ignore[no-untyped-def]
    return admin_order_service_from_container(current_app.extensions["container"])


@api_v1.get("/admin/orders")
@roles_required("admin", "super_admin")
@api_v1.arguments(OrderQuerySchema, location="query")
def admin_orders(query: dict):  # type: ignore[no-untyped-def]
    result = _service().list_orders(**query)
    return {
        "data": result["items"],
        "meta": {
            "total": result["total"],
            "payment_counts": result["payment_counts"],
        },
    }


@api_v1.patch("/admin/orders/products/<uuid:order_id>/fulfillment")
@roles_required("admin", "super_admin")
@api_v1.arguments(FulfillmentUpdateSchema)
def advance_product_order(data: dict, order_id: UUID):  # type: ignore[no-untyped-def]
    return {"data": _service().advance_product(order_id, data["status"])}
