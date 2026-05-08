"""Pydantic schemas for portfolio, transactions, holdings, and performance APIs."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Portfolio CRUD
# ---------------------------------------------------------------------------

class PortfolioCreate(BaseModel):
    """Payload for creating a new portfolio."""
    name: str = Field(..., min_length=1, max_length=100)
    description: str | None = None
    initial_capital: float | None = Field(None, ge=0)
    currency: str = Field("KES", max_length=10)


class PortfolioUpdate(BaseModel):
    """Payload for updating a portfolio."""
    name: str | None = Field(None, min_length=1, max_length=100)
    description: str | None = None
    initial_capital: float | None = Field(None, ge=0)
    currency: str | None = Field(None, max_length=10)


class PortfolioResponse(BaseModel):
    """Portfolio response schema."""
    id: int
    user_id: int
    name: str
    description: str | None = None
    initial_capital: float | None = None
    currency: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Transactions
# ---------------------------------------------------------------------------

class TransactionCreate(BaseModel):
    """Payload for recording a buy/sell transaction."""
    company_id: int
    transaction_type: str = Field(
        ...,
        pattern=r"^(buy|sell)$",
        description="Transaction type: buy or sell",
    )
    quantity: float = Field(..., gt=0)
    price_per_share: float = Field(..., gt=0)
    total_amount: float | None = Field(None, ge=0, description="Auto-calculated if not provided")
    fees: float = Field(0, ge=0)
    transaction_date: date
    notes: str | None = None


class TransactionUpdate(BaseModel):
    """Payload for updating an existing transaction."""
    transaction_type: str | None = Field(None, pattern=r"^(buy|sell)$")
    quantity: float | None = Field(None, gt=0)
    price_per_share: float | None = Field(None, gt=0)
    transaction_date: date | None = None
    notes: str | None = None


class TransactionResponse(BaseModel):
    """Transaction response schema."""
    id: int
    portfolio_id: int
    company_id: int
    company_name: str | None = None
    company_ticker: str | None = None
    transaction_type: str
    quantity: float
    price_per_share: float
    total_amount: float
    fees: float | None = 0
    transaction_date: date
    notes: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Holdings
# ---------------------------------------------------------------------------

class HoldingResponse(BaseModel):
    """Current holding for a single company in a portfolio."""
    company_id: int
    company_name: str
    company_ticker: str
    total_shares: float
    average_cost_basis: float
    total_cost: float
    current_price: float | None = None
    current_value: float | None = None
    unrealized_pnl: float | None = None
    unrealized_pnl_pct: float | None = None


class HoldingsListResponse(BaseModel):
    """List of all current holdings in a portfolio."""
    portfolio_id: int
    portfolio_name: str
    holdings: list[HoldingResponse] = []
    total_invested: float = 0
    total_current_value: float | None = None
    total_unrealized_pnl: float | None = None


# ---------------------------------------------------------------------------
# Performance
# ---------------------------------------------------------------------------

class PerformanceResponse(BaseModel):
    """Portfolio performance metrics."""
    portfolio_id: int
    portfolio_name: str
    initial_capital: float | None = None
    total_invested: float
    total_current_value: float | None = None
    cash_from_sales: float = 0
    total_fees_paid: float = 0
    unrealized_pnl: float | None = None
    realized_pnl: float = 0
    total_pnl: float | None = None
    total_return_pct: float | None = None
    cagr: float | None = None
    allocations: list[AllocationItem] = []


class AllocationItem(BaseModel):
    """Allocation percentage for a single holding."""
    company_id: int
    company_name: str
    company_ticker: str
    current_value: float
    allocation_pct: float


# Fix forward reference
PerformanceResponse.model_rebuild()
