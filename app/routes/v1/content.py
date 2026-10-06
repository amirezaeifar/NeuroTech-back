"""Partner directory and global-trade content endpoints."""

from __future__ import annotations

from uuid import UUID

from flask import current_app
from marshmallow import Schema, fields, validate

from app.routes.authz import roles_required
from app.routes.change_control import stage_change
from app.routes.v1 import api_v1
from app.services.content import content_service_from_container


class LocaleQuerySchema(Schema):
    locale = fields.String(load_default="en", validate=validate.OneOf(["en", "fa"]))


class PartnerTranslationSchema(Schema):
    locale = fields.String(required=True, validate=validate.OneOf(["en", "fa"]))
    name = fields.String(required=True, validate=validate.Length(min=1, max=240))
    title = fields.String(required=True, validate=validate.Length(min=1, max=240))
    qualification = fields.String(load_default="", validate=validate.Length(max=300))
    location = fields.String(load_default="", validate=validate.Length(max=240))
    affiliation = fields.String(load_default="", validate=validate.Length(max=300))
    bio = fields.String(required=True, validate=validate.Length(min=1, max=20_000))
    details = fields.Dict(load_default=dict)


class PartnerMutationSchema(Schema):
    slug = fields.String(validate=validate.Length(min=1, max=160))
    user_id = fields.UUID(load_default=None, allow_none=True)
    position = fields.Integer(load_default=0, validate=validate.Range(min=0))
    image_file_id = fields.UUID(load_default=None, allow_none=True)
    translations = fields.List(
        fields.Nested(PartnerTranslationSchema), required=True, validate=validate.Length(equal=2)
    )


class PartnerUpdateSchema(Schema):
    user_id = fields.UUID(allow_none=True)
    position = fields.Integer(validate=validate.Range(min=0))
    image_file_id = fields.UUID(allow_none=True)
    translations = fields.List(
        fields.Nested(PartnerTranslationSchema), validate=validate.Length(equal=2)
    )


class TradeTranslationSchema(Schema):
    locale = fields.String(required=True, validate=validate.OneOf(["en", "fa"]))
    title = fields.String(required=True, validate=validate.Length(min=1, max=300))
    doc_type = fields.String(required=True, validate=validate.Length(min=1, max=240))
    partner_name = fields.String(required=True, validate=validate.Length(min=1, max=240))
    category = fields.String(required=True, validate=validate.Length(min=1, max=240))
    location = fields.String(load_default=None, allow_none=True, validate=validate.Length(max=240))
    region = fields.String(load_default=None, allow_none=True, validate=validate.Length(max=240))
    summary = fields.String(load_default="", validate=validate.Length(max=10_000))
    groups = fields.List(fields.Dict(), load_default=list, validate=validate.Length(max=100))


class TradeMutationSchema(Schema):
    slug = fields.String(required=True, validate=validate.Length(min=1, max=190))
    document_code = fields.String(required=True, validate=validate.Length(min=1, max=100))
    position = fields.Integer(load_default=0, validate=validate.Range(min=0))
    attachment_file_id = fields.UUID(load_default=None, allow_none=True)
    translations = fields.List(
        fields.Nested(TradeTranslationSchema), required=True, validate=validate.Length(equal=2)
    )


class TradeUpdateSchema(Schema):
    document_code = fields.String(validate=validate.Length(min=1, max=100))
    position = fields.Integer(validate=validate.Range(min=0))
    attachment_file_id = fields.UUID(allow_none=True)
    translations = fields.List(
        fields.Nested(TradeTranslationSchema), validate=validate.Length(equal=2)
    )


class PageTranslationSchema(Schema):
    locale = fields.String(required=True, validate=validate.OneOf(["en", "fa"]))
    content = fields.Dict(required=True)


class PageContentSchema(Schema):
    translations = fields.List(
        fields.Nested(PageTranslationSchema), required=True, validate=validate.Length(equal=2)
    )


def _service():  # type: ignore[no-untyped-def]
    return content_service_from_container(current_app.extensions["container"])


CONTENT_ROLES = ("content_manager", "admin", "super_admin")


@api_v1.get("/partners")
@api_v1.arguments(LocaleQuerySchema, location="query")
def partners(query: dict):  # type: ignore[no-untyped-def]
    return {"data": _service().partners(query["locale"])}


@api_v1.get("/partners/<string:slug>")
@api_v1.arguments(LocaleQuerySchema, location="query")
def partner(query: dict, slug: str):  # type: ignore[no-untyped-def]
    return {"data": _service().partner(slug, query["locale"])}


@api_v1.get("/admin/partners")
@roles_required(*CONTENT_ROLES)
def admin_partners():  # type: ignore[no-untyped-def]
    return {"data": _service().partners("en", admin=True)}


@api_v1.post("/admin/partners")
@roles_required(*CONTENT_ROLES)
@api_v1.arguments(PartnerMutationSchema)
def create_partner(data: dict):  # type: ignore[no-untyped-def]
    name = next(item["name"] for item in data["translations"] if item["locale"] == "en")
    staged = stage_change("partner", f"new:{name.strip().lower()}", "create", data)
    if staged:
        return staged
    return {"data": _service().create_partner(data)}, 201


@api_v1.patch("/admin/partners/<uuid:partner_id>")
@roles_required(*CONTENT_ROLES)
@api_v1.arguments(PartnerUpdateSchema)
def update_partner(data: dict, partner_id: UUID):  # type: ignore[no-untyped-def]
    staged = stage_change("partner", str(partner_id), "update", data, resource_id=partner_id)
    if staged:
        return staged
    return {"data": _service().update_partner(partner_id, data)}


@api_v1.post("/admin/partners/<uuid:partner_id>/publish")
@roles_required(*CONTENT_ROLES)
def publish_partner(partner_id: UUID):  # type: ignore[no-untyped-def]
    staged = stage_change("partner", str(partner_id), "publish", resource_id=partner_id)
    if staged:
        return staged
    return {"data": _service().publish_partner(partner_id, True)}


@api_v1.post("/admin/partners/<uuid:partner_id>/unpublish")
@roles_required(*CONTENT_ROLES)
def unpublish_partner(partner_id: UUID):  # type: ignore[no-untyped-def]
    staged = stage_change("partner", str(partner_id), "unpublish", resource_id=partner_id)
    if staged:
        return staged
    return {"data": _service().publish_partner(partner_id, False)}


@api_v1.delete("/admin/partners/<uuid:partner_id>")
@roles_required(*CONTENT_ROLES)
def archive_partner(partner_id: UUID):  # type: ignore[no-untyped-def]
    staged = stage_change("partner", str(partner_id), "archive", resource_id=partner_id)
    if staged:
        return staged
    _service().archive_partner(partner_id)
    return "", 204


@api_v1.get("/trade-documents")
@api_v1.arguments(LocaleQuerySchema, location="query")
def trade_documents(query: dict):  # type: ignore[no-untyped-def]
    return {"data": _service().trade_documents(query["locale"])}


@api_v1.get("/trade-documents/<string:slug>")
@api_v1.arguments(LocaleQuerySchema, location="query")
def trade_document(query: dict, slug: str):  # type: ignore[no-untyped-def]
    return {"data": _service().trade_document(slug, query["locale"])}


@api_v1.get("/admin/trade-documents")
@roles_required(*CONTENT_ROLES)
def admin_trade_documents():  # type: ignore[no-untyped-def]
    return {"data": _service().trade_documents("en", admin=True)}


@api_v1.post("/admin/trade-documents")
@roles_required(*CONTENT_ROLES)
@api_v1.arguments(TradeMutationSchema)
def create_trade_document(data: dict):  # type: ignore[no-untyped-def]
    return {"data": _service().create_trade_document(data)}, 201


@api_v1.patch("/admin/trade-documents/<uuid:document_id>")
@roles_required(*CONTENT_ROLES)
@api_v1.arguments(TradeUpdateSchema)
def update_trade_document(data: dict, document_id: UUID):  # type: ignore[no-untyped-def]
    return {"data": _service().update_trade_document(document_id, data)}


@api_v1.post("/admin/trade-documents/<uuid:document_id>/publish")
@roles_required(*CONTENT_ROLES)
def publish_trade_document(document_id: UUID):  # type: ignore[no-untyped-def]
    return {"data": _service().publish_trade_document(document_id, True)}


@api_v1.post("/admin/trade-documents/<uuid:document_id>/unpublish")
@roles_required(*CONTENT_ROLES)
def unpublish_trade_document(document_id: UUID):  # type: ignore[no-untyped-def]
    return {"data": _service().publish_trade_document(document_id, False)}


@api_v1.delete("/admin/trade-documents/<uuid:document_id>")
@roles_required(*CONTENT_ROLES)
def archive_trade_document(document_id: UUID):  # type: ignore[no-untyped-def]
    _service().archive_trade_document(document_id)
    return "", 204


@api_v1.get("/page-content/<string:page_key>")
@api_v1.arguments(LocaleQuerySchema, location="query")
def page_content(query: dict, page_key: str):  # type: ignore[no-untyped-def]
    return {"data": _service().page_content(page_key, query["locale"])}


@api_v1.get("/admin/page-content")
@roles_required(*CONTENT_ROLES)
def admin_page_content():  # type: ignore[no-untyped-def]
    return {"data": _service().managed_pages()}


@api_v1.put("/admin/page-content/<string:page_key>")
@roles_required(*CONTENT_ROLES)
@api_v1.arguments(PageContentSchema)
def save_page_content(data: dict, page_key: str):  # type: ignore[no-untyped-def]
    return {"data": _service().save_page_content(page_key, data["translations"])}


@api_v1.post("/admin/page-content/<string:page_key>/publish")
@roles_required(*CONTENT_ROLES)
def publish_page_content(page_key: str):  # type: ignore[no-untyped-def]
    return {"data": _service().publish_page_content(page_key, True)}


@api_v1.post("/admin/page-content/<string:page_key>/unpublish")
@roles_required(*CONTENT_ROLES)
def unpublish_page_content(page_key: str):  # type: ignore[no-untyped-def]
    return {"data": _service().publish_page_content(page_key, False)}
