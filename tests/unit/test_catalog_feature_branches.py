from __future__ import annotations

from datetime import datetime
from io import BytesIO
from uuid import UUID, uuid4

import pytest
from werkzeug.datastructures import FileStorage

from app.core.auth_models import EmailIdentity, User, UserProfile
from app.core.unit_of_work import SqlAlchemyUnitOfWork
from app.domain.catalog import (
    validate_prices,
    validate_slug,
    validate_translations,
    validate_youtube_playlist_id,
)
from app.domain.errors import ConflictError, NotFoundError, ValidationError
from app.services.catalog import catalog_service_from_container
from app.services.events import event_service_from_container
from app.services.files import LocalFileService, _matches_signature
from app.services.seed import seed_catalog_and_events


def _category() -> dict:
    return {
        "slug": "test-devices",
        "translations": [
            {"locale": "en", "title": "Test devices"},
            {"locale": "fa", "title": "تجهیزات تست"},
        ],
    }


def _product(slug: str, mode: str = "direct", category_slug: str = "test-devices") -> dict:
    return {
        "slug": slug,
        "sku": slug.upper(),
        "category_slug": category_slug,
        "sale_mode": mode,
        "stock_quantity": 3 if mode == "direct" else None,
        "translations": [
            {
                "locale": "en",
                "name": slug,
                "short_description": "Short",
                "description": "Description",
            },
            {
                "locale": "fa",
                "name": f"{slug} فارسی",
                "short_description": "کوتاه",
                "description": "توضیحات",
            },
        ],
        "prices": [{"currency": "IRR", "amount_minor": 1000}] if mode == "direct" else [],
        "media": [],
    }


def _event(slug: str, user_id: UUID | None = None) -> dict:
    data = {
        "slug": slug,
        "kind": "online",
        "status": "upcoming",
        "starts_at": datetime.fromisoformat("2027-02-01T10:00:00+03:30"),
        "ends_at": datetime.fromisoformat("2027-02-01T11:00:00+03:30"),
        "capacity": 1,
        "online_url": "https://example.com/live",
        "venue": None,
        "translations": [
            {
                "locale": "en",
                "title": slug,
                "summary": "Summary",
                "description": "Description",
                "host_label": "Host",
            },
            {
                "locale": "fa",
                "title": f"{slug} فارسی",
                "summary": "خلاصه",
                "description": "توضیح",
                "host_label": "میزبان",
            },
        ],
        "speakers": [],
    }
    if user_id:
        data["speakers"] = [{"user_id": user_id, "role_label": "Speaker", "position": 1}]
    return data


def _user(container, name: str) -> UUID:  # type: ignore[no-untyped-def]
    with container.database.session() as session:
        user = User(display_name=name, role="user", status="active")
        session.add(user)
        session.flush()
        user.emails.append(EmailIdentity(email=f"{user.id}@example.com",
            verified_at=datetime.now().astimezone()))
        session.add(
            UserProfile(
                user_id=user.id,
                full_name=name,
                email=f"{user.id}@example.com",
                phone="+989121234567",
            )
        )
        session.commit()
        return user.id


def test_catalog_domain_and_file_signature_branches() -> None:
    with pytest.raises(ValidationError):
        validate_slug("Bad Slug")
    with pytest.raises(ValidationError):
        validate_translations([{"locale": "en"}])
    with pytest.raises(ValidationError):
        validate_prices("other", [])
    with pytest.raises(ValidationError):
        validate_prices("direct", [{"currency": "EUR", "amount_minor": 1}])
    with pytest.raises(ValidationError):
        validate_prices(
            "direct",
            [
                {"currency": "IRR", "amount_minor": 1},
                {"currency": "IRR", "amount_minor": 2},
            ],
        )
    with pytest.raises(ValidationError):
        validate_prices("direct", [{"currency": "IRR", "amount_minor": -1}])
    with pytest.raises(ValidationError):
        validate_prices("direct", [])
    with pytest.raises(ValidationError):
        validate_prices("inquiry", [{"currency": "IRR", "amount_minor": 1}])
    assert validate_youtube_playlist_id(None) is None
    assert validate_youtube_playlist_id("  ") is None
    with pytest.raises(ValidationError):
        validate_youtube_playlist_id("bad id")

    assert _matches_signature(".jpg", b"\xff\xd8\xffrest")
    assert _matches_signature(".jpeg", b"\xff\xd8\xffrest")
    assert _matches_signature(".gif", b"GIF87arest")
    assert _matches_signature(".gif", b"GIF89arest")
    assert _matches_signature(".webp", b"RIFF0000WEBPrest")
    assert _matches_signature(".pdf", b"%PDF-1.7")
    assert _matches_signature(".woff", b"wOFFrest")
    assert _matches_signature(".woff2", b"wOF2rest")
    assert _matches_signature(".txt", b"plain text")
    assert not _matches_signature(".txt", b"MZ executable")
    assert not _matches_signature(".txt", b"a\x00b")
    assert not _matches_signature(".unknown", b"anything")


def test_catalog_service_validation_and_state_branches(app) -> None:  # type: ignore[no-untyped-def]
    container = app.extensions["container"]
    service = catalog_service_from_container(container)
    user_id = _user(container, "Buyer")

    category_slug = service.create_category(_category())["slug"]
    with pytest.raises(ConflictError):
        service.create_category(_category())
    bad_stock = _product("bad-stock", category_slug=category_slug)
    bad_stock["stock_quantity"] = None
    with pytest.raises(ValidationError):
        service.create_product(bad_stock)
    missing_category = _product("missing-category")
    missing_category["category_slug"] = "missing"
    with pytest.raises(ValidationError):
        service.create_product(missing_category)
    bad_media = _product("bad-media", category_slug=category_slug)
    bad_media["media"] = [{"position": 0, "alt_text": "bad"}]
    with pytest.raises(ValidationError):
        service.create_product(bad_media)

    direct = service.create_product(_product("direct-device", category_slug=category_slug))
    inquiry = service.create_product(_product("inquiry-device", "inquiry", category_slug))
    direct_id, inquiry_id = UUID(direct["id"]), UUID(inquiry["id"])
    service.publish_product(direct_id, True)
    service.publish_product(inquiry_id, True)
    assert service.products("en", None, 1, 10)[1] == 2
    assert service.product(direct["slug"], "en", admin=True)["sku"] == "DIRECT-DEVICE"
    with pytest.raises(NotFoundError):
        service.product("unknown", "en")
    with pytest.raises(ConflictError):
        service.create_product(_product("direct-device", category_slug=category_slug))
    with pytest.raises(NotFoundError):
        service.update_product(uuid4(), {})
    with pytest.raises(ValidationError):
        service.update_product(direct_id, {"category_slug": "missing"})
    with pytest.raises(ConflictError):
        service.update_product(direct_id, {"sku": "INQUIRY-DEVICE"})
    with pytest.raises(ValidationError):
        service.update_product(
            inquiry_id,
            {
                "sale_mode": "direct",
                "stock_quantity": None,
                "prices": [{"currency": "IRR", "amount_minor": 1}],
            },
        )
    translations_without_description = _product("unused")["translations"]
    for item in translations_without_description:
        item.pop("description")
        item["details"] = {"overviewBody": "Overview supplied by the product editor"}
    updated = service.update_product(
        direct_id,
        {
            "sku": "DIRECT-UPDATED",
            "translations": translations_without_description,
            "prices": [{"currency": "USD", "amount_minor": 200}],
            "media": [
                {
                    "external_url": "https://example.com/device.png",
                    "alt_text": "Device",
                    "position": 1,
                }
            ],
        },
    )
    assert updated["sku"] == "DIRECT-UPDATED"
    assert updated["description"] == "Overview supplied by the product editor"
    with pytest.raises(ValidationError):
        service.update_product(direct_id, {"media": [{"position": 1}]})
    with pytest.raises(NotFoundError):
        service.publish_product(uuid4(), True)
    service.archive_product(uuid4())

    assert service.cart(user_id)["items"] == []
    with pytest.raises(ValidationError):
        service.set_cart_item(user_id, direct_id, 0)
    with pytest.raises(NotFoundError):
        service.set_cart_item(user_id, uuid4(), 1)
    with pytest.raises(ValidationError):
        service.set_cart_item(user_id, inquiry_id, 1)
    with pytest.raises(ConflictError):
        service.set_cart_item(user_id, direct_id, 99)
    service.set_cart_item(user_id, direct_id, 1)
    service.set_cart_item(user_id, direct_id, 2)
    service.remove_cart_item(user_id, inquiry_id)
    service.remove_cart_item(user_id, direct_id)
    with pytest.raises(ValidationError):
        service.create_product_order(user_id, "EUR", {})
    empty_user_id = _user(container, "Empty cart buyer")
    with pytest.raises(ValidationError):
        service.create_product_order(empty_user_id, "USD", {})
    with pytest.raises(ValidationError):
        service.create_product_order(user_id, "USD", {})

    with pytest.raises(ValidationError):
        service.create_inquiry("inquiry-device", {"message": "x"}, None)
    inquiry_data = {
        "name": "Customer",
        "email": "customer@example.com",
        "phone": None,
        "quantity": 1,
        "message": "A valid inquiry",
    }
    with pytest.raises(NotFoundError):
        service.create_inquiry("missing", inquiry_data, None)
    with pytest.raises(ValidationError):
        service.create_inquiry(updated["slug"], inquiry_data, None)
    invalid_email = {**inquiry_data, "email": "invalid"}
    with pytest.raises(ValidationError):
        service.create_inquiry(inquiry["slug"], invalid_email, None)
    created_inquiry = service.create_inquiry(inquiry["slug"], inquiry_data, None)
    assert len(service.inquiries()) == 1
    with pytest.raises(ValidationError):
        service.inquiries("unknown")
    with pytest.raises(ValidationError):
        service.respond_inquiry(UUID(created_inquiry["id"]), user_id, "pending", None)
    with pytest.raises(NotFoundError):
        service.respond_inquiry(uuid4(), user_id, "answered", None)

    with pytest.raises(NotFoundError):
        service.product_order(user_id, uuid4())
    with pytest.raises(ValidationError):
        service.product_payment(uuid4(), "invalid")
    with pytest.raises(NotFoundError):
        service.product_payment(uuid4(), "cancel")


def test_catalog_order_cancel_idempotency_and_seed(app) -> None:  # type: ignore[no-untyped-def]
    container = app.extensions["container"]
    service = catalog_service_from_container(container)
    user_id = _user(container, "Paying buyer")
    category_slug = service.create_category(_category())["slug"]
    product = service.create_product(_product("payable-device", category_slug=category_slug))
    product_id = UUID(product["id"])
    service.publish_product(product_id, True)
    service.set_cart_item(user_id, product_id, 1)
    order = service.create_product_order(
        user_id,
        "IRR",
        {"address": "Tehran", "city": "Tehran", "postal_code": "1234567890"},
    )
    attempt_id = UUID(order["payment_url"].rsplit("/", 1)[-1])
    assert service.product_payment(attempt_id, "cancel")["status"] == "cancelled"
    assert service.product_payment(attempt_id, "cancel")["status"] == "cancelled"

    product_count, event_count = seed_catalog_and_events(container)
    assert (product_count, event_count) == (2, 1)
    assert seed_catalog_and_events(container) == (0, 0)


def test_event_service_validation_capacity_and_profile_links(app) -> None:  # type: ignore[no-untyped-def]
    container = app.extensions["container"]
    service = event_service_from_container(container)
    first = _user(container, "First speaker")
    second = _user(container, "Second attendee")
    third = _user(container, "Third attendee")

    with pytest.raises(ValidationError):
        service.list("en", kind="hybrid")
    with pytest.raises(ValidationError):
        service.list("en", status="draft")
    for change in (
        {"kind": "hybrid"},
        {"status": "draft"},
        {"ends_at": _event("x")["starts_at"]},
        {"capacity": 0},
        {"status": "live", "online_url": None},
        {"kind": "onsite", "online_url": None, "venue": None},
    ):
        payload = {**_event(f"bad-event-{len(change)}"), **change}
        with pytest.raises(ValidationError):
            service.create(payload)

    payload = _event("profile-event", first)
    created = service.create(payload)
    event_id = UUID(created["id"])
    assert service.detail("profile-event", "de", admin=True)["speakers"][0]["name"]
    with pytest.raises(ConflictError):
        service.create(payload)
    with pytest.raises(NotFoundError):
        service.detail("missing", "en")
    with pytest.raises(NotFoundError):
        service.update(uuid4(), {})
    with pytest.raises(ValidationError):
        service.update(
            event_id,
            {
                "speakers": [
                    {"user_id": first, "role_label": "One", "position": 1},
                    {"user_id": first, "role_label": "Two", "position": 2},
                ]
            },
        )
    with pytest.raises(ValidationError):
        service.update(
            event_id,
            {"speakers": [{"user_id": uuid4(), "role_label": "Missing", "position": 1}]},
        )
    service.update(
        event_id,
        {"speakers": [{"user_id": second, "role_label": "Moderator", "position": 1}]},
    )
    with pytest.raises(NotFoundError):
        service.publish(uuid4(), True)
    service.publish(event_id, True)
    def confirm(user_id):
        assert service.reserve(user_id, "profile-event")["status"] == "pending_email"
        token = container.email_sender.sent_messages[-1].body.split("token=", 1)[1].splitlines()[0]
        return service.confirm_reservation(token)

    assert confirm(first)["status"] == "confirmed"
    with pytest.raises(ConflictError):
        service.reserve(second, "profile-event")
    service.cancel(first, "profile-event")
    assert confirm(second)["status"] == "confirmed"
    with pytest.raises(ConflictError):
        service.reserve(first, "profile-event")
    service.cancel(third, "profile-event")
    with pytest.raises(NotFoundError):
        service.reserve(first, "missing")
    service.update(event_id, {"status": "completed"})
    with pytest.raises(ConflictError):
        service.reserve(third, "profile-event")
    service.archive(uuid4())


def test_local_file_service_input_validation(app, tmp_path) -> None:  # type: ignore[no-untyped-def]
    container = app.extensions["container"]
    user_id = _user(container, "Uploader")
    service = LocalFileService(
        lambda: SqlAlchemyUnitOfWork(container.database.session_factory),
        tmp_path / "files",
    )
    for upload in (
        FileStorage(stream=BytesIO(b"x"), filename="", content_type="text/plain"),
        FileStorage(
            stream=BytesIO(b"x"), filename="tool.exe", content_type="application/octet-stream"
        ),
        FileStorage(stream=BytesIO(b"x"), filename="note.txt", content_type="image/png"),
        FileStorage(stream=BytesIO(b""), filename="note.txt", content_type="text/plain"),
    ):
        with pytest.raises(ValidationError):
            service.save(user_id, upload, is_public=True)
    private = service.save(
        user_id,
        FileStorage(stream=BytesIO(b"plain text"), filename="note.txt", content_type="text/plain"),
        is_public=False,
    )
    with pytest.raises(NotFoundError):
        service.resolve_public(UUID(private["id"]))
    with pytest.raises(NotFoundError):
        service.delete(uuid4())
