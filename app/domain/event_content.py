"""Validated, structured content for the existing event page sections."""

from marshmallow import Schema, fields, validate

MEDIA_URL = validate.Regexp(r"^(https://[^\s]+|/api/v1/files/[0-9a-fA-F-]{36})$")


class EventMediaSchema(Schema):
    url = fields.String(required=True, validate=[validate.Length(max=1000), MEDIA_URL])
    name = fields.String(required=True, validate=validate.Length(min=1, max=240))
    type = fields.String(load_default="", validate=validate.Length(max=30))
    size = fields.String(load_default="", validate=validate.Length(max=40))


class EventAgendaSchema(Schema):
    time = fields.String(load_default="", validate=validate.Length(max=40))
    title = fields.String(required=True, validate=validate.Length(min=1, max=240))
    detail = fields.String(load_default="", validate=validate.Length(max=2000))


class EventFaqSchema(Schema):
    q = fields.String(required=True, validate=validate.Length(min=1, max=500))
    a = fields.String(required=True, validate=validate.Length(min=1, max=4000))


class EventContentSchema(Schema):
    gallery = fields.List(
        fields.Nested(EventMediaSchema), load_default=list, validate=validate.Length(max=40)
    )
    videos = fields.List(
        fields.Nested(EventMediaSchema), load_default=list, validate=validate.Length(max=20)
    )
    documents = fields.List(
        fields.Nested(EventMediaSchema), load_default=list, validate=validate.Length(max=40)
    )
    agenda = fields.List(
        fields.Nested(EventAgendaSchema), load_default=list, validate=validate.Length(max=40)
    )
    faq = fields.List(
        fields.Nested(EventFaqSchema), load_default=list, validate=validate.Length(max=30)
    )
    closing_note = fields.String(load_default="", validate=validate.Length(max=4000))
