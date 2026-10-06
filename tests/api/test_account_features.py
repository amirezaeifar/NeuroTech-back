from __future__ import annotations

from datetime import UTC, datetime, timedelta
from io import BytesIO
from uuid import uuid4

from sqlalchemy import select

from app.core.academy_models import Course
from app.core.auth_models import EmailIdentity, User
from app.core.catalog_models import Product, ProductCategory, ProductOrder, ProductOrderItem, ProductPaymentAttempt
from app.core.commerce_models import Order, OrderItem, PaymentAttempt
from app.core.content_models import PartnerProfile
from app.core.learning_models import CourseComment, Enrollment
from tests.api.test_auth import _login, _register_and_verify
from tests.api.test_governance import _staff


def _member(app):
    with app.extensions["container"].database.session() as session:
        return session.scalar(select(User).join(EmailIdentity).where(EmailIdentity.email == "member@example.com")).id


def test_account_pages_are_user_scoped_and_favorites_can_be_managed(client, app) -> None:
    _register_and_verify(client, app)
    _login(client)
    with app.extensions["container"].database.session() as session:
        version_before = session.get(User, _member(app)).version
    for _ in range(3):
        assert client.get("/api/v1/me").status_code == 200
    with app.extensions["container"].database.session() as session:
        assert session.get(User, _member(app)).version == version_before
    for path in ("courses", "orders", "payments", "favorites"):
        response = client.get(f"/api/v1/me/{path}")
        assert response.status_code == 200
        assert response.json["data"] == []

    member_id = _member(app)
    with app.extensions["container"].database.session() as session:
        course = Course(slug="favorite-course", tier="free", field="neurology", level="beginner")
        session.add(course)
        session.flush()
        enrollment = Enrollment(user_id=member_id, course_id=course.id, enrolled_at=datetime.now(UTC))
        order = Order(user_id=member_id, currency="IRR", total_minor=120000)
        session.add_all([enrollment, order])
        session.flush()
        session.add(OrderItem(order_id=order.id, course_id=course.id, title_snapshot="Favorite course", unit_amount_minor=120000))
        session.add(PaymentAttempt(order_id=order.id, provider="fake", provider_reference=uuid4().hex, redirect_url="https://example.com/pay"))
        session.commit()
        course_id = course.id

    with app.extensions["container"].database.session() as session:
        assert len(session.scalars(select(Enrollment)).all()) == 1
    assert client.get("/api/v1/me").json["data"]["user"]["id"] == str(member_id)
    courses_response = client.get("/api/v1/me/courses")
    assert courses_response.status_code == 200
    assert len(courses_response.json["data"]) == 1
    assert len(client.get("/api/v1/me/orders").json["data"]) == 1
    assert len(client.get("/api/v1/me/payments").json["data"]) == 1
    other_client = app.test_client()
    _register_and_verify(other_client, app, "other@example.com")
    _login(other_client, "other@example.com")
    for path in ("courses", "orders", "payments", "favorites"):
        assert other_client.get(f"/api/v1/me/{path}").json["data"] == []

    csrf = client.get_cookie("csrf_access_token").value
    headers = {"X-CSRF-TOKEN": csrf}
    added = client.post("/api/v1/me/favorites", json={"item_type": "course", "item_id": str(course_id)}, headers=headers)
    assert added.status_code == 201
    favorites = client.get("/api/v1/me/favorites").json["data"]
    assert favorites[0]["slug"] == "favorite-course"
    assert client.delete(f"/api/v1/me/favorites/{favorites[0]['id']}", headers=headers).status_code == 204
    assert client.get("/api/v1/me/favorites").json["data"] == []


def test_invoice_download_is_limited_to_paid_orders_owned_by_user(client, app) -> None:
    _register_and_verify(client, app)
    _login(client)
    member_id = _member(app)
    with app.extensions["container"].database.session() as session:
        course = Course(slug="invoice-course", tier="premium", field="neurology", level="beginner")
        category = ProductCategory(slug="invoice-products")
        session.add_all([course, category])
        session.flush()
        product = Product(category_id=category.id, slug="invoice-product", sku="invoice-1", sale_mode="direct")
        course_order = Order(user_id=member_id, currency="IRR", total_minor=120000, status="paid")
        product_order = ProductOrder(user_id=member_id, currency="IRR", total_minor=240000, status="paid", shipping_address={})
        session.add_all([product, course_order, product_order])
        session.flush()
        session.add_all([
            OrderItem(order_id=course_order.id, course_id=course.id, title_snapshot="Course invoice", unit_amount_minor=120000),
            ProductOrderItem(order_id=product_order.id, product_id=product.id, title_snapshot="Product invoice", quantity=2, unit_amount_minor=120000),
        ])
        course_payment = PaymentAttempt(order_id=course_order.id, provider="fake", provider_reference=uuid4().hex, redirect_url="https://example.com/pay", status="succeeded")
        product_payment = ProductPaymentAttempt(order_id=product_order.id, provider="fake", provider_reference=uuid4().hex, redirect_url="https://example.com/pay", status="succeeded")
        pending_payment = PaymentAttempt(order_id=course_order.id, provider="fake", provider_reference=uuid4().hex, redirect_url="https://example.com/pay")
        session.add_all([course_payment, product_payment, pending_payment])
        session.commit()
        course_payment_id, product_payment_id, pending_payment_id, product_id = course_payment.id, product_payment.id, pending_payment.id, product.id

    for payment_id, kind, item_name in ((course_payment_id, "course", "Course invoice"), (product_payment_id, "product", "Product invoice")):
        response = client.get(f"/api/v1/me/payments/{payment_id}/invoice?type={kind}")
        assert response.status_code == 200
        assert "attachment" in response.headers["Content-Disposition"]
        assert item_name in response.get_data(as_text=True)
        assert "Test Member" in response.get_data(as_text=True)
    assert client.get(f"/api/v1/me/payments/{pending_payment_id}/invoice?type=course").status_code == 404
    assert client.get(f"/api/v1/me/payments/{course_payment_id}/invoice?type=product").status_code == 404
    persian_invoice = client.get(f"/api/v1/me/payments/{course_payment_id}/invoice?type=course&locale=fa")
    assert 'dir="rtl"' in persian_invoice.get_data(as_text=True)
    assert "فاکتور پرداخت" in persian_invoice.get_data(as_text=True)
    product_favorite = client.post("/api/v1/me/favorites", json={"item_type": "product", "item_id": str(product_id)}, headers={"X-CSRF-TOKEN": client.get_cookie("csrf_access_token").value})
    assert product_favorite.status_code == 201
    assert client.get("/api/v1/me/favorites").json["data"][0]["item_id"] == str(product_id)

    other = app.test_client()
    _register_and_verify(other, app, "invoice-other@example.com")
    _login(other, "invoice-other@example.com")
    assert other.get(f"/api/v1/me/payments/{course_payment_id}/invoice?type=course").status_code == 404
    assert other.get(f"/api/v1/me/payments/{product_payment_id}/invoice?type=product").status_code == 404


def test_profile_edit_updates_visible_user_name(client, app) -> None:
    _register_and_verify(client, app)
    _login(client)
    headers = {"X-CSRF-TOKEN": client.get_cookie("csrf_access_token").value}
    response = client.put("/api/v1/me/profile", headers=headers, json={
        "full_name": "New Member Name", "email": "member@example.com", "phone": "",
        "national_id": "", "address": "Somewhere",
    })
    assert response.status_code == 200
    assert response.json["data"]["full_name"] == "New Member Name"
    assert client.get("/api/v1/me").json["data"]["user"]["display_name"] == "New Member Name"


def test_profile_photo_is_optional_private_and_removable(client, app) -> None:
    _register_and_verify(client, app)
    _login(client)
    assert client.get("/api/v1/me").json["data"]["user"]["avatar_url"] is None
    headers = {"X-CSRF-TOKEN": client.get_cookie("csrf_access_token").value}
    invalid = client.post(
        "/api/v1/me/avatar", data={"file": (BytesIO(b"GIF89a"), "photo.gif")},
        content_type="multipart/form-data", headers=headers,
    )
    assert invalid.status_code == 422
    oversized = client.post(
        "/api/v1/me/avatar",
        data={"file": (BytesIO(b"\x89PNG\r\n\x1a\n" + b"x" * (1024 * 1024)), "large.png")},
        content_type="multipart/form-data", headers=headers,
    )
    assert oversized.status_code == 422

    png = b"\x89PNG\r\n\x1a\n" + b"test-profile-photo"
    uploaded = client.post(
        "/api/v1/me/avatar", data={"file": (BytesIO(png), "photo.png")},
        content_type="multipart/form-data", headers=headers,
    )
    assert uploaded.status_code == 201
    avatar_url = uploaded.json["data"]["avatar_url"]
    assert client.get("/api/v1/me").json["data"]["user"]["avatar_url"] == avatar_url
    assert client.get("/api/v1/me/avatar").data == png

    other = app.test_client()
    _register_and_verify(other, app, "avatar-other@example.com")
    _login(other, "avatar-other@example.com")
    assert other.get("/api/v1/me/avatar").status_code == 404
    assert other.get(avatar_url).status_code == 404
    assert client.delete("/api/v1/me/avatar", headers=headers).status_code == 204
    assert client.get("/api/v1/me/avatar").status_code == 404
    assert client.get("/api/v1/me").json["data"]["user"]["avatar_url"] is None


def test_account_is_suspended_after_thirty_days_without_activity(client, app) -> None:
    _register_and_verify(client, app)
    _login(client)
    user_id = _member(app)
    with app.extensions["container"].database.session() as session:
        user = session.get(User, user_id)
        user.last_active_at = datetime.now(UTC) - timedelta(days=31)
        session.commit()

    assert client.get("/api/v1/me").status_code == 401
    with app.extensions["container"].database.session() as session:
        user = session.get(User, user_id)
        assert user.status == "suspended"
        assert user.display_name == "Test Member"


def test_content_staff_can_open_courses_and_specialist_moderates_only_own_course(app) -> None:
    specialist_client = app.test_client()
    specialist_headers = _staff(specialist_client, app, "specialist")
    content_client = app.test_client()
    content_headers = _staff(content_client, app, "content_manager")
    assert content_client.get("/api/v1/admin/courses", headers=content_headers).status_code == 200

    with app.extensions["container"].database.session() as session:
        specialists = session.scalars(select(User).where(User.role == "specialist")).all()
        author = session.scalars(select(User).where(User.role == "content_manager")).first()
        partner = PartnerProfile(slug="teaching-specialist", user_id=specialists[0].id)
        session.add(partner); session.flush()
        own = Course(slug="specialist-course", tier="free", field="neurology", level="beginner", owner_user_id=specialists[0].id)
        taught = Course(slug="taught-course", tier="free", field="neurology", level="beginner", instructor_partner_id=partner.id)
        other = Course(slug="other-course", tier="free", field="neurology", level="beginner")
        session.add_all([own, taught, other]); session.flush()
        own_comment = CourseComment(course_id=own.id, user_id=author.id, body="Own course question")
        taught_comment = CourseComment(course_id=taught.id, user_id=author.id, body="Taught course question")
        other_comment = CourseComment(course_id=other.id, user_id=author.id, body="Other course question")
        session.add_all([own_comment, taught_comment, other_comment]); session.commit()
        own_id, taught_id, other_id = own_comment.id, taught_comment.id, other_comment.id

    listing = specialist_client.get("/api/v1/admin/comments", headers=specialist_headers)
    assert listing.status_code == 200
    assert {item["id"] for item in listing.json["data"]} == {str(own_id), str(taught_id)}
    course_options = specialist_client.get("/api/v1/admin/comments/courses", headers=specialist_headers)
    assert {item["slug"] for item in course_options.json["data"]} == {"specialist-course", "taught-course"}
    denied = specialist_client.post(f"/api/v1/admin/comments/{other_id}/moderate", headers=specialist_headers, json={"decision": "approved"})
    assert denied.status_code == 403
    allowed = specialist_client.post(f"/api/v1/admin/comments/{own_id}/moderate", headers=specialist_headers, json={"decision": "approved"})
    assert allowed.status_code == 200
    assert specialist_client.post(f"/api/v1/admin/comments/{taught_id}/moderate", headers=specialist_headers, json={"decision": "approved"}).status_code == 200
