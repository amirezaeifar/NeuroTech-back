"""Schemas shared across the HTTP layer."""

from __future__ import annotations

from marshmallow import Schema, fields


class PaginationMetaSchema(Schema):
    page = fields.Integer(required=True)
    page_size = fields.Integer(required=True)
    total = fields.Integer(required=True)


class ProblemErrorSchema(Schema):
    field = fields.String(required=False)
    code = fields.String(required=True)
    detail = fields.String(required=False)


class ProblemSchema(Schema):
    type = fields.Url(required=True)
    title = fields.String(required=True)
    status = fields.Integer(required=True)
    detail = fields.String(required=True)
    instance = fields.String(required=True)
    code = fields.String(required=True)
    request_id = fields.UUID(required=True)
    errors = fields.List(fields.Nested(ProblemErrorSchema), required=False)
