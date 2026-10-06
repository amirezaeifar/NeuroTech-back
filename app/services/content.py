"""Partner-directory and global-trade content use cases."""

from __future__ import annotations

import re
import unicodedata
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.auth_models import User
from app.core.catalog_models import StoredFile
from app.core.content_models import (
    ManagedPage,
    ManagedPageTranslation,
    PartnerProfile,
    PartnerTranslation,
    TradeDocument,
    TradeDocumentTranslation,
)
from app.core.unit_of_work import SqlAlchemyUnitOfWork
from app.domain.catalog import validate_slug, validate_translations
from app.domain.errors import ConflictError, NotFoundError, ValidationError

MANAGED_PAGE_KEYS = {"academy", "products", "events", "partners", "global-trade"}


class ContentService:
    def __init__(self, uow_factory) -> None:  # type: ignore[no-untyped-def]
        self.uow_factory = uow_factory

    def partners(self, locale: str, *, admin: bool = False) -> list[dict]:
        conditions = [PartnerProfile.archived_at.is_(None)]
        if not admin:
            conditions.append(PartnerProfile.published_at.is_not(None))
        with self.uow_factory() as uow:
            rows = list(
                uow.session.scalars(
                    select(PartnerProfile)
                    .options(selectinload(PartnerProfile.translations))
                    .where(*conditions)
                    .order_by(PartnerProfile.position, PartnerProfile.created_at)
                ).unique()
            )
            return [_partner_payload(row, locale, admin=admin) for row in rows]

    def partner(self, slug: str, locale: str, *, admin: bool = False) -> dict:
        with self.uow_factory() as uow:
            query = (
                select(PartnerProfile)
                .options(selectinload(PartnerProfile.translations))
                .where(PartnerProfile.slug == slug, PartnerProfile.archived_at.is_(None))
            )
            if not admin:
                query = query.where(PartnerProfile.published_at.is_not(None))
            partner = uow.session.scalar(query)
            if partner is None:
                raise NotFoundError("Partner profile does not exist.")
            return _partner_payload(partner, locale, admin=admin)

    def create_partner(self, data: dict) -> dict:
        validate_translations(data["translations"])
        partner_id = uuid4()
        english = next(
            (item for item in data["translations"] if item["locale"] == "en"),
            data["translations"][0],
        )
        slug = _partner_slug(english["name"], partner_id)
        with self.uow_factory() as uow:
            self._validate_references(uow.session, data)
            partner = PartnerProfile(
                id=partner_id,
                slug=slug,
                user_id=data.get("user_id"),
                position=data.get("position", 0),
                image_file_id=data.get("image_file_id"),
            )
            partner.translations.extend(PartnerTranslation(**item) for item in data["translations"])
            uow.session.add(partner)
            uow.commit()
            return _partner_payload(partner, "en", admin=True)

    def update_partner(self, partner_id: UUID, data: dict) -> dict:
        with self.uow_factory() as uow:
            partner = uow.session.scalar(
                select(PartnerProfile)
                .options(selectinload(PartnerProfile.translations))
                .where(PartnerProfile.id == partner_id, PartnerProfile.archived_at.is_(None))
            )
            if partner is None:
                raise NotFoundError("Partner profile does not exist.")
            self._validate_references(uow.session, data, partner_id=partner.id)
            for key in ("user_id", "position", "image_file_id"):
                if key in data:
                    setattr(partner, key, data[key])
            if "translations" in data:
                validate_translations(data["translations"])
                partner.translations.clear()
                uow.session.flush()
                partner.translations.extend(
                    PartnerTranslation(**item) for item in data["translations"]
                )
            uow.commit()
            return _partner_payload(partner, "en", admin=True)

    def publish_partner(self, partner_id: UUID, published: bool) -> dict:
        with self.uow_factory() as uow:
            partner = uow.session.scalar(
                select(PartnerProfile)
                .options(selectinload(PartnerProfile.translations))
                .where(PartnerProfile.id == partner_id, PartnerProfile.archived_at.is_(None))
            )
            if partner is None:
                raise NotFoundError("Partner profile does not exist.")
            validate_translations([{"locale": item.locale} for item in partner.translations])
            partner.published_at = datetime.now(UTC) if published else None
            uow.commit()
            return _partner_payload(partner, "en", admin=True)

    def archive_partner(self, partner_id: UUID) -> None:
        with self.uow_factory() as uow:
            partner = uow.session.get(PartnerProfile, partner_id)
            if partner:
                partner.archived_at = partner.archived_at or datetime.now(UTC)
                partner.published_at = None
                uow.commit()

    def trade_documents(self, locale: str, *, admin: bool = False) -> list[dict]:
        conditions = [TradeDocument.archived_at.is_(None)]
        if not admin:
            conditions.append(TradeDocument.published_at.is_not(None))
        with self.uow_factory() as uow:
            rows = list(
                uow.session.scalars(
                    select(TradeDocument)
                    .options(selectinload(TradeDocument.translations))
                    .where(*conditions)
                    .order_by(TradeDocument.position, TradeDocument.created_at)
                ).unique()
            )
            return [_trade_payload(row, locale, admin=admin) for row in rows]

    def trade_document(self, slug: str, locale: str, *, admin: bool = False) -> dict:
        with self.uow_factory() as uow:
            query = (
                select(TradeDocument)
                .options(selectinload(TradeDocument.translations))
                .where(TradeDocument.slug == slug, TradeDocument.archived_at.is_(None))
            )
            if not admin:
                query = query.where(TradeDocument.published_at.is_not(None))
            document = uow.session.scalar(query)
            if document is None:
                raise NotFoundError("Trade document does not exist.")
            return _trade_payload(document, locale, admin=admin)

    def create_trade_document(self, data: dict) -> dict:
        slug = validate_slug(data["slug"])
        validate_translations(data["translations"])
        with self.uow_factory() as uow:
            duplicate = uow.session.scalar(
                select(TradeDocument.id).where(
                    (TradeDocument.slug == slug)
                    | (TradeDocument.document_code == data["document_code"])
                )
            )
            if duplicate:
                raise ConflictError("Trade document slug or code already exists.")
            self._validate_file(uow.session, data.get("attachment_file_id"))
            document = TradeDocument(
                slug=slug,
                document_code=data["document_code"].strip(),
                position=data.get("position", 0),
                attachment_file_id=data.get("attachment_file_id"),
            )
            document.translations.extend(
                TradeDocumentTranslation(**item) for item in data["translations"]
            )
            uow.session.add(document)
            uow.commit()
            return _trade_payload(document, "en", admin=True)

    def update_trade_document(self, document_id: UUID, data: dict) -> dict:
        with self.uow_factory() as uow:
            document = uow.session.scalar(
                select(TradeDocument)
                .options(selectinload(TradeDocument.translations))
                .where(TradeDocument.id == document_id, TradeDocument.archived_at.is_(None))
            )
            if document is None:
                raise NotFoundError("Trade document does not exist.")
            if "document_code" in data:
                code = data["document_code"].strip()
                duplicate = uow.session.scalar(
                    select(TradeDocument.id).where(
                        TradeDocument.document_code == code, TradeDocument.id != document.id
                    )
                )
                if duplicate:
                    raise ConflictError("Trade document code already exists.")
                document.document_code = code
            for key in ("position", "attachment_file_id"):
                if key in data:
                    setattr(document, key, data[key])
            if "attachment_file_id" in data:
                self._validate_file(uow.session, data["attachment_file_id"])
            if "translations" in data:
                validate_translations(data["translations"])
                document.translations.clear()
                uow.session.flush()
                document.translations.extend(
                    TradeDocumentTranslation(**item) for item in data["translations"]
                )
            uow.commit()
            return _trade_payload(document, "en", admin=True)

    def publish_trade_document(self, document_id: UUID, published: bool) -> dict:
        with self.uow_factory() as uow:
            document = uow.session.scalar(
                select(TradeDocument)
                .options(selectinload(TradeDocument.translations))
                .where(TradeDocument.id == document_id, TradeDocument.archived_at.is_(None))
            )
            if document is None:
                raise NotFoundError("Trade document does not exist.")
            validate_translations([{"locale": item.locale} for item in document.translations])
            document.published_at = datetime.now(UTC) if published else None
            uow.commit()
            return _trade_payload(document, "en", admin=True)

    def archive_trade_document(self, document_id: UUID) -> None:
        with self.uow_factory() as uow:
            document = uow.session.get(TradeDocument, document_id)
            if document:
                document.archived_at = document.archived_at or datetime.now(UTC)
                document.published_at = None
                uow.commit()

    def page_content(self, page_key: str, locale: str, *, admin: bool = False) -> dict:
        _validate_page_key(page_key)
        with self.uow_factory() as uow:
            query = (
                select(ManagedPage)
                .options(selectinload(ManagedPage.translations))
                .where(ManagedPage.page_key == page_key, ManagedPage.archived_at.is_(None))
            )
            if not admin:
                query = query.where(ManagedPage.published_at.is_not(None))
            page = uow.session.scalar(query)
            if page is None:
                raise NotFoundError("Managed page content does not exist.")
            translation = _localized(page.translations, locale)
            return {
                "page_key": page.page_key,
                "locale": translation.locale,
                "content": translation.content,
                "published": page.published_at is not None,
                **(
                    {
                        "translations": [
                            {"locale": item.locale, "content": item.content}
                            for item in page.translations
                        ]
                    }
                    if admin
                    else {}
                ),
            }

    def managed_pages(self) -> list[dict]:
        result = []
        for key in sorted(MANAGED_PAGE_KEYS):
            try:
                result.append(self.page_content(key, "en", admin=True))
            except NotFoundError:
                result.append(
                    {
                        "page_key": key,
                        "published": False,
                        "translations": [
                            {"locale": "en", "content": {}},
                            {"locale": "fa", "content": {}},
                        ],
                    }
                )
        return result

    def save_page_content(self, page_key: str, translations: list[dict]) -> dict:
        _validate_page_key(page_key)
        validate_translations(translations)
        with self.uow_factory() as uow:
            page = uow.session.scalar(
                select(ManagedPage)
                .options(selectinload(ManagedPage.translations))
                .where(ManagedPage.page_key == page_key, ManagedPage.archived_at.is_(None))
            )
            if page is None:
                page = ManagedPage(page_key=page_key)
                uow.session.add(page)
            else:
                page.translations.clear()
                uow.session.flush()
            page.translations.extend(ManagedPageTranslation(**item) for item in translations)
            uow.commit()
            return self.page_content(page_key, "en", admin=True)

    def publish_page_content(self, page_key: str, published: bool) -> dict:
        _validate_page_key(page_key)
        with self.uow_factory() as uow:
            page = uow.session.scalar(
                select(ManagedPage)
                .options(selectinload(ManagedPage.translations))
                .where(ManagedPage.page_key == page_key, ManagedPage.archived_at.is_(None))
            )
            if page is None:
                raise NotFoundError("Managed page content does not exist.")
            validate_translations([{"locale": item.locale} for item in page.translations])
            page.published_at = datetime.now(UTC) if published else None
            uow.commit()
            return self.page_content(page_key, "en", admin=True)

    def _validate_references(
        self, session, data: dict, *, partner_id: UUID | None = None  # type: ignore[no-untyped-def]
    ) -> None:
        user_id = data.get("user_id")
        if user_id is not None:
            if session.get(User, user_id) is None:
                raise ValidationError("Linked user does not exist.")
            duplicate_query = select(PartnerProfile.id).where(
                PartnerProfile.user_id == user_id
            )
            if partner_id:
                duplicate_query = duplicate_query.where(PartnerProfile.id != partner_id)
            duplicate = session.scalar(duplicate_query)
            if duplicate:
                raise ConflictError("This user already has a partner profile.")
        self._validate_file(session, data.get("image_file_id"))

    @staticmethod
    def _validate_file(session, file_id: UUID | None) -> None:  # type: ignore[no-untyped-def]
        if file_id is not None and session.get(StoredFile, file_id) is None:
            raise ValidationError("Stored file does not exist.")


def _localized(items: list, locale: str):  # type: ignore[no-untyped-def,type-arg]
    return (
        next((item for item in items if item.locale == locale), None)
        or next((item for item in items if item.locale == "en"), None)
        or items[0]
    )


def _validate_page_key(page_key: str) -> None:
    if page_key not in MANAGED_PAGE_KEYS:
        raise ValidationError("This page is static or is not managed by the CMS.")


def _partner_slug(name: str, partner_id: UUID) -> str:
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    stem = "-".join(re.findall(r"[a-z0-9]+", ascii_name.lower()))[:120].strip("-")
    return f"{stem or 'partner'}-{partner_id.hex}"


def _partner_payload(partner: PartnerProfile, locale: str, *, admin: bool = False) -> dict:
    translation = _localized(partner.translations, locale)
    result = {
        "id": str(partner.id),
        "slug": partner.slug,
        "user_id": str(partner.user_id) if partner.user_id else None,
        "position": partner.position,
        "image_url": f"/api/v1/files/{partner.image_file_id}" if partner.image_file_id else None,
        "image_file_id": str(partner.image_file_id) if partner.image_file_id else None,
        "published": partner.published_at is not None,
        "name": translation.name,
        "title": translation.title,
        "qualification": translation.qualification,
        "location": translation.location,
        "affiliation": translation.affiliation,
        "bio": translation.bio,
        **(translation.details or {}),
    }
    if admin:
        result["translations"] = [
            {
                "locale": item.locale,
                "name": item.name,
                "title": item.title,
                "qualification": item.qualification,
                "location": item.location,
                "affiliation": item.affiliation,
                "bio": item.bio,
                "details": item.details,
            }
            for item in partner.translations
        ]
    return result


def _trade_payload(document: TradeDocument, locale: str, *, admin: bool = False) -> dict:
    translation = _localized(document.translations, locale)
    result = {
        "id": document.document_code,
        "record_id": str(document.id),
        "slug": document.slug,
        "position": document.position,
        "title": translation.title,
        "docType": translation.doc_type,
        "partner": translation.partner_name,
        "category": translation.category,
        "location": translation.location,
        "region": translation.region,
        "summary": translation.summary,
        "groups": translation.groups,
        "attachment_url": (
            f"/api/v1/files/{document.attachment_file_id}"
            if document.attachment_file_id
            else None
        ),
        "attachment_file_id": (
            str(document.attachment_file_id) if document.attachment_file_id else None
        ),
        "published": document.published_at is not None,
    }
    if admin:
        result["translations"] = [
            {
                "locale": item.locale,
                "title": item.title,
                "doc_type": item.doc_type,
                "partner_name": item.partner_name,
                "category": item.category,
                "location": item.location,
                "region": item.region,
                "summary": item.summary,
                "groups": item.groups,
            }
            for item in document.translations
        ]
    return result


def content_service_from_container(container) -> ContentService:  # type: ignore[no-untyped-def]
    return ContentService(lambda: SqlAlchemyUnitOfWork(container.database.session_factory))
