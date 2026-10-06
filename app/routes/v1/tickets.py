"""Guest support submission, private tracking and administrator responses."""

from flask import current_app
from flask_jwt_extended import get_jwt_identity
from marshmallow import Schema, fields, validate

from app.core.extensions import limiter
from app.routes.authz import roles_required
from app.routes.v1 import api_v1
from app.services.tickets import TicketService

TICKET_CATEGORIES = [
    "technical",
    "courses",
    "orders_payments",
    "products",
    "partnerships",
    "general",
]


class TicketCreateSchema(Schema):
    name = fields.String(required=True, validate=validate.Length(min=1, max=160))
    phone = fields.String(required=True, validate=validate.Length(min=7, max=24))
    email = fields.Email(load_default=None, allow_none=True, validate=validate.Length(max=254))
    subject = fields.String(required=True, validate=validate.Length(min=1, max=240))
    message = fields.String(required=True, validate=validate.Length(min=1, max=10000))
    locale = fields.String(load_default="fa", validate=validate.OneOf(["en", "fa"]))
    category = fields.String(load_default="general", validate=validate.OneOf(TICKET_CATEGORIES))


class TicketQuerySchema(Schema):
    page = fields.Integer(load_default=1, validate=validate.Range(min=1))
    page_size = fields.Integer(load_default=20, validate=validate.Range(min=1, max=100))
    status = fields.String(
        validate=validate.OneOf(
            ["open", "closed", "submitted", "in_progress", "resolved", "rejected"]
        )
    )
    q = fields.String(load_default="", validate=validate.Length(max=160))
    category = fields.String(validate=validate.OneOf(TICKET_CATEGORIES))


class TicketReplySchema(Schema):
    status = fields.String(
        required=True,
        validate=validate.OneOf(["submitted", "in_progress", "resolved", "rejected"]),
    )
    reply = fields.String(load_default="", validate=validate.Length(max=10000))
    version = fields.Integer(required=True, validate=validate.Range(min=1))


def _service():
    return TicketService(current_app.extensions["container"])


@api_v1.post("/tickets")
@limiter.limit("5 per minute")
@api_v1.arguments(TicketCreateSchema)
def create_ticket(data):
    return {"data": _service().create(data)}, 201


@api_v1.get("/tickets/track/<string:token>")
@limiter.limit("30 per minute")
def track_ticket(token):
    return {"data": _service().detail(token)}


@api_v1.get("/admin/tickets")
@roles_required("admin", "super_admin")
@api_v1.arguments(TicketQuerySchema, location="query")
def list_tickets(query):
    return _service().list(**query)


@api_v1.get("/admin/tickets/<uuid:ticket_id>")
@roles_required("admin", "super_admin")
def ticket_detail(ticket_id):
    return {"data": _service().detail(ticket_id, admin=True)}


@api_v1.patch("/admin/tickets/<uuid:ticket_id>")
@roles_required("admin", "super_admin")
@api_v1.arguments(TicketReplySchema)
def reply_ticket(data, ticket_id):
    return {"data": _service().update(ticket_id, data, get_jwt_identity())}
