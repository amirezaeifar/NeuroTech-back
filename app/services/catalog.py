"""Product catalogue, cart, inquiry, and direct-sale use cases."""

from __future__ import annotations

import re
import unicodedata
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.core.auth_models import UserProfile
from app.core.catalog_models import (
    CartItem,
    Product,
    ProductCategory,
    ProductCategoryTranslation,
    ProductInquiry,
    ProductMedia,
    ProductOrder,
    ProductOrderItem,
    ProductPaymentAttempt,
    ProductPaymentEvent,
    ProductPrice,
    ProductTranslation,
    ShoppingCart,
)
from app.core.unit_of_work import SqlAlchemyUnitOfWork
from app.domain.auth import normalize_email
from app.domain.catalog import (
    INQUIRY_STATUSES,
    validate_prices,
    validate_translations,
)
from app.domain.errors import ConflictError, NotFoundError, ValidationError
from app.domain.ports import PaymentGateway


class CatalogService:
    def __init__(self, uow_factory, gateway: PaymentGateway) -> None:  # type: ignore[no-untyped-def]
        self.uow_factory = uow_factory
        self.gateway = gateway

    def categories(self, locale: str) -> list[dict]:
        with self.uow_factory() as uow:
            rows = list(
                uow.session.scalars(
                    select(ProductCategory)
                    .options(selectinload(ProductCategory.translations))
                    .where(
                        ProductCategory.published_at.is_not(None),
                        ProductCategory.archived_at.is_(None),
                    )
                    .order_by(ProductCategory.position, ProductCategory.slug)
                ).unique()
            )
            return [
                {
                    "id": str(row.id),
                    "slug": row.slug,
                    "title": _localized(row.translations, locale, "title"),
                }
                for row in rows
            ]

    def admin_categories(self) -> list[dict]:
        with self.uow_factory() as uow:
            rows = list(
                uow.session.scalars(
                    select(ProductCategory)
                    .options(selectinload(ProductCategory.translations))
                    .where(ProductCategory.archived_at.is_(None))
                    .order_by(ProductCategory.position, ProductCategory.created_at)
                ).unique()
            )
            return [
                {
                    "id": str(row.id),
                    "slug": row.slug,
                    "position": row.position,
                    "published": row.published_at is not None,
                    "translations": [
                        {"locale": item.locale, "title": item.title} for item in row.translations
                    ],
                }
                for row in rows
            ]

    def products(
        self, locale: str, category: str | None, page: int, page_size: int
    ) -> tuple[list[dict], int]:
        conditions = [Product.published_at.is_not(None), Product.archived_at.is_(None)]
        if category:
            conditions.append(ProductCategory.slug == category)
        with self.uow_factory() as uow:
            base = select(Product).join(ProductCategory).where(*conditions)
            total = uow.session.scalar(select(func.count()).select_from(base.subquery())) or 0
            rows = list(
                uow.session.scalars(
                    base.options(*_product_options())
                    .order_by(Product.created_at, Product.id)
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                ).unique()
            )
            return [_product_payload(row, locale) for row in rows], total

    def product(self, slug: str, locale: str, *, admin: bool = False) -> dict:
        with self.uow_factory() as uow:
            query = (
                select(Product)
                .options(*_product_options())
                .where(Product.slug == slug, Product.archived_at.is_(None))
            )
            if not admin:
                query = query.where(Product.published_at.is_not(None))
            product = uow.session.scalar(query)
            if product is None:
                raise NotFoundError("Product does not exist.")
            return _product_payload(product, locale, admin=admin)

    def admin_products(self) -> list[dict]:
        with self.uow_factory() as uow:
            rows = list(
                uow.session.scalars(
                    select(Product)
                    .options(*_product_options())
                    .where(Product.archived_at.is_(None))
                ).unique()
            )
            return [_product_payload(row, "en", admin=True) for row in rows]

    def create_category(self, data: dict) -> dict:
        validate_translations(data["translations"])
        category_id = uuid4()
        english_title = _english_translation(data["translations"])["title"]
        slug = _generated_slug(english_title, category_id, max_length=120, fallback="category")
        with self.uow_factory() as uow:
            duplicate = uow.session.scalar(
                select(ProductCategory.id)
                .join(ProductCategoryTranslation)
                .where(
                    ProductCategoryTranslation.locale == "en",
                    func.lower(ProductCategoryTranslation.title) == english_title.lower(),
                    ProductCategory.archived_at.is_(None),
                )
            )
            if duplicate:
                raise ConflictError("A product category with this English title already exists.")
            category = ProductCategory(
                id=category_id,
                slug=slug,
                position=data.get("position", 0),
                published_at=datetime.now(UTC),
            )
            category.translations.extend(
                ProductCategoryTranslation(**item) for item in data["translations"]
            )
            uow.session.add(category)
            uow.commit()
            return {"id": str(category.id), "slug": category.slug}

    def archive_category(self, category_id: UUID) -> None:
        with self.uow_factory() as uow:
            category = uow.session.get(ProductCategory, category_id)
            if category is None or category.archived_at is not None:
                raise NotFoundError("Product category does not exist.")
            has_products = uow.session.scalar(
                select(Product.id).where(
                    Product.category_id == category.id,
                    Product.archived_at.is_(None),
                )
            )
            if has_products:
                raise ConflictError(
                    "Archive the products in this category before deleting the category."
                )
            category.archived_at = datetime.now(UTC)
            category.published_at = None
            uow.commit()

    def create_product(self, data: dict) -> dict:
        translations = _normalized_product_translations(data["translations"])
        prices = data.get("prices", [])
        validate_translations(translations)
        product_id = uuid4()
        english_name = _english_translation(translations)["name"]
        slug = _generated_slug(english_name, product_id, max_length=160, fallback="product")
        validate_prices(data["sale_mode"], prices)
        stock = data.get("stock_quantity")
        if data["sale_mode"] == "direct" and (stock is None or stock < 0):
            raise ValidationError("Direct-sale products require a non-negative stock quantity.")
        with self.uow_factory() as uow:
            category = uow.session.scalar(
                select(ProductCategory).where(
                    ProductCategory.slug == data["category_slug"],
                    ProductCategory.archived_at.is_(None),
                )
            )
            if category is None:
                raise ValidationError("Product category does not exist.")
            if uow.session.scalar(select(Product.id).where(Product.sku == data["sku"])):
                raise ConflictError("Product SKU already exists.")
            product = Product(
                id=product_id,
                category_id=category.id,
                slug=slug,
                sku=data["sku"].strip(),
                sale_mode=data["sale_mode"],
                stock_quantity=stock,
            )
            product.translations.extend(ProductTranslation(**item) for item in translations)
            product.prices.extend(ProductPrice(**item) for item in prices)
            for item in data.get("media", []):
                if bool(item.get("stored_file_id")) == bool(item.get("external_url")):
                    raise ValidationError("Product media requires one stored file or external URL.")
                product.media.append(ProductMedia(**item))
            uow.session.add(product)
            uow.commit()
            return _product_payload(product, "en", admin=True)

    def update_product(self, product_id: UUID, data: dict) -> dict:
        with self.uow_factory() as uow:
            product = uow.session.scalar(
                select(Product)
                .options(*_product_options())
                .where(Product.id == product_id, Product.archived_at.is_(None))
            )
            if product is None:
                raise NotFoundError("Product does not exist.")
            category = product.category
            if "category_slug" in data:
                category = uow.session.scalar(
                    select(ProductCategory).where(
                        ProductCategory.slug == data["category_slug"],
                        ProductCategory.archived_at.is_(None),
                    )
                )
                if category is None:
                    raise ValidationError("Product category does not exist.")
                product.category = category
            if "sku" in data:
                duplicate = uow.session.scalar(
                    select(Product.id).where(Product.sku == data["sku"], Product.id != product.id)
                )
                if duplicate:
                    raise ConflictError("Product SKU already exists.")
                product.sku = data["sku"].strip()
            sale_mode = data.get("sale_mode", product.sale_mode)
            prices = data.get(
                "prices",
                [
                    {"currency": item.currency, "amount_minor": item.amount_minor}
                    for item in product.prices
                ],
            )
            validate_prices(sale_mode, prices)
            stock = data.get("stock_quantity", product.stock_quantity)
            if sale_mode == "direct" and (stock is None or stock < 0):
                raise ValidationError("Direct-sale products require a non-negative stock quantity.")
            product.sale_mode = sale_mode
            product.stock_quantity = stock if sale_mode == "direct" else None
            if "translations" in data:
                validate_translations(data["translations"])
                translations = _normalized_product_translations(data["translations"])
                english_name = _english_translation(translations)["name"]
                product.slug = _generated_slug(
                    english_name, product.id, max_length=160, fallback="product"
                )
                product.translations.clear()
                uow.session.flush()
                product.translations.extend(ProductTranslation(**item) for item in translations)
            if "prices" in data:
                product.prices.clear()
                uow.session.flush()
                product.prices.extend(ProductPrice(**item) for item in prices)
            if "media" in data:
                product.media.clear()
                uow.session.flush()
                for item in data["media"]:
                    if bool(item.get("stored_file_id")) == bool(item.get("external_url")):
                        raise ValidationError(
                            "Product media requires one stored file or external URL."
                        )
                    product.media.append(ProductMedia(**item))
            uow.commit()
            return _product_payload(product, "en", admin=True)

    def publish_product(self, product_id: UUID, published: bool) -> dict:
        with self.uow_factory() as uow:
            product = uow.session.scalar(
                select(Product)
                .options(*_product_options())
                .where(Product.id == product_id, Product.archived_at.is_(None))
            )
            if product is None:
                raise NotFoundError("Product does not exist.")
            validate_translations([{"locale": item.locale} for item in product.translations])
            validate_prices(
                product.sale_mode,
                [{"currency": p.currency, "amount_minor": p.amount_minor} for p in product.prices],
            )
            product.published_at = datetime.now(UTC) if published else None
            uow.commit()
            return _product_payload(product, "en", admin=True)

    def archive_product(self, product_id: UUID) -> None:
        with self.uow_factory() as uow:
            product = uow.session.get(Product, product_id)
            if product:
                product.archived_at = product.archived_at or datetime.now(UTC)
                product.published_at = None
                uow.commit()

    def cart(self, user_id: UUID, locale: str = "en") -> dict:
        with self.uow_factory() as uow:
            cart = _active_cart(uow.session, user_id, create=False)
            return _cart_payload(uow.session, cart, locale)

    def set_cart_item(self, user_id: UUID, product_id: UUID, quantity: int) -> dict:
        if not 1 <= quantity <= 99:
            raise ValidationError("Cart quantity must be between 1 and 99.")
        with self.uow_factory() as uow:
            product = uow.session.scalar(
                select(Product).where(
                    Product.id == product_id,
                    Product.published_at.is_not(None),
                    Product.archived_at.is_(None),
                )
            )
            if product is None:
                raise NotFoundError("Product does not exist.")
            if product.sale_mode != "direct":
                raise ValidationError("Inquiry-only products cannot be added to a cart.")
            if product.stock_quantity is not None and quantity > product.stock_quantity:
                raise ConflictError("Requested quantity is not available.")
            cart = _active_cart(uow.session, user_id, create=True)
            item = uow.session.scalar(
                select(CartItem).where(
                    CartItem.cart_id == cart.id, CartItem.product_id == product.id
                )
            )
            if item is None:
                uow.session.add(CartItem(cart_id=cart.id, product_id=product.id, quantity=quantity))
            else:
                item.quantity = quantity
            uow.commit()
            return _cart_payload(uow.session, cart, "en")

    def remove_cart_item(self, user_id: UUID, product_id: UUID) -> None:
        with self.uow_factory() as uow:
            cart = _active_cart(uow.session, user_id, create=False)
            if cart:
                item = uow.session.scalar(
                    select(CartItem).where(
                        CartItem.cart_id == cart.id, CartItem.product_id == product_id
                    )
                )
                if item:
                    uow.session.delete(item)
                    uow.commit()

    def create_inquiry(self, slug: str, data: dict, user_id: UUID | None) -> dict:
        message = " ".join(data["message"].split())
        if not 2 <= len(message) <= 4000:
            raise ValidationError("Inquiry message must be between 2 and 4000 characters.")
        with self.uow_factory() as uow:
            product = uow.session.scalar(
                select(Product).where(
                    Product.slug == slug,
                    Product.published_at.is_not(None),
                    Product.archived_at.is_(None),
                )
            )
            if product is None:
                raise NotFoundError("Product does not exist.")
            if product.sale_mode != "inquiry":
                raise ValidationError("This product is available through direct checkout.")
            try:
                email = normalize_email(data["email"])
            except ValueError as error:
                raise ValidationError(str(error)) from error
            inquiry = ProductInquiry(
                product_id=product.id,
                user_id=user_id,
                name=data["name"].strip(),
                email=email,
                phone=(data.get("phone") or "").strip() or None,
                quantity=data["quantity"],
                message=message,
                status="pending",
            )
            uow.session.add(inquiry)
            uow.commit()
            return _inquiry_payload(inquiry, product.slug)

    def inquiries(self, status: str | None = None) -> list[dict]:
        if status and status not in INQUIRY_STATUSES:
            raise ValidationError("Unknown inquiry status.")
        with self.uow_factory() as uow:
            query = select(ProductInquiry, Product.slug).join(Product)
            if status:
                query = query.where(ProductInquiry.status == status)
            return [
                _inquiry_payload(item, slug)
                for item, slug in uow.session.execute(
                    query.order_by(ProductInquiry.created_at.desc())
                ).all()
            ]

    def respond_inquiry(
        self, inquiry_id: UUID, moderator_id: UUID, status: str, response: str | None
    ) -> dict:
        if status not in INQUIRY_STATUSES - {"pending"}:
            raise ValidationError("Inquiry status must be answered, closed or rejected.")
        with self.uow_factory() as uow:
            inquiry = uow.session.get(ProductInquiry, inquiry_id)
            if inquiry is None:
                raise NotFoundError("Inquiry does not exist.")
            inquiry.status, inquiry.response = status, (response or "").strip() or None
            inquiry.responded_by, inquiry.responded_at = moderator_id, datetime.now(UTC)
            product = uow.session.get(Product, inquiry.product_id)
            uow.commit()
            return _inquiry_payload(inquiry, product.slug if product else "")

    def create_product_order(self, user_id: UUID, currency: str, shipping: dict) -> dict:
        currency = currency.upper()
        if currency not in {"IRR", "USD"}:
            raise ValidationError("Currency must be IRR or USD.")
        with self.uow_factory() as uow:
            profile = uow.session.scalar(
                select(UserProfile).where(UserProfile.user_id == user_id)
            )
            if profile is None or not all((profile.full_name, profile.email, profile.phone)):
                raise ValidationError("Complete your basic information before placing an order.")
            if not str(shipping.get("address", "")).strip():
                raise ValidationError("Address is required for delivery.")
            cart = _active_cart(uow.session, user_id, create=False)
            if cart is None:
                raise ValidationError("Cart is empty.")
            cart_items = list(
                uow.session.scalars(select(CartItem).where(CartItem.cart_id == cart.id))
            )
            if not cart_items:
                raise ValidationError("Cart is empty.")
            order = ProductOrder(
                user_id=user_id,
                currency=currency,
                total_minor=0,
                status="pending",
                fulfillment_status="awaiting_payment",
                shipping_address=shipping,
            )
            uow.session.add(order)
            uow.session.flush()
            total = 0
            for cart_item in cart_items:
                product = uow.session.scalar(
                    select(Product)
                    .options(selectinload(Product.translations), selectinload(Product.prices))
                    .where(Product.id == cart_item.product_id)
                    .with_for_update()
                )
                if (
                    product is None
                    or product.sale_mode != "direct"
                    or product.published_at is None
                    or product.archived_at is not None
                ):
                    raise ValidationError("Cart contains an unavailable product.")
                if (
                    product.stock_quantity is not None
                    and cart_item.quantity > product.stock_quantity
                ):
                    raise ConflictError(
                        "A cart item is no longer available in the requested quantity."
                    )
                price = next((item for item in product.prices if item.currency == currency), None)
                if price is None:
                    raise ValidationError("A cart item is not sold in the selected currency.")
                title = _localized(product.translations, "en", "name")
                total += price.amount_minor * cart_item.quantity
                uow.session.add(
                    ProductOrderItem(
                        order_id=order.id,
                        product_id=product.id,
                        title_snapshot=title,
                        quantity=cart_item.quantity,
                        unit_amount_minor=price.amount_minor,
                    )
                )
            order.total_minor = total
            attempt = ProductPaymentAttempt(
                order_id=order.id,
                provider="fake",
                provider_reference=f"fake-product:{order.id}",
                status="pending",
                redirect_url="pending",
            )
            uow.session.add(attempt)
            uow.session.flush()
            attempt.redirect_url = self.gateway.create_payment(
                reference=str(attempt.id),
                amount_minor=total,
                currency=currency,
                callback_url="/api/v1/product-payments/fake",
            )
            cart.status = "checked_out"
            uow.commit()
            return {
                "id": str(order.id),
                "status": order.status,
                "fulfillment_status": order.fulfillment_status,
                "currency": currency,
                "total_minor": total,
                "payment_url": attempt.redirect_url,
            }

    def product_order(self, user_id: UUID, order_id: UUID) -> dict:
        with self.uow_factory() as uow:
            order = uow.session.scalar(
                select(ProductOrder).where(
                    ProductOrder.id == order_id, ProductOrder.user_id == user_id
                )
            )
            if order is None:
                raise NotFoundError("Product order does not exist.")
            items = list(
                uow.session.scalars(
                    select(ProductOrderItem).where(ProductOrderItem.order_id == order.id)
                )
            )
            attempt = uow.session.scalar(
                select(ProductPaymentAttempt)
                .where(ProductPaymentAttempt.order_id == order.id)
                .order_by(ProductPaymentAttempt.created_at.desc())
            )
            return {
                "id": str(order.id),
                "status": order.status,
                "fulfillment_status": order.fulfillment_status,
                "currency": order.currency,
                "total_minor": order.total_minor,
                "shipping_address": order.shipping_address,
                "paid_at": order.paid_at.isoformat() if order.paid_at else None,
                "payment_url": attempt.redirect_url if attempt else None,
                "items": [
                    {
                        "product_id": str(item.product_id),
                        "title": item.title_snapshot,
                        "quantity": item.quantity,
                        "unit_amount_minor": item.unit_amount_minor,
                    }
                    for item in items
                ],
            }

    def product_payment(self, attempt_id: UUID, result: str) -> dict:
        if result not in {"success", "cancel", "failure"}:
            raise ValidationError("Fake payment result must be success, cancel or failure.")
        with self.uow_factory() as uow:
            attempt = uow.session.scalar(
                select(ProductPaymentAttempt)
                .where(ProductPaymentAttempt.id == attempt_id)
                .with_for_update()
            )
            if attempt is None:
                raise NotFoundError("Product payment attempt does not exist.")
            order = uow.session.scalar(
                select(ProductOrder).where(ProductOrder.id == attempt.order_id).with_for_update()
            )
            if order is None:
                raise NotFoundError("Product order does not exist.")
            event_id = f"fake-product:{attempt_id}:{result}"
            if not uow.session.scalar(
                select(ProductPaymentEvent.id).where(
                    ProductPaymentEvent.provider_event_id == event_id
                )
            ):
                uow.session.add(
                    ProductPaymentEvent(
                        attempt_id=attempt.id,
                        provider_event_id=event_id,
                        event_type=result,
                        payload={"result": result},
                    )
                )
            if result == "success" and order.status != "paid":
                for item in uow.session.scalars(
                    select(ProductOrderItem).where(ProductOrderItem.order_id == order.id)
                ):
                    product = uow.session.scalar(
                        select(Product).where(Product.id == item.product_id).with_for_update()
                    )
                    if product and product.stock_quantity is not None:
                        if product.stock_quantity < item.quantity:
                            raise ConflictError(
                                "Product stock changed before payment confirmation."
                            )
                        product.stock_quantity -= item.quantity
                order.status, order.paid_at, attempt.status = "paid", datetime.now(UTC), "succeeded"
                order.fulfillment_status = "awaiting_confirmation"
            elif result == "cancel" and order.status == "pending":
                order.status, attempt.status = "cancelled", "cancelled"
            elif result == "failure" and order.status == "pending":
                order.status, attempt.status = "failed", "failed"
            uow.commit()
            return {"order_id": str(order.id), "status": order.status}


def _product_options() -> tuple:
    return (
        selectinload(Product.category).selectinload(ProductCategory.translations),
        selectinload(Product.translations),
        selectinload(Product.prices),
        selectinload(Product.media),
    )


def _localized(items: list, locale: str, attribute: str) -> str:  # type: ignore[type-arg]
    selected = next((item for item in items if item.locale == locale), None) or next(
        (item for item in items if item.locale == "en"), None
    )
    return getattr(selected or items[0], attribute) if items else ""


def _english_translation(translations: list[dict]) -> dict:
    return next(item for item in translations if item["locale"] == "en")


def _normalized_product_translations(translations: list[dict]) -> list[dict]:
    normalized = []
    for item in translations:
        details = item.get("details") or {}
        description = (
            item.get("description") or details.get("overviewBody") or item["short_description"]
        ).strip()
        normalized.append({**item, "description": description})
    return normalized


def _generated_slug(title: str, record_id: UUID, *, max_length: int, fallback: str) -> str:
    """Build a deterministic, URL-safe slug from the English title and UUID."""
    ascii_title = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    suffix = record_id.hex
    stem_limit = max_length - len(suffix) - 1
    stem = "-".join(re.findall(r"[a-z0-9]+", ascii_title.lower()))[:stem_limit].strip("-")
    return f"{stem or fallback}-{suffix}"


def _product_payload(product: Product, locale: str, *, admin: bool = False) -> dict:
    data = {
        "id": str(product.id),
        "slug": product.slug,
        "sku": product.sku,
        "category": product.category.slug,
        "category_title": _localized(product.category.translations, locale, "title"),
        "sale_mode": product.sale_mode,
        "stock_quantity": product.stock_quantity,
        "name": _localized(product.translations, locale, "name"),
        "short_description": _localized(product.translations, locale, "short_description"),
        "description": _localized(product.translations, locale, "description"),
        "details": _localized(product.translations, locale, "details") or {},
        "prices": [
            {"currency": p.currency, "amount_minor": p.amount_minor}
            for p in sorted(product.prices, key=lambda p: p.currency)
        ],
        "media": [
            {
                "id": str(m.id),
                "stored_file_id": str(m.stored_file_id) if m.stored_file_id else None,
                "file_url": f"/api/v1/files/{m.stored_file_id}" if m.stored_file_id else None,
                "external_url": m.external_url,
                "alt_text": m.alt_text,
                "position": m.position,
            }
            for m in product.media
        ],
        "published": product.published_at is not None,
    }
    if admin:
        data["translations"] = [
            {
                "locale": t.locale,
                "name": t.name,
                "short_description": t.short_description,
                "description": t.description,
                "details": t.details,
            }
            for t in product.translations
        ]
    return data


def _active_cart(session, user_id: UUID, *, create: bool) -> ShoppingCart | None:  # type: ignore[no-untyped-def]
    cart = session.scalar(
        select(ShoppingCart).where(ShoppingCart.user_id == user_id, ShoppingCart.status == "active")
    )
    if cart is None and create:
        cart = ShoppingCart(user_id=user_id, status="active")
        session.add(cart)
        session.flush()
    return cart


def _cart_payload(session, cart: ShoppingCart | None, locale: str) -> dict:  # type: ignore[no-untyped-def]
    if cart is None:
        return {"id": None, "items": []}
    result = []
    for item in session.scalars(select(CartItem).where(CartItem.cart_id == cart.id)):
        product = session.scalar(
            select(Product).options(*_product_options()).where(Product.id == item.product_id)
        )
        if product:
            result.append({"product": _product_payload(product, locale), "quantity": item.quantity})
    return {"id": str(cart.id), "items": result}


def _inquiry_payload(item: ProductInquiry, slug: str) -> dict:
    return {
        "id": str(item.id),
        "product_slug": slug,
        "name": item.name,
        "email": item.email,
        "phone": item.phone,
        "quantity": item.quantity,
        "message": item.message,
        "status": item.status,
        "response": item.response,
        "created_at": item.created_at.isoformat(),
    }


def catalog_service_from_container(container) -> CatalogService:  # type: ignore[no-untyped-def]
    return CatalogService(
        lambda: SqlAlchemyUnitOfWork(container.database.session_factory), container.payment_gateway
    )
