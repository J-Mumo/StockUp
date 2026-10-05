"""Persistent user notifications and delivery preferences.

``Alert`` is a rule configured by a user. A ``Notification`` is an immutable
event created when a rule fires (or a recommendation changes). Keeping these
separate lets StockUp retain an inbox/history and record email delivery
without re-triggering an investment condition.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class NotificationPreference(Base):
    """Per-user controls for StockUp's in-app and email notifications."""

    __tablename__ = "notification_preferences"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False, index=True
    )
    in_app_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    email_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # ``immediate`` is implemented now. ``daily_digest`` is retained as the
    # stable public preference value for the scheduled digest follow-up.
    email_frequency: Mapped[str] = mapped_column(String(20), default="immediate", nullable=False)
    price_alerts_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    valuation_alerts_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    recommendation_alerts_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    opportunity_alerts_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    user = relationship("User", back_populates="notification_preference")


class Notification(Base):
    """A user-visible notification with durable email delivery status."""

    __tablename__ = "notifications"
    __table_args__ = (
        Index("ix_notifications_user_read_created", "user_id", "read_at", "created_at"),
        Index("ix_notifications_dedupe_key", "dedupe_key", unique=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    company_id: Mapped[int | None] = mapped_column(
        ForeignKey("companies.id", ondelete="SET NULL"), nullable=True, index=True
    )
    alert_id: Mapped[int | None] = mapped_column(
        ForeignKey("alerts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    notification_type: Mapped[str] = mapped_column(String(50), nullable=False)
    priority: Mapped[str] = mapped_column(String(20), default="normal", nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    link_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    dedupe_key: Mapped[str] = mapped_column(String(255), nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    email_status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    email_attempted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    email_sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    email_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="notifications")
    company = relationship("Company")
    alert = relationship("Alert")