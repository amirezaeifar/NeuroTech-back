"""Authenticated user profile endpoints."""

from __future__ import annotations

from html import escape
from uuid import UUID

from flask import current_app, make_response, request, send_file
from flask_jwt_extended import get_jwt_identity, jwt_required
from marshmallow import EXCLUDE, Schema, fields, validate
from sqlalchemy import select

from app.core.academy_models import Course
from app.core.auth_models import Favorite, User, UserProfile
from app.core.catalog_models import Product, ProductOrder, ProductOrderItem, ProductPaymentAttempt
from app.core.commerce_models import Order, OrderItem, PaymentAttempt
from app.core.learning_models import Enrollment
from app.core.unit_of_work import SqlAlchemyUnitOfWork
from app.domain.errors import NotFoundError, ValidationError
from app.routes.v1 import api_v1
from app.services.files import file_service_from_container
from app.services.user_profiles import user_profile_service_from_container


class UserProfileSchema(Schema):
    class Meta:
        unknown = EXCLUDE

    full_name = fields.String(required=True, validate=validate.Length(min=2, max=160))
    email = fields.String(required=True, validate=validate.Length(max=320))
    phone = fields.String(required=True, validate=validate.Length(max=24))
    national_id = fields.String(
        load_default=None, allow_none=True, validate=validate.Length(max=20)
    )
    address = fields.String(load_default=None, allow_none=True, validate=validate.Length(max=1000))


def _service():  # type: ignore[no-untyped-def]
    return user_profile_service_from_container(current_app.extensions["container"])


@api_v1.get("/me/profile")
@jwt_required()
def user_profile():  # type: ignore[no-untyped-def]
    return {"data": _service().get(UUID(get_jwt_identity()))}


@api_v1.put("/me/profile")
@jwt_required()
@api_v1.arguments(UserProfileSchema)
def save_user_profile(data: dict):  # type: ignore[no-untyped-def]
    return {"data": _service().save(UUID(get_jwt_identity()), data)}


class FavoriteSchema(Schema):
    item_type = fields.String(required=True, validate=validate.OneOf(["course", "product"]))
    item_id = fields.UUID(required=True)


def _uow():
    return SqlAlchemyUnitOfWork(current_app.extensions["container"].database.session_factory)


def _file_service():
    return file_service_from_container(
        current_app.extensions["container"], current_app.config["UPLOAD_ROOT"]
    )


@api_v1.post("/me/avatar")
@jwt_required()
def upload_my_avatar():
    upload = request.files.get("file")
    if upload is None:
        raise ValidationError("Multipart field 'file' is required.")
    if not (upload.filename or "").lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
        raise ValidationError("Profile image must be PNG, JPEG, or WebP.")
    user_id = UUID(get_jwt_identity())
    files = _file_service()
    stored = files.save(user_id, upload, is_public=False, max_bytes=1024 * 1024)
    file_id = UUID(stored["id"])
    try:
        with _uow() as uow:
            user = uow.session.get(User, user_id)
            if user is None:
                raise NotFoundError("User does not exist.")
            previous = user.avatar_file_id
            user.avatar_file_id = file_id
            uow.commit()
    except Exception:
        files.delete(file_id)
        raise
    if previous:
        try:
            files.delete(previous)
        except (NotFoundError, OSError):
            pass
    return {"data": {"avatar_url": f"/api/v1/me/avatar?file={file_id}"}}, 201


@api_v1.get("/me/avatar")
@jwt_required()
def my_avatar():
    user_id = UUID(get_jwt_identity())
    with _uow() as uow:
        user = uow.session.get(User, user_id)
        if user is None or user.avatar_file_id is None:
            raise NotFoundError("Profile image does not exist.")
        file_id = user.avatar_file_id
    path, stored = _file_service().resolve_owned(file_id, user_id)
    response = send_file(path, mimetype=stored.mime_type, conditional=True)
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@api_v1.delete("/me/avatar")
@jwt_required()
def remove_my_avatar():
    user_id = UUID(get_jwt_identity())
    with _uow() as uow:
        user = uow.session.get(User, user_id)
        if user is None:
            raise NotFoundError("User does not exist.")
        previous = user.avatar_file_id
        user.avatar_file_id = None
        uow.commit()
    if previous:
        try:
            _file_service().delete(previous)
        except (NotFoundError, OSError):
            pass
    return "", 204


@api_v1.get("/me/courses")
@jwt_required()
def my_courses():
    user_id = UUID(get_jwt_identity())
    with _uow() as uow:
        rows = uow.session.execute(select(Enrollment, Course).join(Course, Course.id == Enrollment.course_id).where(Enrollment.user_id == user_id).order_by(Enrollment.enrolled_at.desc())).all()
        return {"data": [{"id": str(course.id), "slug": course.slug, "titles": {translation.locale: translation.title for translation in course.translations}, "status": enrollment.status, "enrolled_at": enrollment.enrolled_at.isoformat()} for enrollment, course in rows]}


@api_v1.get("/me/orders")
@jwt_required()
def my_orders():
    user_id = UUID(get_jwt_identity())
    with _uow() as uow:
        result = []
        for order in uow.session.scalars(select(Order).where(Order.user_id == user_id)):
            items = uow.session.scalars(select(OrderItem).where(OrderItem.order_id == order.id)).all()
            result.append({"id": str(order.id), "type": "course", "status": order.status, "currency": order.currency, "total_minor": order.total_minor, "created_at": order.created_at.isoformat(), "items": [item.title_snapshot for item in items]})
        for order in uow.session.scalars(select(ProductOrder).where(ProductOrder.user_id == user_id)):
            items = uow.session.scalars(select(ProductOrderItem).where(ProductOrderItem.order_id == order.id)).all()
            result.append({"id": str(order.id), "type": "product", "status": order.status, "currency": order.currency, "total_minor": order.total_minor, "created_at": order.created_at.isoformat(), "items": [item.title_snapshot for item in items]})
        return {"data": sorted(result, key=lambda item: item["created_at"], reverse=True)}


@api_v1.get("/me/payments")
@jwt_required()
def my_payments():
    user_id = UUID(get_jwt_identity())
    with _uow() as uow:
        result = []
        for attempt, order in uow.session.execute(select(PaymentAttempt, Order).join(Order, Order.id == PaymentAttempt.order_id).where(Order.user_id == user_id)):
            result.append({"id": str(attempt.id), "order_id": str(order.id), "type": "course", "provider": attempt.provider, "status": attempt.status, "amount_minor": order.total_minor, "currency": order.currency, "created_at": attempt.created_at.isoformat()})
        for attempt, order in uow.session.execute(select(ProductPaymentAttempt, ProductOrder).join(ProductOrder, ProductOrder.id == ProductPaymentAttempt.order_id).where(ProductOrder.user_id == user_id)):
            result.append({"id": str(attempt.id), "order_id": str(order.id), "type": "product", "provider": attempt.provider, "status": attempt.status, "amount_minor": order.total_minor, "currency": order.currency, "created_at": attempt.created_at.isoformat()})
        return {"data": sorted(result, key=lambda item: item["created_at"], reverse=True)}


@api_v1.get("/me/payments/<uuid:payment_id>/invoice")
@jwt_required()
def my_payment_invoice(payment_id: UUID):
    kind = request.args.get("type")
    locale = "fa" if request.args.get("locale") == "fa" else "en"
    labels = ({
        "title": "فاکتور پرداخت", "print": "چاپ یا ذخیره به PDF", "reference": "شماره فاکتور",
        "customer": "خریدار", "date": "تاریخ پرداخت", "type": "نوع سفارش",
        "payment": "شناسه پرداخت", "item": "شرح", "quantity": "تعداد", "price": "قیمت واحد",
        "total": "مبلغ پرداخت شده", "order": "شناسه سفارش", "course": "دوره", "product": "محصول",
    } if locale == "fa" else {
        "title": "Payment invoice", "print": "Print or save as PDF", "reference": "Invoice reference",
        "customer": "Customer", "date": "Payment date", "type": "Order type",
        "payment": "Payment reference", "item": "Item", "quantity": "Quantity", "price": "Unit price",
        "total": "Total paid", "order": "Order ID", "course": "Course", "product": "Product",
    })
    if kind not in ("course", "product"):
        raise NotFoundError("Invoice does not exist.")
    user_id = UUID(get_jwt_identity())
    with _uow() as uow:
        attempt_model, order_model, item_model = (
            (PaymentAttempt, Order, OrderItem) if kind == "course"
            else (ProductPaymentAttempt, ProductOrder, ProductOrderItem)
        )
        row = uow.session.execute(
            select(attempt_model, order_model)
            .join(order_model, order_model.id == attempt_model.order_id)
            .where(attempt_model.id == payment_id, order_model.user_id == user_id)
        ).first()
        if row is None or row[0].status != "succeeded" or row[1].status != "paid":
            raise NotFoundError("Invoice does not exist.")
        attempt, order = row
        items = uow.session.scalars(select(item_model).where(item_model.order_id == order.id)).all()
        profile = uow.session.scalar(select(UserProfile).where(UserProfile.user_id == user_id))
        user = uow.session.get(User, user_id)
        customer = profile.full_name if profile else user.display_name
        lines = "".join(
            f"<tr><td>{escape(item.title_snapshot)}</td><td>{getattr(item, 'quantity', 1)}</td>"
            f"<td>{item.unit_amount_minor:,} {escape(order.currency)}</td></tr>"
            for item in items
        )
        document = f"""<!doctype html><html lang="{locale}" dir="{'rtl' if locale == 'fa' else 'ltr'}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{labels['title']} {order.id}</title>
<style>body{{font:15px/1.7 Arial,sans-serif;color:#26313b;background:#f4f1ea;margin:0;padding:40px}}
main{{max-width:760px;margin:auto;background:white;padding:48px;box-shadow:0 18px 50px #17232d22}}
header{{display:flex;justify-content:space-between;gap:24px;border-bottom:2px solid #b88a45;padding-bottom:24px}}
h1{{font-size:34px;font-weight:400;margin:0}}small{{color:#64717a}}.meta{{display:grid;grid-template-columns:1fr 1fr;gap:18px;margin:30px 0}}
table{{border-collapse:collapse;width:100%}}th,td{{padding:14px;text-align:start;border-bottom:1px solid #dfe3e3}}
th{{background:#f4f1ea}}.total{{font-size:20px;font-weight:bold;text-align:end;margin-top:25px}}
button{{border:0;background:#26313b;color:white;padding:10px 18px;cursor:pointer;margin-bottom:20px}}
@media print{{body{{padding:0;background:white}}main{{box-shadow:none;padding:0}}button{{display:none}}}}</style></head>
<body><main><button onclick="window.print()">{labels['print']}</button><header><div><small>NEUROTECH</small>
<h1>{labels['title']}</h1></div><div><small>{labels['reference']}</small><div>{order.id}</div></div></header>
<div class="meta"><div><small>{labels['customer']}</small><div>{escape(customer)}</div></div>
<div><small>{labels['date']}</small><div>{escape(attempt.created_at.isoformat())}</div></div>
<div><small>{labels['type']}</small><div>{labels[kind]}</div></div>
<div><small>{labels['payment']}</small><div>{escape(attempt.provider_reference)}</div></div></div>
<table><thead><tr><th>{labels['item']}</th><th>{labels['quantity']}</th><th>{labels['price']}</th></tr></thead><tbody>{lines}</tbody></table>
<p class="total">{labels['total']}: {order.total_minor:,} {escape(order.currency)}</p>
<small>{labels['order']}: {order.id}</small></main></body></html>"""
        response = make_response(document)
        response.headers["Content-Type"] = "text/html; charset=utf-8"
        response.headers["Content-Disposition"] = f'attachment; filename="invoice-{order.id}.html"'
        response.headers["Cache-Control"] = "private, no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response


@api_v1.get("/me/favorites")
@jwt_required()
def my_favorites():
    with _uow() as uow:
        rows = uow.session.scalars(select(Favorite).where(Favorite.user_id == UUID(get_jwt_identity())).order_by(Favorite.created_at.desc())).all()
        result = []
        for item in rows:
            target = uow.session.get(Course if item.item_type == "course" else Product, item.item_id)
            if target is not None:
                result.append({"id": str(item.id), "item_type": item.item_type, "item_id": str(item.item_id), "slug": target.slug, "titles": {translation.locale: (translation.title if item.item_type == "course" else translation.name) for translation in target.translations}, "created_at": item.created_at.isoformat()})
        return {"data": result}


@api_v1.post("/me/favorites")
@jwt_required()
@api_v1.arguments(FavoriteSchema)
def add_favorite(data: dict):
    with _uow() as uow:
        model = Course if data["item_type"] == "course" else Product
        if uow.session.get(model, data["item_id"]) is None:
            raise NotFoundError("Item does not exist.")
        user_id = UUID(get_jwt_identity())
        item = uow.session.scalar(select(Favorite).where(Favorite.user_id == user_id, Favorite.item_type == data["item_type"], Favorite.item_id == data["item_id"]))
        if item is None:
            item = Favorite(user_id=user_id, **data)
            uow.session.add(item)
            uow.commit()
        return {"data": {"id": str(item.id)}}, 201


@api_v1.delete("/me/favorites/<uuid:favorite_id>")
@jwt_required()
def remove_favorite(favorite_id: UUID):
    with _uow() as uow:
        item = uow.session.scalar(select(Favorite).where(Favorite.id == favorite_id, Favorite.user_id == UUID(get_jwt_identity())))
        if item is None:
            raise NotFoundError("Favorite does not exist.")
        uow.session.delete(item)
        uow.commit()
    return "", 204
