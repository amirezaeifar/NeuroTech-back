"""Academy enrollment, progress, and discussion endpoints."""

from __future__ import annotations

from uuid import UUID

from flask import current_app
from flask_jwt_extended import get_jwt, get_jwt_identity, jwt_required
from marshmallow import Schema, fields, validate

from app.routes.authz import roles_required
from app.routes.v1 import api_v1
from app.services.learning import learning_service_from_container


class ProgressSchema(Schema):
    position_seconds = fields.Integer(required=True, validate=validate.Range(min=0))
    completed = fields.Boolean(load_default=False)


class CommentSchema(Schema):
    body = fields.String(required=True, validate=validate.Length(min=2, max=4000))
    lesson_id = fields.UUID(load_default=None, allow_none=True)


class ModerationSchema(Schema):
    decision = fields.String(
        required=True,
        validate=validate.OneOf(["approved", "rejected", "hidden", "needs_reply"]),
    )
    reason = fields.String(load_default=None, allow_none=True, validate=validate.Length(max=500))


class PathwayQuerySchema(Schema):
    locale = fields.String(load_default="en", validate=validate.OneOf(["en", "fa"]))


class AdminCommentQuerySchema(Schema):
    page = fields.Integer(load_default=1, validate=validate.Range(min=1))
    page_size = fields.Integer(load_default=20, validate=validate.Range(min=1, max=100))
    course = fields.String(load_default=None, allow_none=True, validate=validate.Length(max=160))
    status = fields.String(
        load_default="attention",
        validate=validate.OneOf(
            ["attention", "pending", "approved", "rejected", "needs_reply", "hidden", "all"]
        ),
    )
    date_from = fields.Date(load_default=None, allow_none=True)
    date_to = fields.Date(load_default=None, allow_none=True)


class CommentReplySchema(Schema):
    body = fields.String(required=True, validate=validate.Length(min=2, max=4000))


def _service():  # type: ignore[no-untyped-def]
    return learning_service_from_container(current_app.extensions["container"])


def _specialist_id() -> UUID | None:
    return UUID(get_jwt_identity()) if get_jwt().get("role") == "specialist" else None


@api_v1.post("/courses/<string:slug>/enroll")
@jwt_required()
def enroll_free(slug: str):  # type: ignore[no-untyped-def]
    return {"data": _service().enroll_free(UUID(get_jwt_identity()), slug)}, 201


@api_v1.get("/courses/<string:slug>/access")
@jwt_required()
@api_v1.arguments(PathwayQuerySchema, location="query")
def course_access(query: dict, slug: str):  # type: ignore[no-untyped-def]
    return {"data": _service().access(UUID(get_jwt_identity()), slug, query["locale"])}


@api_v1.get("/me/pathway")
@jwt_required()
@api_v1.arguments(PathwayQuerySchema, location="query")
def pathway(query: dict):  # type: ignore[no-untyped-def]
    return {"data": _service().pathway(UUID(get_jwt_identity()), query["locale"])}


@api_v1.put("/me/lessons/<uuid:lesson_id>/progress")
@jwt_required()
@api_v1.arguments(ProgressSchema)
def save_progress(data: dict, lesson_id: UUID):  # type: ignore[no-untyped-def]
    return {"data": _service().save_progress(UUID(get_jwt_identity()), lesson_id, **data)}


@api_v1.get("/courses/<string:slug>/comments")
def list_comments(slug: str):  # type: ignore[no-untyped-def]
    return {"data": _service().comments(slug)}


@api_v1.post("/courses/<string:slug>/comments")
@jwt_required()
@api_v1.arguments(CommentSchema)
def add_comment(data: dict, slug: str):  # type: ignore[no-untyped-def]
    return {
        "data": _service().add_comment(
            UUID(get_jwt_identity()), slug, data["body"], data["lesson_id"]
        )
    }, 201


@api_v1.post("/admin/comments/<uuid:comment_id>/moderate")
@roles_required("specialist", "super_admin")
@api_v1.arguments(ModerationSchema)
def moderate_comment(data: dict, comment_id: UUID):  # type: ignore[no-untyped-def]
    return {
        "data": _service().moderate(
            UUID(get_jwt_identity()), comment_id, data["decision"], data["reason"], _specialist_id()
        )
    }


@api_v1.get("/admin/comments/pending")
@roles_required("specialist", "super_admin")
def pending_comments():  # type: ignore[no-untyped-def]
    return {"data": _service().admin_comments(status="pending", specialist_id=_specialist_id())["data"]}


@api_v1.get("/admin/comments/courses")
@roles_required("specialist", "super_admin")
def moderation_courses():
    return {"data": _service().moderation_courses(_specialist_id())}


@api_v1.get("/admin/comments")
@roles_required("specialist", "super_admin")
@api_v1.arguments(AdminCommentQuerySchema, location="query")
def admin_comments(query: dict):  # type: ignore[no-untyped-def]
    return _service().admin_comments(**query, specialist_id=_specialist_id())


@api_v1.get("/admin/comments/summary")
@roles_required("specialist", "super_admin")
def comment_summary():  # type: ignore[no-untyped-def]
    return {"data": _service().comment_summary(_specialist_id())}


@api_v1.post("/admin/comments/<uuid:comment_id>/reply")
@roles_required("specialist", "super_admin")
@api_v1.arguments(CommentReplySchema)
def reply_comment(data: dict, comment_id: UUID):  # type: ignore[no-untyped-def]
    return {
        "data": _service().reply_comment(
            UUID(get_jwt_identity()), comment_id, data["body"], _specialist_id()
        )
    }, 201


@api_v1.delete("/admin/comments/<uuid:comment_id>")
@roles_required("specialist", "super_admin")
def delete_comment(comment_id: UUID):  # type: ignore[no-untyped-def]
    _service().delete_comment(comment_id, _specialist_id())
    return "", 204
