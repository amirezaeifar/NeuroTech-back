"""Persistent guest support requests and their conversation history."""

from sqlalchemy import JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, TimestampMixin, UuidPrimaryKeyMixin


class SupportTicket(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "support_tickets"

    tracking_token: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    phone: Mapped[str] = mapped_column(String(24), nullable=False)
    email: Mapped[str | None] = mapped_column(String(254))
    subject: Mapped[str] = mapped_column(String(240), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False, default="general", index=True)
    locale: Mapped[str] = mapped_column(String(5), nullable=False, default="fa")
    status: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    history: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
