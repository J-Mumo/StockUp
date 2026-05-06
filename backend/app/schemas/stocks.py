"""Pydantic schemas for the stocks API — markets, companies, prices, financials, valuations."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Market
# ---------------------------------------------------------------------------

class MarketResponse(BaseModel):
    id: int
    name: str
    code: str
    country: str
    currency: str
    is_active: bool
    company_count: int = 0

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Company
# ---------------------------------------------------------------------------

class CompanyListItem(BaseModel):
    id: int
    ticker_symbol: str
    name: str
    sector: str | None = None
    is_active: bool
    latest_price: float | None = None
    latest_change_pct: float | None = None
    latest_price_date: date | None = None
    intrinsic_value: float | None = None
    margin_of_safety_pct: float | None = None
    recommendation: str | None = None
    index_membership: str | None = None  # "NSE 20", "NSE 25", or null

    model_config = {"from_attributes": True}


class CompanyDetail(BaseModel):
    id: int
    market_id: int
    name: str
    ticker_symbol: str
    yfinance_ticker: str | None = None
    sector: str | None = None
    industry: str | None = None
    description: str | None = None
    website: str | None = None
    shares_outstanding: int | None = None
    is_active: bool
    latest_price: float | None = None
    latest_change_pct: float | None = None
    latest_price_date: date | None = None
    latest_valuation: ValuationResponse | None = None

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Price History
# ---------------------------------------------------------------------------

class PriceRecord(BaseModel):
    id: int
    price_date: date
    open_price: float | None = None
    high_price: float | None = None
    low_price: float | None = None
    close_price: float
    volume: int | None = None
    change_percent: float | None = None
    source: str

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Financial Statement
# ---------------------------------------------------------------------------

class FinancialStatementCreate(BaseModel):
    """Payload for creating / updating a financial statement."""
    fiscal_year: int = Field(..., ge=1900, le=2100)
    period_type: str = Field("annual", pattern=r"^(annual|quarterly)$")

    # Income Statement
    revenue: float | None = None
    net_income: float | None = None
    earnings_per_share: float | None = None

    # Balance Sheet
    total_assets: float | None = None
    total_liabilities: float | None = None
    total_equity: float | None = None
    shareholders_equity: float | None = None
    book_value_per_share: float | None = None

    # Cash Flow Statement
    operating_cash_flow: float | None = None
    capital_expenditures: float | None = None
    free_cash_flow: float | None = None
    dividends_per_share: float | None = None

    # Ratios
    return_on_equity: float | None = None
    debt_to_equity: float | None = None
    current_ratio: float | None = None

    # Metadata
    notes: str | None = None
    report_date: date | None = None


class FinancialStatementUpdate(BaseModel):
    """Payload for partial update of a financial statement."""
    fiscal_year: int | None = Field(None, ge=1900, le=2100)
    period_type: str | None = Field(None, pattern=r"^(annual|quarterly)$")

    revenue: float | None = None
    net_income: float | None = None
    earnings_per_share: float | None = None

    total_assets: float | None = None
    total_liabilities: float | None = None
    total_equity: float | None = None
    shareholders_equity: float | None = None
    book_value_per_share: float | None = None

    operating_cash_flow: float | None = None
    capital_expenditures: float | None = None
    free_cash_flow: float | None = None
    dividends_per_share: float | None = None

    return_on_equity: float | None = None
    debt_to_equity: float | None = None
    current_ratio: float | None = None

    notes: str | None = None
    report_date: date | None = None


class FinancialStatementResponse(BaseModel):
    id: int
    company_id: int
    fiscal_year: int
    period_type: str

    revenue: float | None = None
    net_income: float | None = None
    earnings_per_share: float | None = None

    total_assets: float | None = None
    total_liabilities: float | None = None
    total_equity: float | None = None
    shareholders_equity: float | None = None
    book_value_per_share: float | None = None

    operating_cash_flow: float | None = None
    capital_expenditures: float | None = None
    free_cash_flow: float | None = None
    dividends_per_share: float | None = None

    return_on_equity: float | None = None
    debt_to_equity: float | None = None
    current_ratio: float | None = None

    notes: str | None = None
    report_date: date | None = None
    entered_by_user_id: int | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Intrinsic Value / Valuation
# ---------------------------------------------------------------------------

class ValuationResponse(BaseModel):
    id: int
    company_id: int
    valuation_date: date

    dcf_value: float | None = None
    epv_value: float | None = None
    book_value_estimate: float | None = None
    weighted_intrinsic_value: float | None = None

    current_market_price: float | None = None
    margin_of_safety_pct: float | None = None

    recommendation: str | None = None
    recommendation_reason: str | None = None

    assumptions: dict[str, Any] | None = None
    calculation_details: dict[str, Any] | None = None

    calculated_at: datetime

    model_config = {"from_attributes": True}


class ValuationHistoryPoint(BaseModel):
    """A single data point for the valuation trends chart."""
    date: date
    market_price: float | None = None
    intrinsic_value: float | None = None
    margin_of_safety_pct: float | None = None

    model_config = {"from_attributes": True}


# Needed so CompanyDetail can reference ValuationResponse
CompanyDetail.model_rebuild()
