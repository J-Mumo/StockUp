"""Schemas for per-company AI chat."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


class CompanyChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(..., min_length=1, max_length=4000)


class CompanyChatRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=4000)
    history: list[CompanyChatMessage] = Field(default_factory=list)
    verify_online: bool = True


class OnlineValidationSummary(BaseModel):
    status: Literal["match", "mismatch", "partial", "unavailable"]
    source: str | None = None
    db_price_date: date | None = None
    db_close_price: float | None = None
    online_price_date: date | None = None
    online_close_price: float | None = None
    price_diff_pct: float | None = None
    note: str | None = None


class CompanyChatContextMeta(BaseModel):
    latest_db_price_date: date | None = None
    latest_valuation_date: date | None = None
    latest_financial_year: int | None = None


class CompanyChatResponse(BaseModel):
    answer: str
    company_ticker: str
    online_validation: OnlineValidationSummary
    context_meta: CompanyChatContextMeta


class ChatHistoryItem(BaseModel):
    id: int
    role: Literal["user", "assistant"]
    content: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ChatHistorySaveRequest(BaseModel):
    messages: list[CompanyChatMessage]


class ChatHistoryResponse(BaseModel):
    company_id: int
    user_id: int
    messages: list[ChatHistoryItem]

