"""Principal approvals, blog management, and platform settings endpoints."""

from __future__ import annotations

from uuid import UUID

from flask import current_app
from flask_jwt_extended import get_jwt_identity
from marshmallow import Schema, fields, validate

from app.routes.authz import roles_required
from app.routes.change_control import stage_change
from app.routes.v1 import api_v1
from app.services.governance import governance_service_from_container

CONTENT_ROLES = ("content_manager", "admin", "super_admin")


class ApprovalQuerySchema(Schema):
    status = fields.String(
        load_default="pending", validate=validate.OneOf(["pending", "approved", "rejected"])
    )


class ApprovalDecisionSchema(Schema):
    decision = fields.String(required=True, validate=validate.OneOf(["approved", "rejected"]))
    note = fields.String(load_default="", validate=validate.Length(max=2000))


class BlogTranslationSchema(Schema):
    locale = fields.String(required=True, validate=validate.OneOf(["en", "fa"]))
    title = fields.String(required=True, validate=validate.Length(min=1, max=240))
    excerpt = fields.String(load_default="", validate=validate.Length(max=600))
    body = fields.String(required=True, validate=validate.Length(min=1, max=100_000))
    seo_title = fields.String(load_default="", validate=validate.Length(max=240))
    seo_description = fields.String(load_default="", validate=validate.Length(max=600))
    seo_keywords = fields.String(load_default="", validate=validate.Length(max=500))


class BlogMutationSchema(Schema):
    slug = fields.String(required=True, validate=validate.Length(min=1, max=180))
    cover_url = fields.String(
        load_default=None,
        allow_none=True,
        validate=validate.Regexp(r"^(https?://[^\s]+|/api/v1/files/[0-9a-fA-F-]{36})$"),
    )
    category = fields.String(load_default="blog", validate=validate.OneOf(["blog", "scientific"]))
    cover_alt = fields.String(load_default="", validate=validate.Length(max=240))
    translations = fields.List(
        fields.Nested(BlogTranslationSchema), required=True, validate=validate.Length(equal=2)
    )


class BlogUpdateSchema(Schema):
    slug = fields.String(validate=validate.Length(min=1, max=180))
    cover_url = fields.String(
        allow_none=True,
        validate=validate.Regexp(r"^(https?://[^\s]+|/api/v1/files/[0-9a-fA-F-]{36})$"),
    )
    category = fields.String(validate=validate.OneOf(["blog", "scientific"]))
    cover_alt = fields.String(validate=validate.Length(max=240))
    translations = fields.List(
        fields.Nested(BlogTranslationSchema), validate=validate.Length(equal=2)
    )


class BlogQuerySchema(Schema):
    locale = fields.String(load_default="en", validate=validate.OneOf(["en", "fa"]))
    category = fields.String(
        load_default=None, allow_none=True, validate=validate.OneOf(["blog", "scientific"])
    )


class SettingsSchema(Schema):
    site_name = fields.String(validate=validate.Length(min=1, max=120))
    support_email = fields.Email()
    maintenance = fields.Boolean()
    registrations = fields.Boolean()
    auto_approve_comments = fields.Boolean()
    premium_checkout = fields.Boolean()


def _service():  # type: ignore[no-untyped-def]
    return governance_service_from_container(current_app.extensions["container"])


@api_v1.get("/admin/approvals")
@roles_required("super_admin")
@api_v1.arguments(ApprovalQuerySchema, location="query")
def approvals(query: dict):  # type: ignore[no-untyped-def]
    return {"data": _service().approvals(query["status"])}


@api_v1.post("/admin/approvals/<uuid:request_id>/review")
@roles_required("super_admin")
@api_v1.arguments(ApprovalDecisionSchema)
def review_approval(data: dict, request_id: UUID):  # type: ignore[no-untyped-def]
    return {
        "data": _service().review(
            request_id, UUID(get_jwt_identity()), data["decision"], data["note"]
        )
    }


@api_v1.get("/blog")
@api_v1.arguments(BlogQuerySchema, location="query")
def blogs(query: dict):  # type: ignore[no-untyped-def]
    return {"data": _service().blogs(query["locale"], category=query["category"])}


@api_v1.get("/blog/<string:slug>")
@api_v1.arguments(BlogQuerySchema, location="query")
def blog_detail(query: dict, slug: str):  # type: ignore[no-untyped-def]
    return {"data": _service().blog(slug, query["locale"])}


@api_v1.get("/admin/blog")
@roles_required(*CONTENT_ROLES)
def admin_blogs():  # type: ignore[no-untyped-def]
    return {"data": _service().blogs("en", admin=True)}


@api_v1.post("/admin/blog")
@roles_required(*CONTENT_ROLES)
@api_v1.arguments(BlogMutationSchema)
def create_blog(data: dict):  # type: ignore[no-untyped-def]
    actor_id = UUID(get_jwt_identity())
    staged = stage_change(
        "blog", f"new:{data['slug']}", "create", {**data, "_author_id": str(actor_id)}
    )
    if staged:
        return staged
    return {"data": _service().create_blog(data, actor_id)}, 201


@api_v1.patch("/admin/blog/<uuid:post_id>")
@roles_required(*CONTENT_ROLES)
@api_v1.arguments(BlogUpdateSchema)
def update_blog(data: dict, post_id: UUID):  # type: ignore[no-untyped-def]
    staged = stage_change("blog", str(post_id), "update", data, resource_id=post_id)
    if staged:
        return staged
    return {"data": _service().update_blog(post_id, data)}


@api_v1.post("/admin/blog/<uuid:post_id>/publish")
@roles_required(*CONTENT_ROLES)
def publish_blog(post_id: UUID):  # type: ignore[no-untyped-def]
    staged = stage_change("blog", str(post_id), "publish", resource_id=post_id)
    if staged:
        return staged
    return {"data": _service().publish_blog(post_id, True)}


@api_v1.post("/admin/blog/<uuid:post_id>/unpublish")
@roles_required(*CONTENT_ROLES)
def unpublish_blog(post_id: UUID):  # type: ignore[no-untyped-def]
    staged = stage_change("blog", str(post_id), "unpublish", resource_id=post_id)
    if staged:
        return staged
    return {"data": _service().publish_blog(post_id, False)}


@api_v1.delete("/admin/blog/<uuid:post_id>")
@roles_required(*CONTENT_ROLES)
def archive_blog(post_id: UUID):  # type: ignore[no-untyped-def]
    staged = stage_change("blog", str(post_id), "delete", resource_id=post_id)
    if staged:
        return staged
    _service().delete_blog(post_id)
    return "", 204


@api_v1.get("/admin/settings")
@roles_required("super_admin")
def settings():  # type: ignore[no-untyped-def]
    return {"data": _service().settings()}


@api_v1.put("/admin/settings")
@roles_required("super_admin")
@api_v1.arguments(SettingsSchema)
def save_settings(data: dict):  # type: ignore[no-untyped-def]
    return {"data": _service().save_settings(data, UUID(get_jwt_identity()))}
