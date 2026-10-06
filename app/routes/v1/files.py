"""Administrative local upload and public file delivery endpoints."""

from __future__ import annotations

from uuid import UUID

from flask import current_app, request, send_file
from flask_jwt_extended import get_jwt_identity

from app.domain.errors import ValidationError
from app.routes.authz import roles_required
from app.routes.v1 import api_v1
from app.services.files import file_service_from_container


def _service():  # type: ignore[no-untyped-def]
    return file_service_from_container(
        current_app.extensions["container"], current_app.config["UPLOAD_ROOT"]
    )


@api_v1.post("/admin/files")
@roles_required("specialist", "content_manager", "admin", "super_admin")
def upload_file():  # type: ignore[no-untyped-def]
    upload = request.files.get("file")
    if upload is None:
        raise ValidationError("Multipart field 'file' is required.")
    public_value = request.form.get("is_public", "true").strip().lower()
    if public_value not in {"true", "false"}:
        raise ValidationError("is_public must be true or false.")
    return {
        "data": _service().save(UUID(get_jwt_identity()), upload, is_public=public_value == "true")
    }, 201


@api_v1.get("/files/<uuid:file_id>")
def public_file(file_id: UUID):  # type: ignore[no-untyped-def]
    path, stored = _service().resolve_public(file_id)
    return send_file(
        path,
        mimetype=stored.mime_type,
        download_name=stored.original_name,
        as_attachment=request.args.get("download", "").strip().lower() in {"1", "true", "yes"},
        conditional=True,
        max_age=3600,
    )


@api_v1.delete("/admin/files/<uuid:file_id>")
@roles_required("specialist", "content_manager", "admin", "super_admin")
def delete_file(file_id: UUID):  # type: ignore[no-untyped-def]
    _service().delete(file_id)
    return "", 204
