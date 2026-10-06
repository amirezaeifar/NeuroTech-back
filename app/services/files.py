"""Safe local-file persistence for small public website assets."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

from app.core.catalog_models import StoredFile
from app.core.unit_of_work import SqlAlchemyUnitOfWork
from app.domain.errors import NotFoundError, ValidationError

ALLOWED_UPLOADS = {
    ".7z": {"application/x-7z-compressed", "application/octet-stream"},
    ".csv": {"text/csv", "application/csv", "text/plain", "application/vnd.ms-excel"},
    ".doc": {"application/msword", "application/octet-stream"},
    ".docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
    ".gif": {"image/gif"},
    ".jpeg": {"image/jpeg"},
    ".jpg": {"image/jpeg"},
    ".json": {"application/json", "text/json", "text/plain"},
    ".mov": {"video/quicktime", "application/octet-stream"},
    ".mp3": {"audio/mpeg", "audio/mp3", "application/octet-stream"},
    ".mp4": {"video/mp4", "application/octet-stream"},
    ".ogg": {"audio/ogg", "video/ogg", "application/ogg"},
    ".pdf": {"application/pdf"},
    ".png": {"image/png"},
    ".ppt": {"application/vnd.ms-powerpoint", "application/octet-stream"},
    ".pptx": {"application/vnd.openxmlformats-officedocument.presentationml.presentation"},
    ".rar": {"application/vnd.rar", "application/x-rar-compressed", "application/octet-stream"},
    ".rtf": {"application/rtf", "text/rtf", "application/octet-stream"},
    ".txt": {"text/plain"},
    ".wav": {"audio/wav", "audio/x-wav", "audio/wave", "application/octet-stream"},
    ".webm": {"video/webm", "audio/webm", "application/octet-stream"},
    ".webp": {"image/webp"},
    ".woff": {"font/woff", "application/font-woff", "application/octet-stream"},
    ".woff2": {"font/woff2", "application/octet-stream"},
    ".xls": {"application/vnd.ms-excel", "application/octet-stream"},
    ".xlsx": {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
    ".zip": {"application/zip", "application/x-zip-compressed", "application/octet-stream"},
}
MAX_UPLOAD_BYTES = 100 * 1024 * 1024
CHUNK_BYTES = 64 * 1024


class LocalFileService:
    def __init__(self, uow_factory, upload_root: Path) -> None:  # type: ignore[no-untyped-def]
        self.uow_factory = uow_factory
        self.upload_root = upload_root.resolve()

    def save(self, uploader_id: UUID, upload: FileStorage, *, is_public: bool, max_bytes: int = MAX_UPLOAD_BYTES) -> dict:
        original_name = secure_filename(upload.filename or "")
        if not original_name:
            raise ValidationError("A file with a valid name is required.")
        suffix = Path(original_name).suffix.lower()
        if suffix not in ALLOWED_UPLOADS:
            raise ValidationError("This file extension is not allowed.")
        mime_type = (upload.mimetype or "application/octet-stream").lower()
        if mime_type not in ALLOWED_UPLOADS[suffix]:
            raise ValidationError("The file MIME type does not match its extension.")

        now = datetime.now(UTC)
        storage_key = f"{now:%Y/%m}/{uuid4().hex}{suffix}"
        destination = (self.upload_root / storage_key).resolve()
        if self.upload_root not in destination.parents:
            raise ValidationError("Invalid storage path.")
        destination.parent.mkdir(parents=True, exist_ok=True)

        size = 0
        digest = hashlib.sha256()
        signature = bytearray()
        try:
            with destination.open("xb") as target:
                while chunk := upload.stream.read(CHUNK_BYTES):
                    size += len(chunk)
                    if size > max_bytes:
                        raise ValidationError(f"File size cannot exceed {max_bytes // (1024 * 1024)} MB.")
                    if len(signature) < 16:
                        signature.extend(chunk[: 16 - len(signature)])
                    digest.update(chunk)
                    target.write(chunk)
            if size == 0:
                raise ValidationError("Empty files cannot be uploaded.")
            if not _matches_signature(suffix, bytes(signature)):
                raise ValidationError("File content does not match its declared type.")

            with self.uow_factory() as uow:
                stored = StoredFile(
                    uploader_id=uploader_id,
                    storage_key=storage_key,
                    original_name=original_name,
                    mime_type=mime_type,
                    size_bytes=size,
                    sha256=digest.hexdigest(),
                    is_public=is_public,
                )
                uow.session.add(stored)
                uow.commit()
                return _payload(stored)
        except Exception:
            destination.unlink(missing_ok=True)
            raise

    def resolve_public(self, file_id: UUID) -> tuple[Path, StoredFile]:
        with self.uow_factory() as uow:
            stored = uow.session.get(StoredFile, file_id)
            if stored is None or stored.archived_at is not None or not stored.is_public:
                raise NotFoundError("File does not exist.")
            path = (self.upload_root / stored.storage_key).resolve()
            if self.upload_root not in path.parents or not path.is_file():
                raise NotFoundError("File does not exist.")
            uow.session.expunge(stored)
            return path, stored

    def resolve_owned(self, file_id: UUID, owner_id: UUID) -> tuple[Path, StoredFile]:
        with self.uow_factory() as uow:
            stored = uow.session.get(StoredFile, file_id)
            if stored is None or stored.archived_at is not None or stored.uploader_id != owner_id:
                raise NotFoundError("File does not exist.")
            path = (self.upload_root / stored.storage_key).resolve()
            if self.upload_root not in path.parents or not path.is_file():
                raise NotFoundError("File does not exist.")
            uow.session.expunge(stored)
            return path, stored

    def delete(self, file_id: UUID) -> None:
        with self.uow_factory() as uow:
            stored = uow.session.get(StoredFile, file_id)
            if stored is None or stored.archived_at is not None:
                raise NotFoundError("File does not exist.")
            path = (self.upload_root / stored.storage_key).resolve()
            if self.upload_root not in path.parents:
                raise ValidationError("Invalid storage path.")
            stored.archived_at = datetime.now(UTC)
            uow.commit()
        path.unlink(missing_ok=True)


def _payload(stored: StoredFile) -> dict:
    return {
        "id": str(stored.id),
        "original_name": stored.original_name,
        "mime_type": stored.mime_type,
        "size_bytes": stored.size_bytes,
        "sha256": stored.sha256,
        "is_public": stored.is_public,
        "url": f"/api/v1/files/{stored.id}" if stored.is_public else None,
    }


def _matches_signature(suffix: str, signature: bytes) -> bool:
    if suffix in {".docx", ".pptx", ".xlsx", ".zip"}:
        return signature.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"))
    if suffix in {".doc", ".ppt", ".xls"}:
        return signature.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1")
    if suffix == ".7z":
        return signature.startswith(b"7z\xbc\xaf\x27\x1c")
    if suffix == ".rar":
        return signature.startswith((b"Rar!\x1a\x07\x00", b"Rar!\x1a\x07\x01\x00"))
    if suffix == ".png":
        return signature.startswith(b"\x89PNG\r\n\x1a\n")
    if suffix in {".jpg", ".jpeg"}:
        return signature.startswith(b"\xff\xd8\xff")
    if suffix == ".gif":
        return signature.startswith((b"GIF87a", b"GIF89a"))
    if suffix == ".webp":
        return signature.startswith(b"RIFF") and signature[8:12] == b"WEBP"
    if suffix == ".pdf":
        return signature.startswith(b"%PDF-")
    if suffix in {".mp4", ".mov"}:
        return len(signature) >= 12 and signature[4:8] == b"ftyp"
    if suffix == ".webm":
        return signature.startswith(b"\x1aE\xdf\xa3")
    if suffix == ".ogg":
        return signature.startswith(b"OggS")
    if suffix == ".wav":
        return signature.startswith(b"RIFF") and signature[8:12] == b"WAVE"
    if suffix == ".mp3":
        return signature.startswith(b"ID3") or (
            len(signature) >= 2 and signature[0] == 0xFF and signature[1] & 0xE0 == 0xE0
        )
    if suffix == ".rtf":
        return signature.startswith(b"{\\rtf")
    if suffix == ".woff":
        return signature.startswith(b"wOFF")
    if suffix == ".woff2":
        return signature.startswith(b"wOF2")
    if suffix in {".txt", ".csv", ".json"}:
        return b"\x00" not in signature and not signature.startswith(b"MZ")
    return False


def file_service_from_container(container, upload_root: str) -> LocalFileService:  # type: ignore[no-untyped-def]
    return LocalFileService(
        lambda: SqlAlchemyUnitOfWork(container.database.session_factory),
        Path(upload_root),
    )
