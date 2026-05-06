"""Pydantic schemas for watchlist APIs."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Watchlist CRUD
# ---------------------------------------------------------------------------

class WatchlistCreate(BaseModel):
    """Payload for creating a new watchlist."""
    name: str = Field(..., min_length=1, max_length=100)


class WatchlistResponse(BaseModel):
    """Watchlist response schema."""
    id: int
    user_id: int
    name: str
    item_count: int = 0
    created_at: datetime

    model_config = {"from_attributes": True}


class WatchlistDetailResponse(BaseModel):
    """Watchlist detail with items."""
    id: int
    user_id: int
    name: str
    created_at: datetime
    items: list[WatchlistItemResponse] = []

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Watchlist Items
# ---------------------------------------------------------------------------

class WatchlistItemCreate(BaseModel):
    """Payload for adding a company to a watchlist."""
    company_id: int
    target_buy_price: float | None = Field(None, gt=0)
    target_sell_price: float | None = Field(None, gt=0)
    notes: str | None = None


class WatchlistItemUpdate(BaseModel):
    """Payload for updating a watchlist item."""
    target_buy_price: float | None = Field(None, gt=0)
    target_sell_price: float | None = Field(None, gt=0)
    notes: str | None = None


class WatchlistItemResponse(BaseModel):
    """Watchlist item response schema."""
    id: int
    watchlist_id: int
    company_id: int
    company_name: str | None = None
    company_ticker: str | None = None
    target_buy_price: float | None = None
    target_sell_price: float | None = None
    current_price: float | None = None
    notes: str | None = None
    added_at: datetime

    model_config = {"from_attributes": True}


# Fix forward reference
WatchlistDetailResponse.model_rebuild()
