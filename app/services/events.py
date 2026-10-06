"""Published event catalogue and capacity-safe reservations."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.orm import selectinload

from app.core.auth_models import User
from app.core.catalog_models import (
    Event,
    EventReservation,
    EventSpeaker,
    EventTranslation,
    StoredFile,
)
from app.core.content_models import PartnerProfile, PartnerTranslation
from app.core.unit_of_work import SqlAlchemyUnitOfWork
from app.domain.catalog import EVENT_KINDS, EVENT_STATUSES, validate_slug, validate_translations
from app.domain.errors import AuthenticationError, ConflictError, NotFoundError, ValidationError
from app.domain.ports import EmailSender
from app.services.email_templates import event_reservation


class EventService:
    def __init__(self, uow_factory, email_sender: EmailSender, secret_key: str, frontend_url: str) -> None:  # type: ignore[no-untyped-def]
        self.uow_factory = uow_factory
        self.email_sender = email_sender
        self.reservation_tokens = URLSafeTimedSerializer(secret_key, salt="event-reservation")
        self.frontend_url = frontend_url.rstrip("/")

    def list(self, locale: str, kind: str | None = None, status: str | None = None) -> list[dict]:
        if kind and kind not in EVENT_KINDS:
            raise ValidationError("Event kind must be online or onsite.")
        if status and status not in EVENT_STATUSES:
            raise ValidationError("Unknown event status.")
        conditions = [Event.published_at.is_not(None), Event.archived_at.is_(None)]
        if kind:
            conditions.append(Event.kind == kind)
        if status:
            conditions.append(Event.status == status)
        with self.uow_factory() as uow:
            rows = list(
                uow.session.scalars(
                    select(Event)
                    .options(selectinload(Event.translations))
                    .where(*conditions)
                    .order_by(Event.starts_at, Event.id)
                ).unique()
            )
            return [_payload(uow.session, item, locale) for item in rows]

    def detail(self, slug: str, locale: str, *, admin: bool = False) -> dict:
        with self.uow_factory() as uow:
            query = (
                select(Event)
                .options(selectinload(Event.translations))
                .where(Event.slug == slug, Event.archived_at.is_(None))
            )
            if not admin:
                query = query.where(Event.published_at.is_not(None))
            event = uow.session.scalar(query)
            if event is None:
                raise NotFoundError("Event does not exist.")
            return _payload(uow.session, event, locale, admin=admin)

    def admin_list(self) -> list[dict]:
        with self.uow_factory() as uow:
            rows = list(
                uow.session.scalars(
                    select(Event)
                    .options(selectinload(Event.translations))
                    .where(Event.archived_at.is_(None))
                    .order_by(Event.starts_at)
                ).unique()
            )
            return [_payload(uow.session, item, "en", admin=True) for item in rows]

    def speaker_options(self, query: str) -> list[dict]:
        with self.uow_factory() as uow:
            search = query.strip()
            users = list(
                uow.session.scalars(
                    select(User)
                    .where(
                        User.display_name.contains(search, autoescape=True),
                        User.archived_at.is_(None),
                    )
                    .order_by(User.display_name)
                    .limit(30)
                )
            )
            partners = list(uow.session.scalars(select(PartnerProfile)
                .join(PartnerTranslation, and_(PartnerTranslation.partner_id == PartnerProfile.id,
                    PartnerTranslation.locale == "en"))
                .where(PartnerProfile.archived_at.is_(None), PartnerProfile.published_at.is_not(None),
                    PartnerTranslation.name.contains(search, autoescape=True))
                .order_by(PartnerTranslation.name).limit(30)))
            partner_ids = set(
                uow.session.scalars(
                    select(PartnerProfile.user_id).where(
                        PartnerProfile.user_id.in_([user.id for user in users]),
                        PartnerProfile.archived_at.is_(None),
                        PartnerProfile.published_at.is_not(None),
                    )
                )
            )
            options = [
                {
                    "id": str(user.id), "user_id": str(user.id), "partner_id": None,
                    "name": user.display_name,
                    "kind": "partner" if user.id in partner_ids else "member",
                }
                for user in users
            ]
            options.extend({"id": f"partner:{partner.id}", "user_id": None,
                "partner_id": str(partner.id), "name": next(
                    (item.name for item in partner.translations if item.locale == "en"), partner.slug),
                "kind": "partner"} for partner in partners)
            return options

    def create(self, data: dict) -> dict:
        slug = validate_slug(data["slug"])
        validate_translations(data["translations"])
        _validate_event(data)
        with self.uow_factory() as uow:
            _validate_media(uow.session, data["translations"])
            if uow.session.scalar(select(Event.id).where(Event.slug == slug)):
                raise ConflictError("Event slug already exists.")
            event = Event(
                slug=slug,
                kind=data["kind"],
                status=data["status"],
                starts_at=_utc(data["starts_at"]),
                ends_at=_utc(data["ends_at"]),
                timezone=data.get("timezone", "Asia/Tehran"),
                capacity=data.get("capacity"),
                online_url=data.get("online_url"),
                venue=data.get("venue"),
                cover_url=data.get("cover_url"),
                agenda_steps=data.get("agenda_steps", []),
            )
            if event.status == "live":
                event.live_started_at = datetime.now(UTC)
                event.step_started_at = event.live_started_at
                event.step_durations = [0] * len(event.agenda_steps or [])
            event.translations.extend(EventTranslation(**item) for item in data["translations"])
            _replace_speakers(uow.session, event, data.get("speakers", []))
            uow.session.add(event)
            uow.commit()
            return _payload(uow.session, event, "en", admin=True)

    def update(self, event_id: UUID, data: dict) -> dict:
        with self.uow_factory() as uow:
            lock_event_writes(uow.session)
            event = uow.session.scalar(
                select(Event)
                .options(selectinload(Event.translations))
                .where(Event.id == event_id, Event.archived_at.is_(None))
                .with_for_update()
            )
            if event is None:
                raise NotFoundError("Event does not exist.")
            merged = {
                "kind": data.get("kind", event.kind),
                "status": data.get("status", event.status),
                "starts_at": data.get("starts_at", event.starts_at),
                "ends_at": data.get("ends_at", event.ends_at),
                "capacity": data.get("capacity", event.capacity),
                "online_url": data.get("online_url", event.online_url),
                "venue": data.get("venue", event.venue),
                "timezone": data.get("timezone", event.timezone),
            }
            _validate_event(merged)
            if merged["capacity"] is not None and merged["capacity"] < _reserved(
                uow.session, event.id
            ):
                raise ConflictError("Capacity cannot be lower than confirmed reservations.")
            previous_status = event.status
            for key in (
                "kind",
                "status",
                "starts_at",
                "ends_at",
                "timezone",
                "capacity",
                "online_url",
                "venue",
                "cover_url",
                "agenda_steps",
            ):
                if key in data:
                    value = _utc(data[key]) if key in {"starts_at", "ends_at"} else data[key]
                    setattr(event, key, value)
            event.current_step = min(event.current_step, max(len(event.agenda_steps or []) - 1, 0))
            if previous_status != event.status:
                now = datetime.now(UTC)
                if event.status == "live":
                    event.live_started_at = now
                    event.step_started_at = now
                    event.step_durations = [0] * len(event.agenda_steps or [])
                    event.current_step = 0
                elif previous_status == "live" and event.step_started_at:
                    durations = list(event.step_durations or [])
                    durations += [0] * (len(event.agenda_steps or []) - len(durations))
                    spent = (now - _utc(event.step_started_at)).total_seconds()
                    durations[event.current_step] += max(0, int(spent))
                    event.step_durations = durations
                    event.step_started_at = None
            if "translations" in data:
                validate_translations(data["translations"])
                _validate_media(uow.session, data["translations"])
                event.translations.clear()
                uow.session.flush()
                event.translations.extend(EventTranslation(**item) for item in data["translations"])
            if "speakers" in data:
                event.speakers.clear()
                uow.session.flush()
                _replace_speakers(uow.session, event, data["speakers"])
            uow.commit()
            return _payload(uow.session, event, "en", admin=True)

    def publish(self, event_id: UUID, published: bool) -> dict:
        with self.uow_factory() as uow:
            event = uow.session.scalar(
                select(Event)
                .options(selectinload(Event.translations))
                .where(Event.id == event_id, Event.archived_at.is_(None))
            )
            if event is None:
                raise NotFoundError("Event does not exist.")
            validate_translations([{"locale": item.locale} for item in event.translations])
            event.published_at = datetime.now(UTC) if published else None
            uow.commit()
            return _payload(uow.session, event, "en", admin=True)

    def archive(self, event_id: UUID) -> None:
        with self.uow_factory() as uow:
            event = uow.session.get(Event, event_id)
            if event:
                event.archived_at = event.archived_at or datetime.now(UTC)
                event.published_at = None
                uow.commit()

    def reserve(self, user_id: UUID, slug: str) -> dict:
        """Email a confirmation link; no seat or reservation is created yet."""
        with self.uow_factory() as uow:
            event = uow.session.scalar(select(Event).where(
                Event.slug == slug, Event.published_at.is_not(None), Event.archived_at.is_(None)
            ))
            if event is None:
                raise NotFoundError("Event does not exist.")
            if event.status not in {"upcoming", "live"} or _utc(event.ends_at) <= datetime.now(UTC):
                raise ConflictError("Reservations have closed for this event.")
            user = uow.session.scalar(select(User).options(selectinload(User.emails)).where(User.id == user_id))
            if user is None or user.status != "active":
                raise AuthenticationError("An active account is required.")
            email = next((item.email for item in user.emails if item.verified_at is not None), None)
            if not email:
                raise AuthenticationError("A verified email address is required to reserve an event.")
            existing = uow.session.scalar(select(EventReservation).where(
                EventReservation.event_id == event.id, EventReservation.user_id == user_id
            ))
            if existing and existing.status == "confirmed":
                return {"id": str(existing.id), "event_slug": slug, "status": "confirmed"}
            if event.capacity is not None and _reserved(uow.session, event.id) >= event.capacity:
                raise ConflictError("Event capacity is full.")
            token = self.reservation_tokens.dumps({"event_id": str(event.id), "user_id": str(user_id), "email": email})
            title = next((item.title for item in event.translations if item.locale == "en"), slug)
        link = f"{self.frontend_url}/#/events/confirm?token={token}"
        subject, body = event_reservation(title, link)
        self.email_sender.send(email, subject, body)
        return {"event_slug": slug, "status": "pending_email"}

    def confirm_reservation(self, token: str) -> dict:
        try:
            claims = self.reservation_tokens.loads(token, max_age=86_400)
            event_id, user_id = UUID(claims["event_id"]), UUID(claims["user_id"])
            email = claims["email"]
        except (BadSignature, SignatureExpired, KeyError, TypeError, ValueError) as error:
            raise AuthenticationError("The reservation link is invalid or expired.") from error
        with self.uow_factory() as uow:
            lock_event_writes(uow.session)
            event = uow.session.scalar(
                select(Event)
                .where(
                    Event.id == event_id, Event.published_at.is_not(None), Event.archived_at.is_(None)
                )
                .with_for_update()
            )
            if event is None:
                raise NotFoundError("Event does not exist.")
            user = uow.session.scalar(select(User).options(selectinload(User.emails)).where(User.id == user_id))
            if user is None or user.status != "active" or not any(
                item.email == email and item.verified_at is not None for item in user.emails
            ):
                raise AuthenticationError("A verified email address is required to reserve an event.")
            if event.status not in {"upcoming", "live"}:
                raise ConflictError("This event is not accepting reservations.")
            if _utc(event.ends_at) <= datetime.now(UTC):
                raise ConflictError("Reservations have closed for this event.")
            existing = uow.session.scalar(
                select(EventReservation).where(
                    EventReservation.event_id == event.id, EventReservation.user_id == user_id
                )
            )
            confirmed = (
                uow.session.scalar(
                    select(func.count())
                    .select_from(EventReservation)
                    .where(
                        EventReservation.event_id == event.id,
                        EventReservation.status == "confirmed",
                    )
                )
                or 0
            )
            if existing:
                if existing.status == "cancelled":
                    if event.capacity is not None and confirmed >= event.capacity:
                        raise ConflictError("Event capacity is full.")
                    existing.status, existing.reserved_at = "confirmed", datetime.now(UTC)
                reservation = existing
            else:
                if event.capacity is not None and confirmed >= event.capacity:
                    raise ConflictError("Event capacity is full.")
                reservation = EventReservation(
                    event_id=event.id,
                    user_id=user_id,
                    status="confirmed",
                    reserved_at=datetime.now(UTC),
                )
                uow.session.add(reservation)
            uow.commit()
            return {
                "id": str(reservation.id),
                "event_slug": event.slug,
                "status": reservation.status,
                "reserved_at": reservation.reserved_at.isoformat(),
            }

    def cancel(self, user_id: UUID, slug: str) -> None:
        with self.uow_factory() as uow:
            lock_event_writes(uow.session)
            event_id = uow.session.scalar(
                select(Event.id).where(Event.slug == slug).with_for_update()
            )
            reservation = uow.session.scalar(
                select(EventReservation).where(
                    EventReservation.event_id == event_id, EventReservation.user_id == user_id
                )
            )
            if reservation and reservation.status == "confirmed":
                reservation.status = "cancelled"
                uow.commit()

    def reservation(self, user_id: UUID, slug: str) -> dict | None:
        with self.uow_factory() as uow:
            item = uow.session.scalar(
                select(EventReservation)
                .join(Event)
                .where(
                    Event.slug == slug,
                    EventReservation.user_id == user_id,
                    Event.archived_at.is_(None),
                    Event.published_at.is_not(None),
                )
            )
            return {"id": str(item.id), "status": item.status} if item else None

    def attendees(self, event_id: UUID) -> list[dict]:
        with self.uow_factory() as uow:
            if not uow.session.get(Event, event_id):
                raise NotFoundError("Event does not exist.")
            rows = uow.session.execute(
                select(EventReservation, User)
                .join(User)
                .where(
                    EventReservation.event_id == event_id,
                )
                .order_by(EventReservation.reserved_at.desc())
            ).all()
            return [
                {
                    "id": str(r.id),
                    "user_id": str(u.id),
                    "name": u.display_name,
                    "status": r.status,
                    "reserved_at": r.reserved_at.isoformat(),
                }
                for r, u in rows
            ]

    def cancel_attendee(self, event_id: UUID, user_id: UUID) -> None:
        with self.uow_factory() as uow:
            event = uow.session.get(Event, event_id)
            if not event:
                raise NotFoundError("Event does not exist.")
            slug = event.slug
        self.cancel(user_id, slug)


def _validate_event(data: dict) -> None:
    if data["kind"] not in EVENT_KINDS or data["status"] not in EVENT_STATUSES:
        raise ValidationError("Event kind or status is invalid.")
    if _utc(data["ends_at"]) <= _utc(data["starts_at"]):
        raise ValidationError("Event end must be after its start.")
    if data.get("capacity") is not None and data["capacity"] < 1:
        raise ValidationError("Event capacity must be positive.")
    if data["kind"] == "online" and data["status"] == "live" and not data.get("online_url"):
        raise ValidationError("A live online event requires a stream URL.")
    if data.get("online_url") and not data["online_url"].startswith("https://"):
        raise ValidationError("Stream links must use HTTPS.")
    try:
        ZoneInfo(data.get("timezone", "Asia/Tehran"))
    except (ZoneInfoNotFoundError, ValueError) as error:
        raise ValidationError("Enter a valid timezone, such as Asia/Tehran.") from error
    if data["kind"] == "onsite" and not data.get("venue"):
        raise ValidationError("Onsite events require a venue.")


def _localized(items: list, locale: str):  # type: ignore[no-untyped-def,type-arg]
    return (
        next((item for item in items if item.locale == locale), None)
        or next((item for item in items if item.locale == "en"), None)
        or items[0]
    )


def _payload(session, event: Event, locale: str, *, admin: bool = False) -> dict:  # type: ignore[no-untyped-def]
    translation = _localized(event.translations, locale)
    content = dict(translation.content or {})
    if not admin:
        fallback = next(
            (item.content or {} for item in event.translations if item != translation), {}
        )
        for section in ("gallery", "videos", "documents", "agenda", "faq", "closing_note"):
            if not content.get(section):
                content[section] = fallback.get(section, [] if section != "closing_note" else "")
    reserved = (
        session.scalar(
            select(func.count())
            .select_from(EventReservation)
            .where(EventReservation.event_id == event.id, EventReservation.status == "confirmed")
        )
        or 0
    )
    result = {
        "id": str(event.id),
        "slug": event.slug,
        "kind": event.kind,
        "status": event.status,
        "starts_at": _utc(event.starts_at).isoformat(),
        "ends_at": _utc(event.ends_at).isoformat(),
        "timezone": event.timezone,
        "capacity": event.capacity,
        "reserved": reserved,
        "remaining": max(event.capacity - reserved, 0) if event.capacity is not None else None,
        "online_url": event.online_url if admin else None,
        "venue": event.venue,
        "cover_url": event.cover_url,
        "agenda_steps": event.agenda_steps or [],
        "current_step": event.current_step,
        "live_started_at": (
            _utc(event.live_started_at).isoformat() if event.live_started_at else None
        ),
        "step_started_at": (
            _utc(event.step_started_at).isoformat() if event.step_started_at else None
        ),
        "step_durations": event.step_durations or [],
        "title": translation.title,
        "summary": translation.summary,
        "description": translation.description,
        "host_label": translation.host_label,
        "content": content,
        "chat_enabled": event.chat_enabled,
        "questions_enabled": event.questions_enabled,
        "published": event.published_at is not None,
        "speakers": [
            {
                "profile_user_id": str(speaker.user_id) if speaker.user_id else None,
                "partner_id": str(speaker.partner_id) if speaker.partner_id else None,
                "profile_slug": profile_slug,
                "name": name,
                "role_label": speaker.role_label,
                "position": speaker.position,
            }
            for speaker, name, profile_slug in session.execute(
                select(EventSpeaker, func.coalesce(PartnerTranslation.name, User.display_name), PartnerProfile.slug)
                .outerjoin(User, User.id == EventSpeaker.user_id)
                .outerjoin(
                    PartnerProfile,
                    or_(PartnerProfile.id == EventSpeaker.partner_id,
                        PartnerProfile.user_id == EventSpeaker.user_id)
                    & PartnerProfile.published_at.is_not(None)
                    & PartnerProfile.archived_at.is_(None),
                )
                .outerjoin(PartnerTranslation, and_(PartnerTranslation.partner_id == PartnerProfile.id,
                    PartnerTranslation.locale == locale))
                .where(EventSpeaker.event_id == event.id)
                .order_by(EventSpeaker.position)
            ).all()
        ],
    }
    if admin:
        result["translations"] = [
            {
                "locale": item.locale,
                "title": item.title,
                "summary": item.summary,
                "description": item.description,
                "host_label": item.host_label,
                "content": item.content or {},
            }
            for item in event.translations
        ]
        result["online_url"] = event.online_url
    return result


def _replace_speakers(session, event: Event, speakers: list[dict]) -> None:  # type: ignore[no-untyped-def]
    user_ids = [item["user_id"] for item in speakers if item.get("user_id")]
    partner_ids = [item["partner_id"] for item in speakers if item.get("partner_id")]
    positions = [item["position"] for item in speakers]
    if any(bool(item.get("user_id")) == bool(item.get("partner_id")) for item in speakers):
        raise ValidationError("Select either a member or a partner for each speaker.")
    if (len(user_ids) != len(set(user_ids)) or len(partner_ids) != len(set(partner_ids))
            or len(positions) != len(set(positions))):
        raise ValidationError("Event speakers and positions must be unique.")
    existing_ids = set(
        session.scalars(select(User.id).where(User.id.in_(user_ids))) if user_ids else []
    )
    if existing_ids != set(user_ids):
        raise ValidationError("An event speaker profile does not exist.")
    partners = list(session.scalars(select(PartnerProfile).where(
        PartnerProfile.id.in_(partner_ids), PartnerProfile.archived_at.is_(None),
        PartnerProfile.published_at.is_not(None)))) if partner_ids else []
    if {item.id for item in partners} != set(partner_ids):
        raise ValidationError("An event partner profile does not exist or is not published.")
    if any(item.user_id in user_ids for item in partners):
        raise ValidationError("The same person cannot be added twice as a member and partner.")
    event.speakers.extend(EventSpeaker(**item) for item in speakers)


def event_service_from_container(container) -> EventService:  # type: ignore[no-untyped-def]
    return EventService(lambda: SqlAlchemyUnitOfWork(container.database.session_factory),
        container.email_sender, container.settings.secret_key, container.settings.frontend_url)


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _validate_media(session, translations: list[dict]) -> None:
    for translation in translations:
        for kind in ("gallery", "videos", "documents"):
            for media in translation.get("content", {}).get(kind, []):
                if not media["url"].startswith("/api/v1/files/"):
                    continue
                stored = session.get(StoredFile, UUID(media["url"].rsplit("/", 1)[-1]))
                if not stored or stored.archived_at or not stored.is_public:
                    raise ValidationError(
                        "Event resources must reference an available public file."
                    )
                prefix = {"gallery": "image/", "videos": "video/"}.get(kind)
                if prefix and not stored.mime_type.startswith(prefix):
                    raise ValidationError("The uploaded file does not match this media section.")


def lock_event_writes(session) -> None:
    # SQLite ignores SELECT FOR UPDATE. Acquire its write lock before the count
    # so simultaneous bookings cannot both consume the final seat.
    if session.get_bind().dialect.name == "sqlite":
        session.execute(text("BEGIN IMMEDIATE"))


def _reserved(session, event_id: UUID) -> int:
    return (
        session.scalar(
            select(func.count())
            .select_from(EventReservation)
            .where(
                EventReservation.event_id == event_id,
                EventReservation.status == "confirmed",
            )
        )
        or 0
    )
