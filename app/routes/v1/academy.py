"""Public and administrative Academy endpoints."""

from __future__ import annotations

from uuid import UUID

from flask import current_app
from marshmallow import Schema, fields, validate

from app.domain.errors import NotFoundError
from app.routes.authz import roles_required
from app.routes.v1 import api_v1
from app.services.academy import academy_service_from_container


class CourseQuerySchema(Schema):
    locale = fields.String(load_default="en", validate=validate.OneOf(["en", "fa"]))
    page = fields.Integer(load_default=1, validate=validate.Range(min=1))
    page_size = fields.Integer(load_default=20, validate=validate.Range(min=1, max=100))
    tier = fields.String(load_default=None, allow_none=True)
    field = fields.String(load_default=None, allow_none=True)


class TranslationSchema(Schema):
    locale = fields.String(required=True, validate=validate.OneOf(["en", "fa"]))
    title = fields.String(required=True, validate=validate.Length(min=1, max=240))
    description = fields.String(required=True, validate=validate.Length(min=1, max=20_000))
    instructor_name = fields.String(required=True, validate=validate.Length(min=1, max=160))
    duration_label = fields.String(required=True, validate=validate.Length(min=1, max=80))


class PriceSchema(Schema):
    currency = fields.String(required=True, validate=validate.OneOf(["IRR", "USD"]))
    amount_minor = fields.Integer(required=True, validate=validate.Range(min=0))


class CourseMutationSchema(Schema):
    slug = fields.String(required=True, validate=validate.Length(min=1, max=160))
    tier = fields.String(required=True, validate=validate.OneOf(["free", "premium"]))
    field = fields.String(required=True, validate=validate.Length(min=1, max=60))
    level = fields.String(required=True, validate=validate.Length(min=1, max=30))
    translations = fields.List(
        fields.Nested(TranslationSchema), required=True, validate=validate.Length(min=1, max=2)
    )
    prices = fields.List(
        fields.Nested(PriceSchema), load_default=list, validate=validate.Length(max=2)
    )


class CourseUpdateSchema(Schema):
    tier = fields.String(validate=validate.OneOf(["free", "premium"]))
    field = fields.String(validate=validate.Length(min=1, max=60))
    level = fields.String(validate=validate.Length(min=1, max=30))
    translations = fields.List(
        fields.Nested(TranslationSchema), validate=validate.Length(min=1, max=2)
    )
    prices = fields.List(fields.Nested(PriceSchema), validate=validate.Length(max=2))


class LocalizedTitleSchema(Schema):
    locale = fields.String(required=True, validate=validate.OneOf(["en", "fa"]))
    title = fields.String(required=True, validate=validate.Length(min=1, max=240))


class LessonContentSchema(Schema):
    position = fields.Integer(required=True, validate=validate.Range(min=1))
    duration_seconds = fields.Integer(required=True, validate=validate.Range(min=0))
    video_provider = fields.String(required=True, validate=validate.OneOf(["youtube"]))
    video_reference = fields.String(required=True, validate=validate.Length(min=1, max=255))
    free_preview = fields.Boolean(load_default=False)
    translations = fields.List(
        fields.Nested(LocalizedTitleSchema),
        required=True,
        validate=validate.Length(equal=2),
    )


class SectionContentSchema(Schema):
    position = fields.Integer(required=True, validate=validate.Range(min=1))
    translations = fields.List(
        fields.Nested(LocalizedTitleSchema),
        required=True,
        validate=validate.Length(equal=2),
    )
    lessons = fields.List(fields.Nested(LessonContentSchema), load_default=list)


class OutcomeContentSchema(Schema):
    locale = fields.String(required=True, validate=validate.OneOf(["en", "fa"]))
    position = fields.Integer(required=True, validate=validate.Range(min=1))
    text = fields.String(required=True, validate=validate.Length(min=1, max=500))


class ResourceContentSchema(Schema):
    name = fields.String(required=True, validate=validate.Length(min=1, max=240))
    kind = fields.String(required=True, validate=validate.Length(min=1, max=30))
    storage_path = fields.String(
        load_default=None, allow_none=True, validate=validate.Length(max=500)
    )
    external_url = fields.Url(load_default=None, allow_none=True)


class MediaContentSchema(Schema):
    kind = fields.String(required=True, validate=validate.Length(min=1, max=30))
    position = fields.Integer(required=True, validate=validate.Range(min=1))
    locale = fields.String(
        load_default=None, allow_none=True, validate=validate.OneOf(["en", "fa"])
    )
    mime_type = fields.String(load_default=None, allow_none=True, validate=validate.Length(max=120))
    storage_path = fields.String(
        load_default=None, allow_none=True, validate=validate.Length(max=500)
    )
    external_url = fields.Url(load_default=None, allow_none=True)


class CourseContentSchema(Schema):
    sections = fields.List(fields.Nested(SectionContentSchema), load_default=list)
    outcomes = fields.List(fields.Nested(OutcomeContentSchema), load_default=list)
    resources = fields.List(fields.Nested(ResourceContentSchema), load_default=list)
    media = fields.List(fields.Nested(MediaContentSchema), load_default=list)


class CourseReorderSchema(Schema):
    course_ids = fields.List(fields.UUID(), required=True, validate=validate.Length(min=1))


def _service():  # type: ignore[no-untyped-def]
    return academy_service_from_container(current_app.extensions["container"])


@api_v1.get("/courses")
@api_v1.arguments(CourseQuerySchema, location="query")
def list_courses(query: dict):  # type: ignore[no-untyped-def]
    courses, total = _service().list_courses(**query)
    return {
        "data": courses,
        "meta": {"page": query["page"], "page_size": query["page_size"], "total": total},
    }


@api_v1.get("/courses/<string:slug>")
@api_v1.arguments(CourseQuerySchema(only=("locale",)), location="query")
def course_detail(query: dict, slug: str):  # type: ignore[no-untyped-def]
    course = _service().get_course(slug, query["locale"])
    if course is None:
        raise NotFoundError("Course does not exist.")
    return {"data": course}


@api_v1.get("/admin/courses")
@roles_required("admin", "specialist")
def list_admin_courses():  # type: ignore[no-untyped-def]
    return {"data": _service().list_admin_courses()}


@api_v1.put("/admin/courses/order")
@roles_required("admin", "specialist")
@api_v1.arguments(CourseReorderSchema)
def reorder_courses(data: dict):  # type: ignore[no-untyped-def]
    _service().reorder(data["course_ids"])
    return {"data": {"ordered": True}}


@api_v1.put("/admin/courses/<uuid:course_id>/content")
@roles_required("admin", "specialist")
@api_v1.arguments(CourseContentSchema)
def replace_course_content(data: dict, course_id: UUID):  # type: ignore[no-untyped-def]
    return {"data": _service().replace_content(course_id, data)}


@api_v1.post("/admin/courses")
@roles_required("admin", "specialist")
@api_v1.arguments(CourseMutationSchema)
def create_course(data: dict):  # type: ignore[no-untyped-def]
    return {"data": _service().create_course(data)}, 201


@api_v1.patch("/admin/courses/<uuid:course_id>")
@roles_required("admin", "specialist")
@api_v1.arguments(CourseUpdateSchema)
def update_course(data: dict, course_id: UUID):  # type: ignore[no-untyped-def]
    return {"data": _service().update_course(course_id, data)}


@api_v1.post("/admin/courses/<uuid:course_id>/publish")
@roles_required("admin", "specialist")
def publish_course(course_id: UUID):  # type: ignore[no-untyped-def]
    return {"data": _service().publish(course_id)}


@api_v1.post("/admin/courses/<uuid:course_id>/unpublish")
@roles_required("admin", "specialist")
def unpublish_course(course_id: UUID):  # type: ignore[no-untyped-def]
    return {"data": _service().unpublish(course_id)}


@api_v1.delete("/admin/courses/<uuid:course_id>")
@roles_required("admin", "specialist")
def archive_course(course_id: UUID):  # type: ignore[no-untyped-def]
    _service().archive(course_id)
    return "", 204
