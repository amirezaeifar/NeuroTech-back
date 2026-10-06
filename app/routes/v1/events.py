"""Public event catalogue and administrative event endpoints."""

from __future__ import annotations

from ipaddress import ip_address
from uuid import UUID

from flask import current_app, request
from flask_jwt_extended import get_jwt_identity, jwt_required
from marshmallow import Schema, fields, validate

from app.core.extensions import limiter
from app.domain.errors import ValidationError
from app.domain.event_content import EventContentSchema
from app.routes.authz import roles_required
from app.routes.change_control import stage_change
from app.routes.v1 import api_v1
from app.services.event_live import live_service_from_container
from app.services.events import event_service_from_container


class EventQuerySchema(Schema):
    locale = fields.String(load_default="en", validate=validate.OneOf(["en", "fa"]))
    kind = fields.String(
        load_default=None, allow_none=True, validate=validate.OneOf(["online", "onsite"])
    )
    status = fields.String(
        load_default=None,
        allow_none=True,
        validate=validate.OneOf(["upcoming", "live", "completed", "cancelled"]),
    )


class EventTranslationSchema(Schema):
    locale = fields.String(required=True, validate=validate.OneOf(["en", "fa"]))
    title = fields.String(required=True, validate=validate.Length(min=1, max=240))
    summary = fields.String(required=True, validate=validate.Length(min=1, max=500))
    description = fields.String(required=True, validate=validate.Length(min=1, max=20_000))
    host_label = fields.String(required=True, validate=validate.Length(min=1, max=240))
    content = fields.Nested(EventContentSchema, load_default=dict)


class EventSpeakerSchema(Schema):
    user_id = fields.UUID(allow_none=True)
    partner_id = fields.UUID(allow_none=True)
    role_label = fields.String(required=True, validate=validate.Length(min=1, max=160))
    position = fields.Integer(required=True, validate=validate.Range(min=1))


class EventMutationSchema(Schema):
    slug = fields.String(required=True, validate=validate.Length(min=1, max=160))
    kind = fields.String(required=True, validate=validate.OneOf(["online", "onsite"]))
    status = fields.String(
        required=True, validate=validate.OneOf(["upcoming", "live", "completed", "cancelled"])
    )
    starts_at = fields.DateTime(required=True)
    ends_at = fields.DateTime(required=True)
    timezone = fields.String(load_default="Asia/Tehran", validate=validate.Length(min=1, max=60))
    capacity = fields.Integer(load_default=None, allow_none=True, validate=validate.Range(min=1))
    online_url = fields.Url(load_default=None, allow_none=True)
    venue = fields.String(load_default=None, allow_none=True, validate=validate.Length(max=500))
    cover_url = fields.String(
        load_default=None,
        allow_none=True,
        validate=validate.Regexp(r"^(https?://[^\s]+|/api/v1/files/[0-9a-fA-F-]{36})$"),
    )
    agenda_steps = fields.List(
        fields.String(validate=validate.Length(min=1, max=240)),
        load_default=list,
        validate=validate.Length(max=30),
    )
    translations = fields.List(
        fields.Nested(EventTranslationSchema), required=True, validate=validate.Length(equal=2)
    )
    speakers = fields.List(fields.Nested(EventSpeakerSchema), load_default=list)


class EventUpdateSchema(Schema):
    kind = fields.String(validate=validate.OneOf(["online", "onsite"]))
    status = fields.String(validate=validate.OneOf(["upcoming", "live", "completed", "cancelled"]))
    starts_at = fields.DateTime()
    ends_at = fields.DateTime()
    timezone = fields.String(validate=validate.Length(min=1, max=60))
    capacity = fields.Integer(allow_none=True, validate=validate.Range(min=1))
    online_url = fields.Url(allow_none=True)
    venue = fields.String(allow_none=True, validate=validate.Length(max=500))
    cover_url = fields.String(
        allow_none=True,
        validate=validate.Regexp(r"^(https?://[^\s]+|/api/v1/files/[0-9a-fA-F-]{36})$"),
    )
    agenda_steps = fields.List(
        fields.String(validate=validate.Length(min=1, max=240)), validate=validate.Length(max=30)
    )
    translations = fields.List(
        fields.Nested(EventTranslationSchema), validate=validate.Length(equal=2)
    )
    speakers = fields.List(fields.Nested(EventSpeakerSchema))


def _service():  # type: ignore[no-untyped-def]
    return event_service_from_container(current_app.extensions["container"])


CONTENT_ROLES = ("content_manager", "admin", "super_admin")


@api_v1.get("/events")
@api_v1.arguments(EventQuerySchema, location="query")
def events(query: dict):  # type: ignore[no-untyped-def]
    return {"data": _service().list(query["locale"], query["kind"], query["status"])}


@api_v1.get("/events/<string:slug>")
@api_v1.arguments(EventQuerySchema(only=("locale",)), location="query")
def event_detail(query: dict, slug: str):  # type: ignore[no-untyped-def]
    return {"data": _service().detail(slug, query["locale"])}


@api_v1.get("/admin/events")
@roles_required(*CONTENT_ROLES)
def admin_events():  # type: ignore[no-untyped-def]
    return {"data": _service().admin_list()}


@api_v1.post("/admin/events")
@roles_required(*CONTENT_ROLES)
@api_v1.arguments(EventMutationSchema)
def create_event(data: dict):  # type: ignore[no-untyped-def]
    staged = stage_change("event", f"new:{data['slug']}", "create", data)
    if staged:
        return staged
    return {"data": _service().create(data)}, 201


@api_v1.get("/admin/events/speakers")
@roles_required(*CONTENT_ROLES)
def event_speaker_options():
    return {"data": _service().speaker_options(request.args.get("q", "")[:100])}


@api_v1.patch("/admin/events/<uuid:event_id>")
@roles_required(*CONTENT_ROLES)
@api_v1.arguments(EventUpdateSchema)
def update_event(data: dict, event_id: UUID):  # type: ignore[no-untyped-def]
    staged = stage_change("event", str(event_id), "update", data, resource_id=event_id)
    if staged:
        return staged
    return {"data": _service().update(event_id, data)}


@api_v1.post("/admin/events/<uuid:event_id>/publish")
@roles_required(*CONTENT_ROLES)
def publish_event(event_id: UUID):  # type: ignore[no-untyped-def]
    staged = stage_change("event", str(event_id), "publish", resource_id=event_id)
    if staged:
        return staged
    return {"data": _service().publish(event_id, True)}


@api_v1.post("/admin/events/<uuid:event_id>/unpublish")
@roles_required(*CONTENT_ROLES)
def unpublish_event(event_id: UUID):  # type: ignore[no-untyped-def]
    staged = stage_change("event", str(event_id), "unpublish", resource_id=event_id)
    if staged:
        return staged
    return {"data": _service().publish(event_id, False)}


@api_v1.delete("/admin/events/<uuid:event_id>")
@roles_required(*CONTENT_ROLES)
def archive_event(event_id: UUID):  # type: ignore[no-untyped-def]
    staged = stage_change("event", str(event_id), "archive", resource_id=event_id)
    if staged:
        return staged
    _service().archive(event_id)
    return "", 204


@api_v1.post("/events/<string:slug>/reservations")
@jwt_required()
def reserve_event(slug: str):  # type: ignore[no-untyped-def]
    result = _service().reserve(UUID(get_jwt_identity()), slug)
    return {"data": result}, 200 if result["status"] == "confirmed" else 202


class ReservationConfirmationSchema(Schema):
    token = fields.String(required=True, validate=validate.Length(min=20, max=2048))


@api_v1.post("/events/reservations/confirm")
@limiter.limit("10 per hour")
@api_v1.arguments(ReservationConfirmationSchema)
def confirm_event_reservation(data: dict):  # type: ignore[no-untyped-def]
    return {"data": _service().confirm_reservation(data["token"])}


@api_v1.delete("/events/<string:slug>/reservations/me")
@jwt_required()
def cancel_event_reservation(slug: str):  # type: ignore[no-untyped-def]
    _service().cancel(UUID(get_jwt_identity()), slug)
    return "", 204


@api_v1.get("/events/<string:slug>/reservations/me")
@jwt_required()
def my_event_reservation(slug: str):
    return {"data": _service().reservation(UUID(get_jwt_identity()), slug)}


@api_v1.get("/admin/events/<uuid:event_id>/reservations")
@roles_required(*CONTENT_ROLES)
def event_attendees(event_id: UUID):
    return {"data": _service().attendees(event_id)}


@api_v1.delete("/admin/events/<uuid:event_id>/reservations/<uuid:user_id>")
@roles_required(*CONTENT_ROLES)
def cancel_attendee(event_id: UUID, user_id: UUID):
    _service().cancel_attendee(event_id, user_id)
    return "", 204


class LiveControlSchema(Schema):
    status = fields.String(validate=validate.OneOf(["live", "completed"]))
    chat_enabled = fields.Boolean()
    questions_enabled = fields.Boolean()


@api_v1.patch("/events/<string:slug>/live/control")
@jwt_required()
@api_v1.arguments(LiveControlSchema)
def live_control(data: dict, slug: str):
    return {"data": _live().configure(slug, UUID(get_jwt_identity()), data)}


@api_v1.delete("/events/<string:slug>/live/<string:kind>/<uuid:item_id>")
@jwt_required()
def moderate_live(slug: str, kind: str, item_id: UUID):
    _live().moderate(slug, UUID(get_jwt_identity()), kind, item_id)
    return "", 204


class LiveTextSchema(Schema):
    body = fields.String(required=True, validate=validate.Length(min=1, max=1000))


class LiveStepSchema(Schema):
    step = fields.Integer(required=True, validate=validate.Range(min=0))


def _live():  # type: ignore[no-untyped-def]
    return live_service_from_container(current_app.extensions["container"])


def _country_code() -> str | None:
    """Resolve country from an optional local GeoLite2 database, never a client header."""
    path = current_app.config.get("GEOIP_DATABASE_PATH")
    if not path:
        return None
    remote_ip = request.remote_addr or ""
    trusted_proxies = {
        item.strip() for item in current_app.config.get("TRUSTED_PROXY_IPS", "").split(",")
    }
    if remote_ip in trusted_proxies:
        forwarded = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        if forwarded:
            remote_ip = forwarded
    try:
        ip_address(remote_ip)
        import maxminddb

        with maxminddb.open_database(path) as db:
            data = db.get(remote_ip) or {}
            value = (data.get("country") or {}).get("iso_code")
            return value if isinstance(value, str) and len(value) == 2 else None
    except (ImportError, OSError, ValueError):
        return None


@api_v1.get("/events/<string:slug>/live")
@jwt_required()
def event_live(slug: str):  # type: ignore[no-untyped-def]
    locale = request.args.get("locale", "en")
    if locale not in {"en", "fa"}:
        raise ValidationError("Locale must be en or fa.")
    return (
        {"data": _live().snapshot(slug, UUID(get_jwt_identity()), _country_code(), locale)},
        200,
        {"Cache-Control": "private, no-store"},
    )


@api_v1.post("/events/<string:slug>/live/messages")
@limiter.limit("15 per minute")
@jwt_required()
@api_v1.arguments(LiveTextSchema)
def event_live_message(data: dict, slug: str):  # type: ignore[no-untyped-def]
    return {"data": _live().post(slug, UUID(get_jwt_identity()), "message", data["body"])}, 201


@api_v1.post("/events/<string:slug>/live/questions")
@limiter.limit("6 per minute")
@jwt_required()
@api_v1.arguments(LiveTextSchema)
def event_live_question(data: dict, slug: str):  # type: ignore[no-untyped-def]
    return {"data": _live().post(slug, UUID(get_jwt_identity()), "question", data["body"])}, 201


@api_v1.post("/events/<string:slug>/live/questions/<uuid:question_id>/vote")
@limiter.limit("30 per minute")
@jwt_required()
def event_live_vote(slug: str, question_id: UUID):  # type: ignore[no-untyped-def]
    return {"data": _live().vote(slug, UUID(get_jwt_identity()), question_id)}


@api_v1.post("/events/<string:slug>/live/questions/<uuid:question_id>/answer")
@jwt_required()
def event_live_answer(slug: str, question_id: UUID):  # type: ignore[no-untyped-def]
    return {"data": _live().control(slug, UUID(get_jwt_identity()), question_id=question_id)}


@api_v1.post("/events/<string:slug>/live/step")
@jwt_required()
@api_v1.arguments(LiveStepSchema)
def event_live_step(data: dict, slug: str):  # type: ignore[no-untyped-def]
    return {"data": _live().control(slug, UUID(get_jwt_identity()), step=data["step"])}
