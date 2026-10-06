"""Product catalogue, cart, inquiry, and product-checkout endpoints."""

from __future__ import annotations

from html import escape
from uuid import UUID

from flask import Response, current_app, redirect, request
from flask_jwt_extended import get_jwt_identity, jwt_required
from marshmallow import Schema, fields, validate

from app.domain.errors import NotFoundError
from app.routes.authz import roles_required
from app.routes.change_control import stage_change
from app.routes.v1 import api_v1
from app.services.catalog import catalog_service_from_container


class ProductQuerySchema(Schema):
    locale = fields.String(load_default="en", validate=validate.OneOf(["en", "fa"]))
    category = fields.String(load_default=None, allow_none=True)
    page = fields.Integer(load_default=1, validate=validate.Range(min=1))
    page_size = fields.Integer(load_default=20, validate=validate.Range(min=1, max=100))


class CategoryTranslationSchema(Schema):
    locale = fields.String(required=True, validate=validate.OneOf(["en", "fa"]))
    title = fields.String(required=True, validate=validate.Length(min=1, max=160))


class CategoryMutationSchema(Schema):
    # Accepted temporarily for older clients, but ignored: the server owns slugs.
    slug = fields.String(load_default=None, allow_none=True, load_only=True)
    position = fields.Integer(load_default=0, validate=validate.Range(min=0))
    translations = fields.List(
        fields.Nested(CategoryTranslationSchema),
        required=True,
        validate=validate.Length(equal=2),
    )


class ProductTranslationSchema(Schema):
    details = fields.Dict(load_default=dict)
    locale = fields.String(required=True, validate=validate.OneOf(["en", "fa"]))
    name = fields.String(required=True, validate=validate.Length(min=1, max=240))
    short_description = fields.String(required=True, validate=validate.Length(min=1, max=500))
    description = fields.String(load_default="", validate=validate.Length(max=20_000))


class ProductPriceSchema(Schema):
    currency = fields.String(required=True, validate=validate.OneOf(["IRR", "USD"]))
    amount_minor = fields.Integer(required=True, validate=validate.Range(min=0))


class ProductMediaSchema(Schema):
    stored_file_id = fields.UUID(load_default=None, allow_none=True)
    external_url = fields.Url(load_default=None, allow_none=True)
    alt_text = fields.String(load_default="", validate=validate.Length(max=255))
    position = fields.Integer(required=True, validate=validate.Range(min=0))


class ProductMutationSchema(Schema):
    # Accepted temporarily for older clients, but ignored: the server owns slugs.
    slug = fields.String(load_default=None, allow_none=True, load_only=True)
    sku = fields.String(required=True, validate=validate.Length(min=1, max=80))
    category_slug = fields.String(required=True, validate=validate.Length(min=1, max=120))
    sale_mode = fields.String(required=True, validate=validate.OneOf(["direct", "inquiry"]))
    stock_quantity = fields.Integer(
        load_default=None, allow_none=True, validate=validate.Range(min=0)
    )
    translations = fields.List(
        fields.Nested(ProductTranslationSchema), required=True, validate=validate.Length(equal=2)
    )
    prices = fields.List(
        fields.Nested(ProductPriceSchema), load_default=list, validate=validate.Length(max=2)
    )
    media = fields.List(fields.Nested(ProductMediaSchema), load_default=list)


class ProductUpdateSchema(Schema):
    sku = fields.String(validate=validate.Length(min=1, max=80))
    category_slug = fields.String(validate=validate.Length(min=1, max=120))
    sale_mode = fields.String(validate=validate.OneOf(["direct", "inquiry"]))
    stock_quantity = fields.Integer(allow_none=True, validate=validate.Range(min=0))
    translations = fields.List(
        fields.Nested(ProductTranslationSchema), validate=validate.Length(equal=2)
    )
    prices = fields.List(fields.Nested(ProductPriceSchema), validate=validate.Length(max=2))
    media = fields.List(fields.Nested(ProductMediaSchema))


class CartQuerySchema(Schema):
    locale = fields.String(load_default="en", validate=validate.OneOf(["en", "fa"]))


class CartItemSchema(Schema):
    quantity = fields.Integer(required=True, validate=validate.Range(min=1, max=99))


class InquirySchema(Schema):
    name = fields.String(required=True, validate=validate.Length(min=2, max=160))
    email = fields.Email(required=True)
    phone = fields.String(load_default=None, allow_none=True, validate=validate.Length(max=32))
    quantity = fields.Integer(load_default=1, validate=validate.Range(min=1, max=100_000))
    message = fields.String(required=True, validate=validate.Length(min=2, max=4000))


class InquiryQuerySchema(Schema):
    status = fields.String(
        load_default=None,
        allow_none=True,
        validate=validate.OneOf(["pending", "answered", "closed", "rejected"]),
    )


class InquiryResponseSchema(Schema):
    status = fields.String(
        required=True, validate=validate.OneOf(["answered", "closed", "rejected"])
    )
    response = fields.String(load_default=None, allow_none=True, validate=validate.Length(max=4000))


class ProductOrderSchema(Schema):
    currency = fields.String(required=True, validate=validate.OneOf(["IRR", "USD"]))
    shipping_address = fields.Dict(required=True, validate=validate.Length(min=1))


class FakePaymentSchema(Schema):
    result = fields.String(
        required=True, validate=validate.OneOf(["success", "cancel", "failure"])
    )


def _service():  # type: ignore[no-untyped-def]
    return catalog_service_from_container(current_app.extensions["container"])


CONTENT_ROLES = ("content_manager", "admin", "super_admin")


@api_v1.get("/product-categories")
@api_v1.arguments(ProductQuerySchema(only=("locale",)), location="query")
def product_categories(query: dict):  # type: ignore[no-untyped-def]
    return {"data": _service().categories(query["locale"])}


@api_v1.get("/products")
@api_v1.arguments(ProductQuerySchema, location="query")
def products(query: dict):  # type: ignore[no-untyped-def]
    rows, total = _service().products(**query)
    return {
        "data": rows,
        "meta": {"page": query["page"], "page_size": query["page_size"], "total": total},
    }


@api_v1.get("/products/<string:slug>")
@api_v1.arguments(ProductQuerySchema(only=("locale",)), location="query")
def product_detail(query: dict, slug: str):  # type: ignore[no-untyped-def]
    return {"data": _service().product(slug, query["locale"])}


@api_v1.get("/admin/products")
@roles_required(*CONTENT_ROLES)
def admin_products():  # type: ignore[no-untyped-def]
    return {"data": _service().admin_products()}


@api_v1.post("/admin/product-categories")
@roles_required(*CONTENT_ROLES)
@api_v1.arguments(CategoryMutationSchema)
def create_product_category(data: dict):  # type: ignore[no-untyped-def]
    english = next(item for item in data["translations"] if item["locale"] == "en")
    staged = stage_change(
        "product_category", f"new:{english['title'].strip().lower()}", "create", data
    )
    if staged:
        return staged
    return {"data": _service().create_category(data)}, 201


@api_v1.get("/admin/product-categories")
@roles_required(*CONTENT_ROLES)
def admin_product_categories():  # type: ignore[no-untyped-def]
    return {"data": _service().admin_categories()}


@api_v1.delete("/admin/product-categories/<uuid:category_id>")
@roles_required(*CONTENT_ROLES)
def archive_product_category(category_id: UUID):  # type: ignore[no-untyped-def]
    staged = stage_change(
        "product_category", str(category_id), "archive", resource_id=category_id
    )
    if staged:
        return staged
    _service().archive_category(category_id)
    return "", 204


@api_v1.post("/admin/products")
@roles_required(*CONTENT_ROLES)
@api_v1.arguments(ProductMutationSchema)
def create_product(data: dict):  # type: ignore[no-untyped-def]
    staged = stage_change("product", f"new:{data['sku']}", "create", data)
    if staged:
        return staged
    return {"data": _service().create_product(data)}, 201


@api_v1.patch("/admin/products/<uuid:product_id>")
@roles_required(*CONTENT_ROLES)
@api_v1.arguments(ProductUpdateSchema)
def update_product(data: dict, product_id: UUID):  # type: ignore[no-untyped-def]
    staged = stage_change("product", str(product_id), "update", data, resource_id=product_id)
    if staged:
        return staged
    return {"data": _service().update_product(product_id, data)}


@api_v1.post("/admin/products/<uuid:product_id>/publish")
@roles_required(*CONTENT_ROLES)
def publish_product(product_id: UUID):  # type: ignore[no-untyped-def]
    staged = stage_change("product", str(product_id), "publish", resource_id=product_id)
    if staged:
        return staged
    return {"data": _service().publish_product(product_id, True)}


@api_v1.post("/admin/products/<uuid:product_id>/unpublish")
@roles_required(*CONTENT_ROLES)
def unpublish_product(product_id: UUID):  # type: ignore[no-untyped-def]
    staged = stage_change("product", str(product_id), "unpublish", resource_id=product_id)
    if staged:
        return staged
    return {"data": _service().publish_product(product_id, False)}


@api_v1.delete("/admin/products/<uuid:product_id>")
@roles_required(*CONTENT_ROLES)
def archive_product(product_id: UUID):  # type: ignore[no-untyped-def]
    staged = stage_change("product", str(product_id), "archive", resource_id=product_id)
    if staged:
        return staged
    _service().archive_product(product_id)
    return "", 204


@api_v1.get("/cart")
@jwt_required()
@api_v1.arguments(CartQuerySchema, location="query")
def cart(query: dict):  # type: ignore[no-untyped-def]
    return {"data": _service().cart(UUID(get_jwt_identity()), query["locale"])}


@api_v1.put("/cart/items/<uuid:product_id>")
@jwt_required()
@api_v1.arguments(CartItemSchema)
def set_cart_item(data: dict, product_id: UUID):  # type: ignore[no-untyped-def]
    return {
        "data": _service().set_cart_item(UUID(get_jwt_identity()), product_id, data["quantity"])
    }


@api_v1.delete("/cart/items/<uuid:product_id>")
@jwt_required()
def remove_cart_item(product_id: UUID):  # type: ignore[no-untyped-def]
    _service().remove_cart_item(UUID(get_jwt_identity()), product_id)
    return "", 204


@api_v1.post("/products/<string:slug>/inquiries")
@jwt_required(optional=True)
@api_v1.arguments(InquirySchema)
def create_product_inquiry(data: dict, slug: str):  # type: ignore[no-untyped-def]
    identity = get_jwt_identity()
    return {
        "data": _service().create_inquiry(
            slug, data, UUID(identity) if identity is not None else None
        )
    }, 201


@api_v1.get("/admin/product-inquiries")
@roles_required(*CONTENT_ROLES)
@api_v1.arguments(InquiryQuerySchema, location="query")
def product_inquiries(query: dict):  # type: ignore[no-untyped-def]
    return {"data": _service().inquiries(query["status"])}


@api_v1.patch("/admin/product-inquiries/<uuid:inquiry_id>")
@roles_required(*CONTENT_ROLES)
@api_v1.arguments(InquiryResponseSchema)
def respond_product_inquiry(data: dict, inquiry_id: UUID):  # type: ignore[no-untyped-def]
    return {
        "data": _service().respond_inquiry(
            inquiry_id,
            UUID(get_jwt_identity()),
            data["status"],
            data["response"],
        )
    }


@api_v1.post("/product-orders")
@jwt_required()
@api_v1.arguments(ProductOrderSchema)
def create_product_order(data: dict):  # type: ignore[no-untyped-def]
    return {
        "data": _service().create_product_order(
            UUID(get_jwt_identity()), data["currency"], data["shipping_address"]
        )
    }, 201


@api_v1.get("/product-orders/<uuid:order_id>")
@jwt_required()
def product_order(order_id: UUID):  # type: ignore[no-untyped-def]
    return {"data": _service().product_order(UUID(get_jwt_identity()), order_id)}


@api_v1.get("/product-payments/fake/<uuid:attempt_id>")
def fake_product_gateway(attempt_id: UUID):  # type: ignore[no-untyped-def]
    if current_app.config["ENVIRONMENT"] == "production":
        raise NotFoundError("Payment page does not exist.")
    result = request.args.get("result")
    if result:
        payment = _service().product_payment(attempt_id, result)
        return redirect(
            f"{current_app.config['FRONTEND_URL']}/#/checkout"
            f"?product_order={payment['order_id']}"
        )
    action = escape(request.path)
    return Response(
        "<!doctype html><meta charset=utf-8><title>Fake Product Payment</title>"
        "<main style='font-family:sans-serif;max-width:32rem;margin:4rem auto'>"
        "<h1>NeuroTech Fake Product Gateway</h1><p>Development only.</p>"
        f"<a href='{action}?result=success'>Approve payment</a> &nbsp; "
        f"<a href='{action}?result=cancel'>Cancel payment</a> &nbsp; "
        f"<a href='{action}?result=failure'>Fail payment</a></main>",
        mimetype="text/html",
    )


@api_v1.post("/product-payments/fake/<uuid:attempt_id>/callback")
@api_v1.arguments(FakePaymentSchema)
def fake_product_callback(data: dict, attempt_id: UUID):  # type: ignore[no-untyped-def]
    if current_app.config["ENVIRONMENT"] == "production":
        raise NotFoundError("Payment callback does not exist.")
    return {"data": _service().product_payment(attempt_id, data["result"])}
