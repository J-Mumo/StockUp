"""Schemas for StockUp's notification inbox and delivery preferences."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class NotificationPreferenceUpdate(BaseModel):
    in_app_enabled: bool | None = None
    email_enabled: bool | None = None
    email_frequency: str | None = Field(None, pattern=r"^(immediate|daily_digest|off)$")
    price_alerts_enabled: bool | None = None
    valuation_alerts_enabled: bool | None = None
    recommendation_alerts_enabled: bool | None = None
    opportunity_alerts_enabled: bool | None = None


class NotificationPreferenceResponse(BaseModel):
    in_app_enabled: bool
    email_enabled: bool
    email_frequency: str
    price_alerts_enabled: bool
    valuation_alerts_enabled: bool
    recommendation_alerts_enabled: bool
    opportunity_alerts_enabled: bool

    model_config = {"from_attributes": True}


class NotificationResponse(BaseModel):
    id: int
    company_id: int | None = None
    alert_id: int | None = None
    notification_type: str
    priority: str
    title: str
    body: str
    link_path: str | None = None
    payload: dict[str, Any] | None = None
    read_at: datetime | None = None
    email_status: str
    email_sent_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class NotificationListResponse(BaseModel):
    notifications: list[NotificationResponse]
    unread_count: int