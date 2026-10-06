"""Guest ticket workflow; HTTP handlers never access persistence directly."""

from datetime import UTC, datetime
from secrets import token_urlsafe
from uuid import UUID

from sqlalchemy import func, or_, select

from app.core.ticket_models import SupportTicket
from app.domain.auth import normalize_phone
from app.domain.errors import ConflictError, NotFoundError, ValidationError


class TicketService:
    def __init__(self, container):
        self.container = container

    def create(self, data: dict) -> dict:
        try:
            phone = normalize_phone(data["phone"])
        except ValueError as error:
            raise ValidationError(str(error)) from error
        for key in ("name", "subject", "message"):
            if not data[key].strip():
                raise ValidationError(f"{key} cannot be blank.")
        ticket = SupportTicket(
            tracking_token=token_urlsafe(32),
            name=data["name"].strip(),
            phone=phone,
            email=data.get("email") or None,
            subject=data["subject"].strip(),
            message=data["message"].strip(),
            category=data.get("category", "general"),
            locale=data.get("locale", "fa"),
            status="submitted",
            history=[self._event("submitted", "", None)],
        )
        with self.container.database.session() as session:
            session.add(ticket)
            session.commit()
            self._notify(session, ticket)
            return self._payload(ticket, admin=True)

    def list(self, *, page=1, page_size=20, status=None, q="", category=None) -> dict:
        conditions = []
        if status == "open":
            conditions.append(SupportTicket.status.in_(["submitted", "in_progress"]))
        elif status == "closed":
            conditions.append(SupportTicket.status.in_(["resolved", "rejected"]))
        elif status:
            conditions.append(SupportTicket.status == status)
        if category:
            conditions.append(SupportTicket.category == category)
        if q:
            conditions.append(
                or_(
                    *[
                        column.contains(q, autoescape=True)
                        for column in (
                            SupportTicket.name,
                            SupportTicket.phone,
                            SupportTicket.subject,
                        )
                    ]
                )
            )
        with self.container.database.session() as session:
            total = session.scalar(
                select(func.count()).select_from(SupportTicket).where(*conditions)
            )
            rows = session.scalars(
                select(SupportTicket)
                .where(*conditions)
                .order_by(SupportTicket.created_at.desc(), SupportTicket.id)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
            return {
                "data": [self._payload(row, admin=True) for row in rows],
                "meta": {"total": total, "page": page, "page_size": page_size},
            }

    def detail(self, identity, *, admin=False):
        with self.container.database.session() as session:
            condition = (
                SupportTicket.id == identity if admin else SupportTicket.tracking_token == identity
            )
            ticket = session.scalar(select(SupportTicket).where(condition))
            if ticket is None:
                raise NotFoundError("Ticket does not exist.")
            return self._payload(ticket, admin=admin)

    def update(self, ticket_id: UUID, data: dict, actor: str) -> dict:
        with self.container.database.session() as session:
            ticket = session.scalar(
                select(SupportTicket).where(SupportTicket.id == ticket_id).with_for_update()
            )
            if ticket is None:
                raise NotFoundError("Ticket does not exist.")
            if ticket.version != data["version"]:
                raise ConflictError("This ticket changed. Reload before replying.")
            status = data["status"]
            reply = data.get("reply", "").strip()
            if status == ticket.status and not reply:
                return self._payload(ticket, admin=True)
            ticket.status = status
            ticket.history = [*ticket.history, self._event(status, reply, actor)]
            session.commit()
            self._notify(session, ticket)
            return self._payload(ticket, admin=True)

    @staticmethod
    def _event(status, reply, actor):
        return {
            "status": status,
            "reply": reply,
            "actor_id": actor,
            "at": datetime.now(UTC).isoformat(),
            "notification": "pending",
        }

    def _notify(self, session, ticket):
        labels = {
            "submitted": "تیکت شما ثبت شد",
            "in_progress": "بررسی تیکت شما آغاز شد",
            "resolved": "درخواست شما انجام شد؛ پاسخ را در سایت بررسی کنید",
            "rejected": "درخواست شما رد شد؛ وضعیت را در سایت بررسی کنید",
        }
        english = {
            "submitted": "Your ticket was received",
            "in_progress": "Your ticket is being reviewed",
            "resolved": "Your request is complete. Check the response on the site",
            "rejected": "Your request was rejected. Check its status on the site",
        }
        origin = self.container.settings.frontend_url
        title = (labels if ticket.locale == "fa" else english)[ticket.status]
        message = f"NeuroTech: {title}\n{origin}/#/tickets/{ticket.tracking_token}"
        event = {**ticket.history[-1], "sms_text": message}
        try:
            event["sms_id"] = self.container.sms_sender.send(ticket.phone, message)
            event["notification"] = (
                "mock" if self.container.settings.sms_provider == "fake" else "sent"
            )
        except Exception:
            event["notification"] = "failed"
        ticket.history = [*ticket.history[:-1], event]
        session.commit()

    @staticmethod
    def _payload(ticket, *, admin):
        result = {
            "id": str(ticket.id),
            "subject": ticket.subject,
            "message": ticket.message,
            "status": ticket.status,
            "category": ticket.category,
            "created_at": ticket.created_at.replace(tzinfo=UTC).isoformat(),
            "updated_at": ticket.updated_at.replace(tzinfo=UTC).isoformat(),
            "history": [
                {key: event[key] for key in ("at", "status", "reply")} for event in ticket.history
            ],
        }
        if admin:
            result.update(
                name=ticket.name,
                phone=ticket.phone,
                email=ticket.email,
                version=ticket.version,
                tracking_token=ticket.tracking_token,
                history=ticket.history,
            )
        return result
