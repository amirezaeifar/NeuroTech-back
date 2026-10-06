from __future__ import annotations

from io import BytesIO

from app.services.auth import auth_service_from_container

PASSWORD = "secure-pass-123"


def _admin(client, app):  # type: ignore[no-untyped-def]
    auth_service_from_container(app.extensions["container"]).bootstrap_admin(
        "Admin", "catalog-admin@example.com", PASSWORD
    )
    response = client.post(
        "/api/v1/auth/login/password",
        json={"email": "catalog-admin@example.com", "password": PASSWORD},
    )
    assert response.status_code == 200
    return {"X-CSRF-TOKEN": client.get_cookie("csrf_access_token").value}


def _translations(name: str) -> list[dict]:
    return [
        {
            "locale": "en",
            "name": name,
            "short_description": f"{name} short description",
            "description": f"{name} long description",
        },
        {
            "locale": "fa",
            "name": f"{name} فارسی",
            "short_description": "توضیح کوتاه محصول",
            "description": "توضیح کامل محصول",
        },
    ]


def _category(client, headers) -> str:  # type: ignore[no-untyped-def]
    response = client.post(
        "/api/v1/admin/product-categories",
        headers=headers,
        json={
            "slug": "devices",
            "position": 1,
            "translations": [
                {"locale": "en", "title": "Devices"},
                {"locale": "fa", "title": "تجهیزات"},
            ],
        },
    )
    assert response.status_code == 201
    return response.get_json()["data"]["slug"]


def _product(client, headers, *, slug: str, sale_mode: str, category_slug: str) -> dict:  # type: ignore[no-untyped-def]
    payload = {
        "slug": slug,
        "sku": slug.upper(),
        "category_slug": category_slug,
        "sale_mode": sale_mode,
        "stock_quantity": 5 if sale_mode == "direct" else None,
        "translations": _translations(slug),
        "prices": (
            [{"currency": "IRR", "amount_minor": 2_500_000}] if sale_mode == "direct" else []
        ),
        "media": [
            {
                "external_url": "https://example.com/product.webp",
                "alt_text": slug,
                "position": 0,
            }
        ],
    }
    created = client.post("/api/v1/admin/products", headers=headers, json=payload)
    assert created.status_code == 201
    product = created.get_json()["data"]
    published = client.post(f"/api/v1/admin/products/{product['id']}/publish", headers=headers)
    assert published.status_code == 200
    return product


def test_direct_product_catalog_cart_order_and_fake_payment(client, app) -> None:  # type: ignore[no-untyped-def]
    headers = _admin(client, app)
    category_slug = _category(client, headers)
    product = _product(
        client, headers, slug="neural-device", sale_mode="direct", category_slug=category_slug
    )

    listing = client.get(f"/api/v1/products?locale=fa&category={category_slug}")
    assert listing.status_code == 200
    assert listing.get_json()["data"][0]["name"] == "neural-device فارسی"
    assert client.get("/api/v1/product-categories?locale=en").status_code == 200
    assert client.get(f"/api/v1/products/{product['slug']}?locale=en").status_code == 200
    assert client.get("/api/v1/admin/products").status_code == 200

    updated = client.patch(
        f"/api/v1/admin/products/{product['id']}",
        headers=headers,
        json={"stock_quantity": 4},
    )
    assert updated.get_json()["data"]["stock_quantity"] == 4
    cart = client.put(
        f"/api/v1/cart/items/{product['id']}",
        headers=headers,
        json={"quantity": 2},
    )
    assert cart.status_code == 200
    assert client.get("/api/v1/cart?locale=en").get_json()["data"]["items"][0]["quantity"] == 2

    profile = client.put(
        "/api/v1/me/profile",
        headers=headers,
        json={
            "full_name": "Test Admin",
            "email": "catalog-admin@example.com",
            "phone": "+989121234567",
        },
    )
    assert profile.status_code == 200

    order = client.post(
        "/api/v1/product-orders",
        headers=headers,
        json={
            "currency": "IRR",
            "shipping_address": {
                "recipient": "Test Admin",
                "address": "Tehran, Test street",
                "phone": "+989121234567",
            },
        },
    )
    assert order.status_code == 201
    order_data = order.get_json()["data"]
    assert order_data["total_minor"] == 5_000_000
    assert order_data["fulfillment_status"] == "awaiting_payment"
    pending_orders = client.get("/api/v1/admin/orders?payment_status=pending")
    assert pending_orders.get_json()["data"][0]["id"] == order_data["id"]
    attempt_id = order_data["payment_url"].rsplit("/", 1)[-1]
    payment = client.post(
        f"/api/v1/product-payments/fake/{attempt_id}/callback",
        json={"result": "success"},
    )
    assert payment.get_json()["data"]["status"] == "paid"
    saved = client.get(f"/api/v1/product-orders/{order_data['id']}")
    assert saved.get_json()["data"]["items"][0]["quantity"] == 2
    assert saved.get_json()["data"]["fulfillment_status"] == "awaiting_confirmation"

    admin_orders = client.get("/api/v1/admin/orders?kind=product")
    assert admin_orders.status_code == 200
    listed = admin_orders.get_json()["data"][0]
    assert listed["id"] == order_data["id"]
    assert listed["payment_status"] == "paid"
    assert listed["fulfillment_status"] == "awaiting_confirmation"
    assert listed["customer"]["email"] == "catalog-admin@example.com"
    assert listed["shipping_address"]["address"] == "Tehran, Test street"
    assert admin_orders.get_json()["meta"]["payment_counts"]["paid"] == 1

    skipped = client.patch(
        f"/api/v1/admin/orders/products/{order_data['id']}/fulfillment",
        headers=headers,
        json={"status": "shipped"},
    )
    assert skipped.status_code == 409
    for next_status in ("confirmed", "shipped", "closed"):
        advanced = client.patch(
            f"/api/v1/admin/orders/products/{order_data['id']}/fulfillment",
            headers=headers,
            json={"status": next_status},
        )
        assert advanced.status_code == 200
        assert advanced.get_json()["data"]["fulfillment_status"] == next_status

    client.put(
        f"/api/v1/cart/items/{product['id']}",
        headers=headers,
        json={"quantity": 1},
    )
    failed_order = client.post(
        "/api/v1/product-orders",
        headers=headers,
        json={
            "currency": "IRR",
            "shipping_address": {
                "recipient": "Test Admin",
                "address": "Tehran, Test street",
                "phone": "+989121234567",
            },
        },
    ).get_json()["data"]
    failed_attempt = failed_order["payment_url"].rsplit("/", 1)[-1]
    client.post(
        f"/api/v1/product-payments/fake/{failed_attempt}/callback",
        json={"result": "failure"},
    )
    failed_orders = client.get("/api/v1/admin/orders?payment_status=failed").get_json()
    assert failed_orders["data"][0]["id"] == failed_order["id"]
    assert failed_orders["meta"]["payment_counts"]["paid"] == 1
    assert failed_orders["meta"]["payment_counts"]["failed"] == 1


def test_inquiry_product_rejects_cart_and_supports_admin_response(client, app) -> None:  # type: ignore[no-untyped-def]
    headers = _admin(client, app)
    category_slug = _category(client, headers)
    product = _product(
        client, headers, slug="custom-electrode", sale_mode="inquiry", category_slug=category_slug
    )

    rejected_cart = client.put(
        f"/api/v1/cart/items/{product['id']}",
        headers=headers,
        json={"quantity": 1},
    )
    assert rejected_cart.status_code == 422
    inquiry = client.post(
        f"/api/v1/products/{product['slug']}/inquiries",
        headers=headers,
        json={
            "name": "Customer",
            "email": "CUSTOMER@example.com",
            "phone": "+989121234567",
            "quantity": 20,
            "message": "Please send a quotation.",
        },
    )
    assert inquiry.status_code == 201
    inquiry_data = inquiry.get_json()["data"]
    assert inquiry_data["status"] == "pending"
    pending = client.get("/api/v1/admin/product-inquiries?status=pending")
    assert pending.get_json()["data"][0]["id"] == inquiry_data["id"]
    answered = client.patch(
        f"/api/v1/admin/product-inquiries/{inquiry_data['id']}",
        headers=headers,
        json={"status": "answered", "response": "Quotation sent."},
    )
    assert answered.get_json()["data"]["status"] == "answered"
    category = next(
        item
        for item in client.get("/api/v1/admin/product-categories").get_json()["data"]
        if item["slug"] == category_slug
    )
    assert (
        client.delete(
            f"/api/v1/admin/product-categories/{category['id']}", headers=headers
        ).status_code
        == 409
    )
    assert (
        client.post(
            f"/api/v1/admin/products/{product['id']}/unpublish", headers=headers
        ).status_code
        == 200
    )
    assert (
        client.delete(f"/api/v1/admin/products/{product['id']}", headers=headers).status_code == 204
    )
    assert (
        client.delete(
            f"/api/v1/admin/product-categories/{category['id']}", headers=headers
        ).status_code
        == 204
    )


def test_local_upload_serves_allowed_image_and_video(client, app) -> None:  # type: ignore[no-untyped-def]
    headers = _admin(client, app)
    uploaded = client.post(
        "/api/v1/admin/files",
        headers=headers,
        data={
            "file": (
                BytesIO(b"\x89PNG\r\n\x1a\nsmall-image-content"),
                "cover.png",
                "image/png",
            ),
            "is_public": "true",
        },
        content_type="multipart/form-data",
    )
    assert uploaded.status_code == 201
    file_data = uploaded.get_json()["data"]
    served = client.get(file_data["url"])
    assert served.status_code == 200
    assert served.data == b"\x89PNG\r\n\x1a\nsmall-image-content"
    served.close()
    downloaded = client.get(f'{file_data["url"]}?download=1')
    assert downloaded.status_code == 200
    assert downloaded.headers["Content-Disposition"].startswith("attachment;")
    downloaded.close()

    video = client.post(
        "/api/v1/admin/files",
        headers=headers,
        data={"file": (BytesIO(b"\x00\x00\x00\x18ftypmp42video"), "lesson.mp4", "video/mp4")},
        content_type="multipart/form-data",
    )
    assert video.status_code == 201
    disguised = client.post(
        "/api/v1/admin/files",
        headers=headers,
        data={"file": (BytesIO(b"MZ executable"), "fake.png", "image/png")},
        content_type="multipart/form-data",
    )
    assert disguised.status_code == 422
    assert (
        client.delete(f"/api/v1/admin/files/{file_data['id']}", headers=headers).status_code == 204
    )
    assert (
        client.delete(
            f"/api/v1/admin/files/{video.get_json()['data']['id']}", headers=headers
        ).status_code
        == 204
    )
    assert client.get(file_data["url"]).status_code == 404


def _event_payload() -> dict:
    return {
        "slug": "brain-health-day",
        "kind": "online",
        "status": "upcoming",
        "starts_at": "2027-01-10T09:00:00+03:30",
        "ends_at": "2027-01-10T11:00:00+03:30",
        "timezone": "Asia/Tehran",
        "capacity": 1,
        "online_url": "https://meet.example.com/brain",
        "translations": [
            {
                "locale": "en",
                "title": "Brain Health Day",
                "summary": "An online neuroscience event.",
                "description": "A detailed event description.",
                "host_label": "Dr. Test",
            },
            {
                "locale": "fa",
                "title": "روز سلامت مغز",
                "summary": "رویداد آنلاین علوم اعصاب",
                "description": "توضیحات کامل رویداد",
                "host_label": "دکتر تست",
            },
        ],
    }


def test_event_crud_public_listing_reservation_and_cancel(client, app) -> None:  # type: ignore[no-untyped-def]
    headers = _admin(client, app)
    admin_id = client.get("/api/v1/me").get_json()["data"]["user"]["id"]
    payload = _event_payload()
    payload["speakers"] = [{"user_id": admin_id, "role_label": "Speaker", "position": 1}]
    created = client.post("/api/v1/admin/events", headers=headers, json=payload)
    assert created.status_code == 201
    event_id = created.get_json()["data"]["id"]
    assert client.get("/api/v1/admin/events").status_code == 200
    assert (
        client.post(f"/api/v1/admin/events/{event_id}/publish", headers=headers).status_code == 200
    )
    listing = client.get("/api/v1/events?locale=fa&kind=online&status=upcoming")
    assert listing.get_json()["data"][0]["title"] == "روز سلامت مغز"
    detail = client.get("/api/v1/events/brain-health-day?locale=en")
    assert detail.status_code == 200
    assert detail.get_json()["data"]["online_url"] is None
    assert detail.get_json()["data"]["speakers"][0]["profile_user_id"] == admin_id

    reservation = client.post("/api/v1/events/brain-health-day/reservations", headers=headers)
    assert reservation.status_code == 202
    assert reservation.get_json()["data"]["status"] == "pending_email"
    from tests.api.test_event_management import confirm_latest
    assert confirm_latest(client, app).status_code == 200
    assert (
        client.delete(
            "/api/v1/events/brain-health-day/reservations/me", headers=headers
        ).status_code
        == 204
    )
    assert (
        client.patch(
            f"/api/v1/admin/events/{event_id}",
            headers=headers,
            json={"status": "completed"},
        ).status_code
        == 200
    )
    assert (
        client.post(f"/api/v1/admin/events/{event_id}/unpublish", headers=headers).status_code
        == 200
    )
    assert client.delete(f"/api/v1/admin/events/{event_id}", headers=headers).status_code == 204
