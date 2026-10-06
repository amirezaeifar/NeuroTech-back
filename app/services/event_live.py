"""Reservation-gated live room activity and instructor controls."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import delete, func, select

from app.core.auth_models import User
from app.core.catalog_models import (
    Event,
    EventLiveMessage,
    EventLivePresence,
    EventLiveQuestion,
    EventLiveVote,
    EventReservation,
    EventSpeaker,
)
from app.core.unit_of_work import SqlAlchemyUnitOfWork
from app.domain.errors import AuthorizationError, ConflictError, NotFoundError, ValidationError
from app.services.events import _payload, _utc, lock_event_writes


class EventLiveService:
    def __init__(self, uow_factory):
        self.uow_factory = uow_factory

    @staticmethod
    def _room(session, slug, user_id):
        lock_event_writes(session)
        event = session.scalar(
            select(Event)
            .where(Event.slug == slug, Event.archived_at.is_(None), Event.published_at.is_not(None))
            .with_for_update()
        )
        if event is None:
            raise NotFoundError("Event does not exist.")
        if event.status == "cancelled":
            raise ConflictError("This event has been cancelled.")
        user = session.get(User, user_id)
        instructor = bool(
            session.scalar(
                select(EventSpeaker.id).where(
                    EventSpeaker.event_id == event.id, EventSpeaker.user_id == user_id
                )
            )
        )
        if user and user.role in {"admin", "super_admin", "content_manager"}:
            instructor = True
        reservation = session.scalar(
            select(EventReservation.id).where(
                EventReservation.event_id == event.id,
                EventReservation.user_id == user_id,
                EventReservation.status == "confirmed",
            )
        )
        if not instructor and not reservation:
            raise AuthorizationError("Reserve this event before entering its live room.")
        return event, instructor

    def snapshot(
        self, slug: str, user_id: UUID, country_code: str | None = None, locale: str = "en"
    ) -> dict:
        now = datetime.now(UTC)
        with self.uow_factory() as uow:
            session = uow.session
            event, instructor = self._room(session, slug, user_id)
            if event.status == "live":
                presence = session.scalar(
                    select(EventLivePresence).where(
                        EventLivePresence.event_id == event.id, EventLivePresence.user_id == user_id
                    )
                )
                if presence is None:
                    presence = EventLivePresence(event_id=event.id, user_id=user_id, joined_at=now)
                    session.add(presence)
                presence.last_seen_at = now
                if country_code:
                    presence.country_code = country_code
                session.flush()
            active = list(
                session.scalars(
                    select(EventLivePresence).where(
                        EventLivePresence.event_id == event.id,
                        EventLivePresence.last_seen_at >= now - timedelta(seconds=45),
                    )
                )
            )
            messages = session.execute(
                select(EventLiveMessage, User.display_name)
                .join(User, User.id == EventLiveMessage.user_id)
                .where(EventLiveMessage.event_id == event.id)
                .order_by(EventLiveMessage.created_at.desc())
                .limit(80)
            ).all()
            questions = session.execute(
                select(EventLiveQuestion, User.display_name)
                .join(User, User.id == EventLiveQuestion.user_id)
                .where(EventLiveQuestion.event_id == event.id)
                .order_by(EventLiveQuestion.created_at.desc())
                .limit(100)
            ).all()
            question_ids = [q.id for q, _ in questions]
            total_questions = (
                session.scalar(
                    select(func.count())
                    .select_from(EventLiveQuestion)
                    .where(EventLiveQuestion.event_id == event.id)
                )
                or 0
            )
            counts = (
                dict(
                    session.execute(
                        select(EventLiveVote.question_id, func.count())
                        .where(EventLiveVote.question_id.in_(question_ids))
                        .group_by(EventLiveVote.question_id)
                    ).all()
                )
                if question_ids
                else {}
            )
            own_votes = (
                set(
                    session.scalars(
                        select(EventLiveVote.question_id).where(
                            EventLiveVote.question_id.in_(question_ids),
                            EventLiveVote.user_id == user_id,
                        )
                    )
                )
                if question_ids
                else set()
            )
            countries = {}
            for attendee in active:
                key = attendee.country_code or "--"
                countries[key] = countries.get(key, 0) + 1
            event_data = _payload(session, event, locale)
            event_data["online_url"] = event.online_url if event.status == "live" else None
            uow.commit()
            return {
                "event": event_data,
                "instructor": instructor,
                "viewer_count": len(active) if event.status == "live" else 0,
                "question_count": total_questions,
                "countries": countries if event.status == "live" else {},
                "chat_enabled": event.chat_enabled,
                "questions_enabled": event.questions_enabled,
                "messages": [
                    {
                        "id": str(m.id),
                        "author": name,
                        "mine": m.user_id == user_id,
                        "body": m.body,
                        "created_at": _utc(m.created_at).isoformat(),
                    }
                    for m, name in reversed(messages)
                ],
                "questions": [
                    {
                        "id": str(q.id),
                        "author": name,
                        "mine": q.user_id == user_id,
                        "body": q.body,
                        "answered": q.answered,
                        "votes": counts.get(q.id, 0),
                        "voted": q.id in own_votes,
                        "created_at": _utc(q.created_at).isoformat(),
                    }
                    for q, name in questions
                ],
            }

    def post(self, slug: str, user_id: UUID, kind: str, body: str) -> dict:
        body = body.strip()
        if not body or len(body) > 1000:
            raise ValidationError("Message must contain 1 to 1000 characters.")
        with self.uow_factory() as uow:
            event, _ = self._room(uow.session, slug, user_id)
            if event.status != "live":
                raise ConflictError("Event is not live.")
            if not (event.chat_enabled if kind == "message" else event.questions_enabled):
                raise ConflictError("The host has paused this conversation.")
            item = (EventLiveQuestion if kind == "question" else EventLiveMessage)(
                event_id=event.id, user_id=user_id, body=body
            )
            uow.session.add(item)
            uow.commit()
            return {"id": str(item.id)}

    def vote(self, slug: str, user_id: UUID, question_id: UUID) -> dict:
        with self.uow_factory() as uow:
            event, _ = self._room(uow.session, slug, user_id)
            if event.status != "live" or not event.questions_enabled:
                raise ConflictError("Question voting is closed.")
            question = uow.session.scalar(
                select(EventLiveQuestion).where(
                    EventLiveQuestion.id == question_id, EventLiveQuestion.event_id == event.id
                )
            )
            if question is None:
                raise NotFoundError("Question does not exist in this event.")
            existing = uow.session.scalar(
                select(EventLiveVote).where(
                    EventLiveVote.question_id == question_id, EventLiveVote.user_id == user_id
                )
            )
            if existing:
                uow.session.delete(existing)
            else:
                uow.session.add(EventLiveVote(question_id=question_id, user_id=user_id))
            uow.commit()
            return {"voted": existing is None}

    def control(
        self, slug: str, user_id: UUID, *, step: int | None = None, question_id: UUID | None = None
    ) -> dict:
        with self.uow_factory() as uow:
            event, instructor = self._room(uow.session, slug, user_id)
            if not instructor:
                raise AuthorizationError("Only event instructors can control the live session.")
            if event.status != "live":
                raise ConflictError("Event is not live.")
            if step is not None:
                if step < 0 or step >= len(event.agenda_steps or []):
                    raise ValidationError("Invalid agenda step.")
                if step != event.current_step:
                    durations = list(event.step_durations or [])
                    durations += [0] * (len(event.agenda_steps or []) - len(durations))
                    if event.step_started_at:
                        spent = (datetime.now(UTC) - _utc(event.step_started_at)).total_seconds()
                        durations[event.current_step] += max(0, int(spent))
                    event.step_durations = durations
                    event.step_started_at = datetime.now(UTC)
                event.current_step = step
            if question_id is not None:
                question = uow.session.scalar(
                    select(EventLiveQuestion).where(
                        EventLiveQuestion.id == question_id, EventLiveQuestion.event_id == event.id
                    )
                )
                if question is None:
                    raise NotFoundError("Question does not exist in this event.")
                question.answered = True
            uow.commit()
            return {"current_step": event.current_step}

    def configure(self, slug: str, user_id: UUID, data: dict) -> dict:
        with self.uow_factory() as uow:
            event, instructor = self._room(uow.session, slug, user_id)
            if not instructor:
                raise AuthorizationError("Only event instructors can control the live session.")
            status = data.get("status")
            if status and status != event.status:
                if (event.status, status) not in {("upcoming", "live"), ("live", "completed")}:
                    raise ConflictError("Invalid live session transition.")
                if status == "live" and not event.online_url:
                    raise ValidationError("Save a stream URL before starting the live session.")
                now = datetime.now(UTC)
                if status == "live":
                    event.live_started_at = now
                    event.step_started_at = now
                    event.step_durations = [0] * len(event.agenda_steps or [])
                    event.current_step = 0
                elif status == "completed" and event.step_started_at:
                    durations = list(event.step_durations or [])
                    durations += [0] * (len(event.agenda_steps or []) - len(durations))
                    spent = (now - _utc(event.step_started_at)).total_seconds()
                    durations[event.current_step] += max(0, int(spent))
                    event.step_durations = durations
                    event.step_started_at = None
                event.status = status
            for key in ("chat_enabled", "questions_enabled"):
                if key in data:
                    setattr(event, key, data[key])
            uow.commit()
            return {
                "status": event.status,
                "chat_enabled": event.chat_enabled,
                "questions_enabled": event.questions_enabled,
            }

    def moderate(self, slug: str, user_id: UUID, kind: str, item_id: UUID) -> None:
        model = {"messages": EventLiveMessage, "questions": EventLiveQuestion}.get(kind)
        if model is None:
            raise ValidationError("Unknown conversation type.")
        with self.uow_factory() as uow:
            event, instructor = self._room(uow.session, slug, user_id)
            if not instructor:
                raise AuthorizationError("Only event instructors can moderate the live session.")
            item = uow.session.scalar(
                select(model).where(model.id == item_id, model.event_id == event.id)
            )
            if item is None:
                raise NotFoundError("Message does not exist in this event.")
            if kind == "questions":
                uow.session.execute(
                    delete(EventLiveVote).where(EventLiveVote.question_id == item_id)
                )
            uow.session.delete(item)
            uow.commit()


def live_service_from_container(container):
    return EventLiveService(lambda: SqlAlchemyUnitOfWork(container.database.session_factory))
