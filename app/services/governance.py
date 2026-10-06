"""Content approvals, blog authoring, and platform settings use cases."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.auth_models import User
from app.core.governance_models import (
    ApprovalRequest,
    BlogPost,
    BlogPostTranslation,
    SiteSetting,
)
from app.core.unit_of_work import SqlAlchemyUnitOfWork
from app.domain.errors import ConflictError, NotFoundError, ValidationError

DEFAULT_SETTINGS = {
    "site_name": "Neuro Tech",
    "support_email": "neuro.tech.pishro@gmail.com",
    "maintenance": False,
    "registrations": True,
    "auto_approve_comments": False,
    "premium_checkout": True,
}


class GovernanceService:
    def __init__(self, container) -> None:  # type: ignore[no-untyped-def]
        self.container = container
        self.uow_factory = lambda: SqlAlchemyUnitOfWork(container.database.session_factory)

    def submit_change(
        self,
        *,
        resource_type: str,
        resource_key: str,
        action: str,
        payload: dict | None,
        actor_id: UUID,
        actor_role: str,
        resource_id: UUID | None = None,
    ) -> dict:
        now = datetime.now(UTC)
        change = {
            "action": action,
            "payload": payload or {},
            "requested_by": str(actor_id),
            "requested_role": actor_role,
            "requested_at": now.isoformat(),
        }
        with self.uow_factory() as uow:
            request = uow.session.scalar(
                select(ApprovalRequest)
                .where(
                    ApprovalRequest.resource_type == resource_type,
                    ApprovalRequest.resource_key == resource_key,
                    ApprovalRequest.status == "pending",
                )
                .with_for_update()
            )
            if request is None:
                request = ApprovalRequest(
                    resource_type=resource_type,
                    resource_key=resource_key,
                    resource_id=resource_id,
                    requested_by_user_id=actor_id,
                    last_requested_by_user_id=actor_id,
                    changes_json="[]",
                )
                uow.session.add(request)
            changes = json.loads(request.changes_json)
            changes.append(change)
            request.changes_json = json.dumps(changes, ensure_ascii=False, default=_json_default)
            request.last_requested_by_user_id = actor_id
            request.resource_id = request.resource_id or resource_id
            uow.commit()
            return _approval_payload(uow.session, request)

    def approvals(self, status: str = "pending") -> list[dict]:
        with self.uow_factory() as uow:
            rows = list(
                uow.session.scalars(
                    select(ApprovalRequest)
                    .where(ApprovalRequest.status == status)
                    .order_by(ApprovalRequest.updated_at.desc())
                )
            )
            return [_approval_payload(uow.session, item) for item in rows]

    def review(self, request_id: UUID, reviewer_id: UUID, decision: str, note: str) -> dict:
        if decision not in {"approved", "rejected"}:
            raise ValidationError("Approval decision is invalid.")
        with self.uow_factory() as uow:
            request = uow.session.scalar(
                select(ApprovalRequest).where(ApprovalRequest.id == request_id).with_for_update()
            )
            if request is None:
                raise NotFoundError("Approval request does not exist.")
            if request.status != "pending":
                raise ConflictError("This approval request has already been reviewed.")
            changes = json.loads(request.changes_json)

        target_id = request.resource_id
        if decision == "approved":
            target_id = self._apply_changes(request.resource_type, target_id, changes)

        with self.uow_factory() as uow:
            stored = uow.session.get(ApprovalRequest, request_id)
            if stored is None or stored.status != "pending":
                raise ConflictError("This approval request has already been reviewed.")
            stored.status = decision
            stored.resource_id = target_id
            stored.reviewed_by_user_id = reviewer_id
            stored.reviewed_at = datetime.now(UTC)
            stored.decision_note = note.strip() or None
            uow.commit()
            return _approval_payload(uow.session, stored)

    def _apply_changes(
        self, resource_type: str, target_id: UUID | None, changes: list[dict]
    ) -> UUID | None:
        creates = [item for item in changes if item["action"] == "create"]
        updates = [item for item in changes if item["action"] == "update"]
        content = [item for item in changes if item["action"] == "replace_content"]
        reorders = [item for item in changes if item["action"] == "reorder"]
        terminal = [
            item for item in changes if item["action"] in {"publish", "unpublish", "archive", "delete"}
        ]

        if creates:
            target_id = self._dispatch(resource_type, "create", target_id, creates[-1]["payload"])
        if updates:
            merged: dict = {}
            for item in updates:
                merged.update(item["payload"])
            target_id = self._dispatch(resource_type, "update", target_id, merged)
        if content:
            target_id = self._dispatch(
                resource_type, "replace_content", target_id, content[-1]["payload"]
            )
        if reorders:
            self._dispatch(resource_type, "reorder", target_id, reorders[-1]["payload"])
        if terminal:
            target_id = self._dispatch(resource_type, terminal[-1]["action"], target_id, {})
        return target_id

    def _dispatch(
        self, resource_type: str, action: str, target_id: UUID | None, payload: dict
    ) -> UUID | None:
        if resource_type == "course":
            from app.services.academy import academy_service_from_container

            service = academy_service_from_container(self.container)
            payload = _restore_payload(resource_type, payload)
            if action == "create":
                values = dict(payload)
                content = values.pop("_content", None)
                publish_after_create = values.pop("_publish", False)
                result = service.create_course(
                    values, owner_user_id=UUID(str(values.pop("_owner_id")))
                )
                course_id = UUID(result["id"])
                if content:
                    service.replace_content(course_id, content)
                if publish_after_create:
                    service.publish(course_id)
                return course_id
            if action == "reorder":
                service.reorder(payload["course_ids"])
                return target_id
            _require_target(target_id)
            if action == "update":
                service.update_course(target_id, payload)
            elif action == "replace_content":
                service.replace_content(target_id, payload)
            elif action == "publish":
                service.publish(target_id)
            elif action == "unpublish":
                service.unpublish(target_id)
            elif action == "archive":
                service.archive(target_id)
            return target_id

        if resource_type == "product":
            from app.services.catalog import catalog_service_from_container

            service = catalog_service_from_container(self.container)
            payload = _restore_payload(resource_type, payload)
            if action == "create":
                return UUID(service.create_product(payload)["id"])
            _require_target(target_id)
            if action == "update":
                service.update_product(target_id, payload)
            elif action == "publish":
                service.publish_product(target_id, True)
            elif action == "unpublish":
                service.publish_product(target_id, False)
            elif action == "archive":
                service.archive_product(target_id)
            return target_id

        if resource_type == "product_category":
            from app.services.catalog import catalog_service_from_container

            service = catalog_service_from_container(self.container)
            if action == "create":
                return UUID(service.create_category(payload)["id"])
            _require_target(target_id)
            if action == "archive":
                service.archive_category(target_id)
            return target_id

        if resource_type == "event":
            from app.services.events import event_service_from_container

            service = event_service_from_container(self.container)
            payload = _restore_payload(resource_type, payload)
            if action == "create":
                return UUID(service.create(payload)["id"])
            _require_target(target_id)
            if action == "update":
                service.update(target_id, payload)
            elif action == "publish":
                service.publish(target_id, True)
            elif action == "unpublish":
                service.publish(target_id, False)
            elif action == "archive":
                service.archive(target_id)
            return target_id

        if resource_type == "partner":
            from app.services.content import content_service_from_container

            service = content_service_from_container(self.container)
            payload = _restore_payload(resource_type, payload)
            if action == "create":
                return UUID(service.create_partner(payload)["id"])
            _require_target(target_id)
            if action == "update":
                service.update_partner(target_id, payload)
            elif action == "publish":
                service.publish_partner(target_id, True)
            elif action == "unpublish":
                service.publish_partner(target_id, False)
            elif action == "archive":
                service.archive_partner(target_id)
            return target_id

        if resource_type == "blog":
            if action == "create":
                values = dict(payload)
                return UUID(self.create_blog(values, UUID(str(values.pop("_author_id"))))["id"])
            _require_target(target_id)
            if action == "update":
                self.update_blog(target_id, payload)
            elif action == "publish":
                self.publish_blog(target_id, True)
            elif action == "unpublish":
                self.publish_blog(target_id, False)
            elif action == "archive":
                self.archive_blog(target_id)
            elif action == "delete":
                self.delete_blog(target_id)
            return target_id

        raise ValidationError("This approval resource type is not supported.")

    def blogs(self, locale: str, *, admin: bool = False, category: str | None = None) -> list[dict]:
        with self.uow_factory() as uow:
            query = (
                select(BlogPost)
                .options(selectinload(BlogPost.translations))
                .where(BlogPost.archived_at.is_(None))
                .order_by(BlogPost.created_at.desc())
            )
            if not admin:
                query = query.where(BlogPost.published_at.is_not(None))
            if category:
                query = query.where(BlogPost.category == category)
            return [_blog_payload(item, locale, admin=admin) for item in uow.session.scalars(query)]

    def blog(self, slug: str, locale: str) -> dict:
        with self.uow_factory() as uow:
            post = uow.session.scalar(
                select(BlogPost)
                .options(selectinload(BlogPost.translations))
                .where(
                    BlogPost.slug == slug,
                    BlogPost.published_at.is_not(None),
                    BlogPost.archived_at.is_(None),
                )
            )
            if post is None:
                raise NotFoundError("Blog post does not exist.")
            return _blog_payload(post, locale)

    def create_blog(self, data: dict, author_id: UUID) -> dict:
        with self.uow_factory() as uow:
            if uow.session.scalar(select(BlogPost.id).where(BlogPost.slug == data["slug"])):
                raise ConflictError("Blog slug already exists.")
            post = BlogPost(
                slug=data["slug"],
                author_user_id=author_id,
                cover_url=data.get("cover_url"),
                category=data.get("category", "blog"),
                cover_alt=data.get("cover_alt", ""),
            )
            post.translations = [BlogPostTranslation(**item) for item in data["translations"]]
            uow.session.add(post)
            uow.commit()
            return _blog_payload(post, "en", admin=True)

    def update_blog(self, post_id: UUID, data: dict) -> dict:
        with self.uow_factory() as uow:
            post = uow.session.scalar(
                select(BlogPost)
                .options(selectinload(BlogPost.translations))
                .where(BlogPost.id == post_id, BlogPost.archived_at.is_(None))
            )
            if post is None:
                raise NotFoundError("Blog post does not exist.")
            if "slug" in data:
                post.slug = data["slug"]
            if "cover_url" in data:
                post.cover_url = data["cover_url"]
            if "category" in data:
                post.category = data["category"]
            if "cover_alt" in data:
                post.cover_alt = data["cover_alt"]
            if "translations" in data:
                existing = {item.locale: item for item in post.translations}
                for values in data["translations"]:
                    translation = existing.get(values["locale"])
                    if translation is None:
                        post.translations.append(BlogPostTranslation(**values))
                        continue
                    translation.title = values["title"]
                    translation.excerpt = values.get("excerpt", "")
                    translation.body = values["body"]
                    translation.seo_title = values.get("seo_title", "")
                    translation.seo_description = values.get("seo_description", "")
                    translation.seo_keywords = values.get("seo_keywords", "")
            uow.commit()
            return _blog_payload(post, "en", admin=True)

    def publish_blog(self, post_id: UUID, published: bool) -> dict:
        with self.uow_factory() as uow:
            post = uow.session.scalar(
                select(BlogPost)
                .options(selectinload(BlogPost.translations))
                .where(BlogPost.id == post_id, BlogPost.archived_at.is_(None))
            )
            if post is None:
                raise NotFoundError("Blog post does not exist.")
            post.published_at = datetime.now(UTC) if published else None
            uow.commit()
            return _blog_payload(post, "en", admin=True)

    def archive_blog(self, post_id: UUID) -> None:
        with self.uow_factory() as uow:
            post = uow.session.get(BlogPost, post_id)
            if post is not None:
                post.archived_at = post.archived_at or datetime.now(UTC)
                post.published_at = None
                uow.commit()

    def delete_blog(self, post_id: UUID) -> None:
        with self.uow_factory() as uow:
            post = uow.session.get(BlogPost, post_id)
            if post is None:
                raise NotFoundError("Blog post does not exist.")
            uow.session.delete(post)
            uow.commit()

    def settings(self) -> dict:
        result = dict(DEFAULT_SETTINGS)
        with self.uow_factory() as uow:
            for item in uow.session.scalars(select(SiteSetting)):
                result[item.key] = json.loads(item.value_json)
        return result

    def save_settings(self, values: dict, actor_id: UUID) -> dict:
        unknown = set(values) - set(DEFAULT_SETTINGS)
        if unknown:
            raise ValidationError(f"Unknown settings: {', '.join(sorted(unknown))}.")
        now = datetime.now(UTC)
        with self.uow_factory() as uow:
            for key, value in values.items():
                item = uow.session.get(SiteSetting, key)
                if item is None:
                    item = SiteSetting(
                        key=key,
                        value_json="null",
                        updated_at=now,
                        updated_by_user_id=actor_id,
                    )
                    uow.session.add(item)
                item.value_json = json.dumps(value, ensure_ascii=False)
                item.updated_at = now
                item.updated_by_user_id = actor_id
            uow.commit()
        return self.settings()


def _approval_payload(session, request: ApprovalRequest) -> dict:  # type: ignore[no-untyped-def]
    requester = session.get(User, request.last_requested_by_user_id)
    reviewer = (
        session.get(User, request.reviewed_by_user_id) if request.reviewed_by_user_id else None
    )
    changes = json.loads(request.changes_json)
    for change in changes:
        actor = (
            session.get(User, UUID(change["requested_by"])) if change.get("requested_by") else None
        )
        change["requester_name"] = actor.display_name if actor else None
    return {
        "id": str(request.id),
        "resource_type": request.resource_type,
        "resource_key": request.resource_key,
        "resource_id": str(request.resource_id) if request.resource_id else None,
        "status": request.status,
        "requester": {
            "id": str(requester.id),
            "name": requester.display_name,
            "role": requester.role,
        }
        if requester
        else None,
        "reviewer": {"id": str(reviewer.id), "name": reviewer.display_name} if reviewer else None,
        "changes": changes,
        "change_count": len(changes),
        "decision_note": request.decision_note,
        "created_at": request.created_at.isoformat(),
        "updated_at": request.updated_at.isoformat(),
        "reviewed_at": request.reviewed_at.isoformat() if request.reviewed_at else None,
    }


def _blog_payload(post: BlogPost, locale: str, *, admin: bool = False) -> dict:
    translation = next((item for item in post.translations if item.locale == locale), None)
    translation = translation or next(
        (item for item in post.translations if item.locale == "en"), None
    )
    payload = {
        "id": str(post.id),
        "slug": post.slug,
        "author_user_id": str(post.author_user_id),
        "cover_url": post.cover_url,
        "category": post.category,
        "cover_alt": post.cover_alt,
        "published": post.published_at is not None,
        "created_at": post.created_at.isoformat(),
        "title": translation.title if translation else "",
        "excerpt": translation.excerpt if translation else "",
        "body": translation.body if translation else "",
        "seo_title": translation.seo_title if translation else "",
        "seo_description": translation.seo_description if translation else "",
        "seo_keywords": translation.seo_keywords if translation else "",
    }
    if admin:
        payload["translations"] = [
            {
                "locale": item.locale,
                "title": item.title,
                "excerpt": item.excerpt,
                "body": item.body,
                "seo_title": item.seo_title,
                "seo_description": item.seo_description,
                "seo_keywords": item.seo_keywords,
            }
            for item in post.translations
        ]
    return payload


def _require_target(target_id: UUID | None) -> None:
    if target_id is None:
        raise ValidationError("Approval target is missing.")


def _json_default(value):  # type: ignore[no-untyped-def]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    raise TypeError(f"{type(value).__name__} is not JSON serializable")


def _restore_payload(resource_type: str, payload: dict) -> dict:
    values = dict(payload)
    if resource_type == "course" and values.get("instructor_partner_id"):
        values["instructor_partner_id"] = UUID(str(values["instructor_partner_id"]))
    elif resource_type == "product":
        for item in values.get("media", []):
            if item.get("stored_file_id"):
                item["stored_file_id"] = UUID(str(item["stored_file_id"]))
    elif resource_type == "event":
        for key in ("starts_at", "ends_at"):
            if isinstance(values.get(key), str):
                values[key] = datetime.fromisoformat(values[key])
        for item in values.get("speakers", []):
            if item.get("user_id"):
                item["user_id"] = UUID(str(item["user_id"]))
    elif resource_type == "partner":
        for key in ("user_id", "image_file_id"):
            if values.get(key):
                values[key] = UUID(str(values[key]))
    return values


def governance_service_from_container(  # type: ignore[no-untyped-def]
    container,
) -> GovernanceService:
    return GovernanceService(container)
