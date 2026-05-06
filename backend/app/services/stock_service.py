"""Stock service — business logic for markets, companies, prices, financials, valuations."""

from __future__ import annotations

from datetime import date
from typing import Sequence

from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from app.models.market import Market
from app.models.company import Company
from app.models.price_history import PriceHistory
from app.models.financial_statement import FinancialStatement
from app.models.intrinsic_value import IntrinsicValue
from app.schemas.stocks import (
    CompanyDetail,
    CompanyListItem,
    FinancialStatementCreate,
    FinancialStatementUpdate,
    MarketResponse,
    PriceRecord,
    FinancialStatementResponse,
    ValuationResponse,
)


# ---------------------------------------------------------------------------
# NSE Index Constituents (as of 2025)
# ---------------------------------------------------------------------------

NSE_20_TICKERS = {
    "SCOM", "EQTY", "KCB", "ABSA", "COOP", "SCBK", "BAT", "EABL", "BAMB",
    "KNRE", "LKNL", "KQ", "SBIC", "NCBA", "DIAM", "TOTL", "NMG", "CARB",
    "KEGN", "CTUM",
}

NSE_25_TICKERS = {
    "SCOM", "EQTY", "KCB", "ABSA", "COOP", "SCBK", "EABL", "BAMB",
    "BAT", "KNRE", "NCBA", "DIAM", "KQ", "SBIC", "CTUM", "LKNL",
    "TOTL", "NMG", "KEGN", "CARB", "BRIT", "JUB", "KUKZ", "LIMT", "BKG",
}


# ---------------------------------------------------------------------------
# Markets
# ---------------------------------------------------------------------------

def list_markets(db: Session) -> list[MarketResponse]:
    """Return all markets with their company counts."""
    markets = db.query(Market).order_by(Market.name).all()
    results: list[MarketResponse] = []
    for market in markets:
        count = (
            db.query(func.count(Company.id))
            .filter(Company.market_id == market.id)
            .scalar()
        )
        results.append(
            MarketResponse(
                id=market.id,
                name=market.name,
                code=market.code,
                country=market.country,
                currency=market.currency,
                is_active=market.is_active,
                company_count=count or 0,
            )
        )
    return results


# ---------------------------------------------------------------------------
# Companies
# ---------------------------------------------------------------------------

def _latest_price_map(
    db: Session, company_ids: list[int]
) -> dict[int, PriceHistory]:
    """Build a company_id → latest PriceHistory mapping in two queries."""
    if not company_ids:
        return {}

    latest_date_subq = (
        db.query(
            PriceHistory.company_id,
            func.max(PriceHistory.price_date).label("max_date"),
        )
        .filter(PriceHistory.company_id.in_(company_ids))
        .group_by(PriceHistory.company_id)
        .subquery()
    )

    latest_prices: Sequence[PriceHistory] = (
        db.query(PriceHistory)
        .join(
            latest_date_subq,
            (PriceHistory.company_id == latest_date_subq.c.company_id)
            & (PriceHistory.price_date == latest_date_subq.c.max_date),
        )
        .all()
    )
    return {p.company_id: p for p in latest_prices}


def _latest_valuation_map(
    db: Session, company_ids: list[int]
) -> dict[int, IntrinsicValue]:
    """Build a company_id → latest IntrinsicValue mapping."""
    if not company_ids:
        return {}

    latest_date_subq = (
        db.query(
            IntrinsicValue.company_id,
            func.max(IntrinsicValue.valuation_date).label("max_date"),
        )
        .filter(IntrinsicValue.company_id.in_(company_ids))
        .group_by(IntrinsicValue.company_id)
        .subquery()
    )

    latest_vals: Sequence[IntrinsicValue] = (
        db.query(IntrinsicValue)
        .join(
            latest_date_subq,
            (IntrinsicValue.company_id == latest_date_subq.c.company_id)
            & (IntrinsicValue.valuation_date == latest_date_subq.c.max_date),
        )
        .all()
    )
    return {v.company_id: v for v in latest_vals}


def _get_index_membership(ticker: str) -> str | None:
    """Determine NSE index membership for a ticker."""
    if ticker in NSE_20_TICKERS:
        return "NSE 20"
    if ticker in NSE_25_TICKERS:
        return "NSE 25"
    return None


def _enrich_companies(
    db: Session, companies: Sequence[Company]
) -> list[CompanyListItem]:
    """Attach latest price data, valuation info, and index membership."""
    if not companies:
        return []

    company_ids = [c.id for c in companies]
    price_map = _latest_price_map(db, company_ids)
    valuation_map = _latest_valuation_map(db, company_ids)

    results: list[CompanyListItem] = []
    for company in companies:
        price = price_map.get(company.id)
        val = valuation_map.get(company.id)
        results.append(
            CompanyListItem(
                id=company.id,
                ticker_symbol=company.ticker_symbol,
                name=company.name,
                sector=company.sector,
                is_active=company.is_active,
                latest_price=float(price.close_price) if price else None,
                latest_change_pct=(
                    float(price.change_percent)
                    if price and price.change_percent
                    else None
                ),
                latest_price_date=price.price_date if price else None,
                intrinsic_value=(
                    float(val.weighted_intrinsic_value)
                    if val and val.weighted_intrinsic_value
                    else None
                ),
                margin_of_safety_pct=(
                    float(val.margin_of_safety_pct)
                    if val and val.margin_of_safety_pct
                    else None
                ),
                recommendation=val.recommendation if val else None,
                index_membership=_get_index_membership(company.ticker_symbol),
            )
        )
    return results


def list_market_companies(db: Session, market_id: int) -> list[CompanyListItem]:
    """List all active companies in a given market."""
    market = db.query(Market).filter(Market.id == market_id).first()
    if market is None:
        return None  # signal 404 to the router
    companies = (
        db.query(Company)
        .filter(Company.market_id == market_id, Company.is_active == True)
        .order_by(Company.ticker_symbol)
        .all()
    )
    return _enrich_companies(db, companies)


def list_companies(
    db: Session,
    sector: str | None = None,
    search: str | None = None,
) -> list[CompanyListItem]:
    """List all active companies with optional sector / search filters."""
    query = db.query(Company).filter(Company.is_active == True)
    if sector:
        query = query.filter(Company.sector == sector)
    if search:
        term = f"%{search}%"
        query = query.filter(
            (Company.name.ilike(term)) | (Company.ticker_symbol.ilike(term))
        )
    companies = query.order_by(Company.ticker_symbol).all()
    return _enrich_companies(db, companies)


def list_sectors(db: Session) -> list[str]:
    """Return distinct, sorted sector names."""
    rows = (
        db.query(Company.sector)
        .filter(Company.sector.isnot(None), Company.is_active == True)
        .distinct()
        .order_by(Company.sector)
        .all()
    )
    return [r[0] for r in rows]


def get_company_detail(db: Session, company_id: int) -> CompanyDetail | None:
    """Return full company detail with latest price and latest valuation."""
    company = db.query(Company).filter(Company.id == company_id).first()
    if company is None:
        return None

    # Latest price
    latest_price = (
        db.query(PriceHistory)
        .filter(PriceHistory.company_id == company.id)
        .order_by(desc(PriceHistory.price_date))
        .first()
    )

    # Latest valuation
    latest_val = (
        db.query(IntrinsicValue)
        .filter(IntrinsicValue.company_id == company.id)
        .order_by(desc(IntrinsicValue.valuation_date))
        .first()
    )

    return CompanyDetail(
        id=company.id,
        market_id=company.market_id,
        name=company.name,
        ticker_symbol=company.ticker_symbol,
        yfinance_ticker=company.yfinance_ticker,
        sector=company.sector,
        industry=company.industry,
        description=company.description,
        website=company.website,
        shares_outstanding=company.shares_outstanding,
        is_active=company.is_active,
        latest_price=float(latest_price.close_price) if latest_price else None,
        latest_change_pct=(
            float(latest_price.change_percent)
            if latest_price and latest_price.change_percent
            else None
        ),
        latest_price_date=latest_price.price_date if latest_price else None,
        latest_valuation=_valuation_to_schema(latest_val) if latest_val else None,
    )


# ---------------------------------------------------------------------------
# Prices
# ---------------------------------------------------------------------------

def get_company_prices(
    db: Session,
    company_id: int,
    start_date: date | None = None,
    end_date: date | None = None,
    limit: int = 365,
) -> list[PriceRecord] | None:
    """Return historical prices for a company, or None if company missing."""
    company = db.query(Company).filter(Company.id == company_id).first()
    if company is None:
        return None

    query = db.query(PriceHistory).filter(PriceHistory.company_id == company_id)
    if start_date:
        query = query.filter(PriceHistory.price_date >= start_date)
    if end_date:
        query = query.filter(PriceHistory.price_date <= end_date)

    prices = query.order_by(desc(PriceHistory.price_date)).limit(limit).all()

    return [
        PriceRecord(
            id=p.id,
            price_date=p.price_date,
            open_price=float(p.open_price) if p.open_price else None,
            high_price=float(p.high_price) if p.high_price else None,
            low_price=float(p.low_price) if p.low_price else None,
            close_price=float(p.close_price),
            volume=p.volume,
            change_percent=(
                float(p.change_percent) if p.change_percent else None
            ),
            source=p.source,
        )
        for p in prices
    ]


# ---------------------------------------------------------------------------
# Financial Statements
# ---------------------------------------------------------------------------

def _financial_to_schema(fs: FinancialStatement) -> FinancialStatementResponse:
    return FinancialStatementResponse(
        id=fs.id,
        company_id=fs.company_id,
        fiscal_year=fs.fiscal_year,
        period_type=fs.period_type,
        revenue=float(fs.revenue) if fs.revenue is not None else None,
        net_income=float(fs.net_income) if fs.net_income is not None else None,
        earnings_per_share=float(fs.earnings_per_share) if fs.earnings_per_share is not None else None,
        total_assets=float(fs.total_assets) if fs.total_assets is not None else None,
        total_liabilities=float(fs.total_liabilities) if fs.total_liabilities is not None else None,
        total_equity=float(fs.total_equity) if fs.total_equity is not None else None,
        shareholders_equity=float(fs.shareholders_equity) if fs.shareholders_equity is not None else None,
        book_value_per_share=float(fs.book_value_per_share) if fs.book_value_per_share is not None else None,
        operating_cash_flow=float(fs.operating_cash_flow) if fs.operating_cash_flow is not None else None,
        capital_expenditures=float(fs.capital_expenditures) if fs.capital_expenditures is not None else None,
        free_cash_flow=float(fs.free_cash_flow) if fs.free_cash_flow is not None else None,
        dividends_per_share=float(fs.dividends_per_share) if fs.dividends_per_share is not None else None,
        return_on_equity=float(fs.return_on_equity) if fs.return_on_equity is not None else None,
        debt_to_equity=float(fs.debt_to_equity) if fs.debt_to_equity is not None else None,
        current_ratio=float(fs.current_ratio) if fs.current_ratio is not None else None,
        notes=fs.notes,
        report_date=fs.report_date,
        entered_by_user_id=fs.entered_by_user_id,
        created_at=fs.created_at,
        updated_at=fs.updated_at,
    )


def list_financials(
    db: Session, company_id: int
) -> list[FinancialStatementResponse] | None:
    """List financial statements for a company ordered by fiscal year desc."""
    company = db.query(Company).filter(Company.id == company_id).first()
    if company is None:
        return None

    statements = (
        db.query(FinancialStatement)
        .filter(FinancialStatement.company_id == company_id)
        .order_by(desc(FinancialStatement.fiscal_year))
        .all()
    )
    return [_financial_to_schema(fs) for fs in statements]


def create_financial(
    db: Session,
    company_id: int,
    data: FinancialStatementCreate,
    user_id: int,
) -> FinancialStatementResponse | None:
    """Create a new financial statement. Returns None if company not found."""
    company = db.query(Company).filter(Company.id == company_id).first()
    if company is None:
        return None

    fs = FinancialStatement(
        company_id=company_id,
        entered_by_user_id=user_id,
        **data.model_dump(exclude_none=False),
    )
    db.add(fs)
    db.commit()
    db.refresh(fs)
    return _financial_to_schema(fs)


def update_financial(
    db: Session,
    company_id: int,
    financial_id: int,
    data: FinancialStatementUpdate,
) -> FinancialStatementResponse | str:
    """Update a financial statement.

    Returns:
        FinancialStatementResponse on success,
        "company_not_found" or "financial_not_found" strings on failure.
    """
    company = db.query(Company).filter(Company.id == company_id).first()
    if company is None:
        return "company_not_found"

    fs = (
        db.query(FinancialStatement)
        .filter(
            FinancialStatement.id == financial_id,
            FinancialStatement.company_id == company_id,
        )
        .first()
    )
    if fs is None:
        return "financial_not_found"

    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(fs, key, value)

    db.commit()
    db.refresh(fs)
    return _financial_to_schema(fs)


def delete_financial(
    db: Session, company_id: int, financial_id: int
) -> str:
    """Delete a financial statement.

    Returns "ok", "company_not_found", or "financial_not_found".
    """
    company = db.query(Company).filter(Company.id == company_id).first()
    if company is None:
        return "company_not_found"

    fs = (
        db.query(FinancialStatement)
        .filter(
            FinancialStatement.id == financial_id,
            FinancialStatement.company_id == company_id,
        )
        .first()
    )
    if fs is None:
        return "financial_not_found"

    db.delete(fs)
    db.commit()
    return "ok"


# ---------------------------------------------------------------------------
# Valuations
# ---------------------------------------------------------------------------

def _valuation_to_schema(iv: IntrinsicValue) -> ValuationResponse:
    return ValuationResponse(
        id=iv.id,
        company_id=iv.company_id,
        valuation_date=iv.valuation_date,
        dcf_value=float(iv.dcf_value) if iv.dcf_value is not None else None,
        epv_value=float(iv.epv_value) if iv.epv_value is not None else None,
        book_value_estimate=float(iv.book_value_estimate) if iv.book_value_estimate is not None else None,
        weighted_intrinsic_value=float(iv.weighted_intrinsic_value) if iv.weighted_intrinsic_value is not None else None,
        current_market_price=float(iv.current_market_price) if iv.current_market_price is not None else None,
        margin_of_safety_pct=float(iv.margin_of_safety_pct) if iv.margin_of_safety_pct is not None else None,
        recommendation=iv.recommendation,
        recommendation_reason=iv.recommendation_reason,
        assumptions=iv.assumptions,
        calculation_details=iv.calculation_details,
        calculated_at=iv.calculated_at,
    )


def list_valuations(
    db: Session, company_id: int
) -> list[ValuationResponse] | None:
    """List valuation history for a company, newest first."""
    company = db.query(Company).filter(Company.id == company_id).first()
    if company is None:
        return None

    valuations = (
        db.query(IntrinsicValue)
        .filter(IntrinsicValue.company_id == company_id)
        .order_by(desc(IntrinsicValue.valuation_date))
        .all()
    )
    return [_valuation_to_schema(v) for v in valuations]


def get_latest_valuation(
    db: Session, company_id: int
) -> ValuationResponse | str:
    """Get the latest valuation for a company.

    Returns ValuationResponse, "company_not_found", or "no_valuation".
    """
    company = db.query(Company).filter(Company.id == company_id).first()
    if company is None:
        return "company_not_found"

    latest = (
        db.query(IntrinsicValue)
        .filter(IntrinsicValue.company_id == company_id)
        .order_by(desc(IntrinsicValue.valuation_date))
        .first()
    )
    if latest is None:
        return "no_valuation"

    return _valuation_to_schema(latest)


def get_valuation_trend(
    db: Session, company_id: int, days: int = 365
) -> list[dict]:
    """Get valuation history merged with price history for trend chart.

    Returns a list of data points with date, market_price, and intrinsic_value.
    Prices come from daily price_history; IV comes from intrinsic_values table.
    IV is forward-filled across daily price dates for chart rendering.
    """
    from datetime import timedelta

    cutoff = date.today() - timedelta(days=days)

    # Get price history for the period
    prices = (
        db.query(PriceHistory)
        .filter(
            PriceHistory.company_id == company_id,
            PriceHistory.price_date >= cutoff,
        )
        .order_by(PriceHistory.price_date)
        .all()
    )

    # Get all valuation points for the period
    valuations = (
        db.query(IntrinsicValue)
        .filter(
            IntrinsicValue.company_id == company_id,
            IntrinsicValue.valuation_date >= cutoff,
        )
        .order_by(IntrinsicValue.valuation_date)
        .all()
    )

    # Build a date → IV map (use latest IV for each date)
    iv_by_date: dict[date, float] = {}
    for v in valuations:
        if v.weighted_intrinsic_value:
            iv_by_date[v.valuation_date] = float(v.weighted_intrinsic_value)

    # Build the merged time series
    # Forward-fill IV: carry the most recent IV value forward across price dates
    result = []
    current_iv: float | None = None

    # Sort all IV dates to enable forward-fill
    iv_dates_sorted = sorted(iv_by_date.keys())

    for price in prices:
        # Update current_iv if there's a valuation on or before this price date
        for iv_date in iv_dates_sorted:
            if iv_date <= price.price_date:
                current_iv = iv_by_date[iv_date]
            else:
                break

        mos = None
        if current_iv and price.close_price and current_iv > 0:
            mos = (current_iv - float(price.close_price)) / current_iv

        result.append({
            "date": price.price_date,
            "market_price": float(price.close_price) if price.close_price else None,
            "intrinsic_value": current_iv,
            "margin_of_safety_pct": round(mos, 4) if mos is not None else None,
        })

    # If no prices but we have valuations, return valuation points alone
    if not result and valuations:
        for v in valuations:
            result.append({
                "date": v.valuation_date,
                "market_price": float(v.current_market_price) if v.current_market_price else None,
                "intrinsic_value": float(v.weighted_intrinsic_value) if v.weighted_intrinsic_value else None,
                "margin_of_safety_pct": float(v.margin_of_safety_pct) if v.margin_of_safety_pct else None,
            })

    return result
