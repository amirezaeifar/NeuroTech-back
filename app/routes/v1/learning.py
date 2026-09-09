"""Academy enrollment, progress, and discussion endpoints."""

from __future__ import annotations

from uuid import UUID

from flask import current_app
from flask_jwt_extended import get_jwt_identity, jwt_required
from marshmallow import Schema, fields, validate

from app.routes.authz import roles_required
from app.routes.v1 import api_v1
from app.services.learning import learning_service_from_container


class ProgressSchema(Schema):
    position_seconds = fields.Integer(required=True, validate=validate.Range(min=0))
    completed = fields.Boolean(load_default=False)


class CommentSchema(Schema):
    body = fields.String(required=True, validate=validate.Length(min=2, max=4000))


class ModerationSchema(Schema):
    decision = fields.String(required=True, validate=validate.OneOf(["approved", "rejected"]))
    reason = fields.String(load_default=None, allow_none=True, validate=validate.Length(max=500))


class PathwayQuerySchema(Schema):
    locale = fields.String(load_default="en", validate=validate.OneOf(["en", "fa"]))


def _service():  # type: ignore[no-untyped-def]
    return learning_service_from_container(current_app.extensions["container"])


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
    return {"data": _service().add_comment(UUID(get_jwt_identity()), slug, data["body"])}, 201


@api_v1.post("/admin/comments/<uuid:comment_id>/moderate")
@roles_required("admin", "specialist")
@api_v1.arguments(ModerationSchema)
def moderate_comment(data: dict, comment_id: UUID):  # type: ignore[no-untyped-def]
    return {
        "data": _service().moderate(
            UUID(get_jwt_identity()), comment_id, data["decision"], data["reason"]
        )
    }


@api_v1.get("/admin/comments/pending")
@roles_required("admin", "specialist")
def pending_comments():  # type: ignore[no-untyped-def]
    return {"data": _service().pending_comments()}
