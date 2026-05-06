"""Dashboard router — user dashboard summary endpoint.

Aggregates portfolio value, watchlist counts, unread alerts, and top
movers into a single API call for the frontend dashboard view.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.alert import Alert
from app.models.company import Company
from app.models.intrinsic_value import IntrinsicValue
from app.models.portfolio import Portfolio, PortfolioTransaction
from app.models.price_history import PriceHistory
from app.models.user import User
from app.models.watchlist import Watchlist, WatchlistItem

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------

class PortfolioSummary(BaseModel):
    """Summary of user's portfolio holdings."""
    total_portfolios: int = 0
    total_invested: float = 0.0
    total_current_value: float = 0.0
    total_pnl: float = 0.0
    pnl_pct: float | None = None


class AlertSummary(BaseModel):
    """Summary of user's alerts."""
    total_active: int = 0
    unread_triggered: int = 0
    recent_triggered: list[dict[str, Any]] = []


class WatchlistSummary(BaseModel):
    """Summary of user's watchlists."""
    total_watchlists: int = 0
    total_items: int = 0


class TopMover(BaseModel):
    """A stock with significant margin of safety."""
    company_id: int
    ticker: str
    company_name: str
    margin_of_safety_pct: float
    intrinsic_value: float | None = None
    market_price: float | None = None
    recommendation: str | None = None


class DashboardResponse(BaseModel):
    """Complete dashboard summary response."""
    portfolio: PortfolioSummary
    alerts: AlertSummary
    watchlists: WatchlistSummary
    top_undervalued: list[TopMover] = []
    market_stats: dict[str, Any] = {}


# ---------------------------------------------------------------------------
# Dashboard endpoint
# ---------------------------------------------------------------------------

@router.get("", response_model=DashboardResponse)
def get_dashboard(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get a comprehensive dashboard summary for the current user.

    Returns:
        - Portfolio summary: total invested, current value, P&L
        - Alert summary: active count, unread triggered, recent alerts
        - Watchlist summary: counts
        - Top undervalued stocks: companies with highest MOS
        - Market stats: total companies tracked, latest data date
    """
    portfolio_summary = _get_portfolio_summary(db, current_user.id)
    alert_summary = _get_alert_summary(db, current_user.id)
    watchlist_summary = _get_watchlist_summary(db, current_user.id)
    top_undervalued = _get_top_undervalued(db, limit=5)
    market_stats = _get_market_stats(db)

    return DashboardResponse(
        portfolio=portfolio_summary,
        alerts=alert_summary,
        watchlists=watchlist_summary,
        top_undervalued=top_undervalued,
        market_stats=market_stats,
    )


# ---------------------------------------------------------------------------
# Internal aggregation functions
# ---------------------------------------------------------------------------

def _get_portfolio_summary(db: Session, user_id: int) -> PortfolioSummary:
    """Aggregate portfolio data across all user portfolios."""
    portfolios = db.query(Portfolio).filter(Portfolio.user_id == user_id).all()

    if not portfolios:
        return PortfolioSummary()

    total_invested = 0.0
    total_current_value = 0.0

    for portfolio in portfolios:
        # Get all transactions for this portfolio
        transactions = (
            db.query(PortfolioTransaction)
            .filter(PortfolioTransaction.portfolio_id == portfolio.id)
            .all()
        )

        # Calculate holdings per company
        holdings: dict[int, float] = {}  # company_id -> shares
        cost_basis: dict[int, float] = {}  # company_id -> total cost

        for txn in transactions:
            cid = txn.company_id
            qty = float(txn.quantity)
            amount = float(txn.total_amount)

            if txn.transaction_type == "buy":
                holdings[cid] = holdings.get(cid, 0) + qty
                cost_basis[cid] = cost_basis.get(cid, 0) + amount
            elif txn.transaction_type == "sell":
                holdings[cid] = holdings.get(cid, 0) - qty
                # Reduce cost basis proportionally
                if holdings.get(cid, 0) + qty > 0:
                    proportion_sold = qty / (holdings.get(cid, 0) + qty)
                    cost_basis[cid] = cost_basis.get(cid, 0) * (1 - proportion_sold)

        # Get current prices for held companies
        held_companies = [cid for cid, shares in holdings.items() if shares > 0]
        if held_companies:
            latest_prices = _get_latest_prices(db, held_companies)

            for cid in held_companies:
                shares = holdings[cid]
                invested = cost_basis.get(cid, 0)
                total_invested += invested

                if cid in latest_prices:
                    total_current_value += shares * latest_prices[cid]

    pnl = total_current_value - total_invested
    pnl_pct = (pnl / total_invested * 100) if total_invested > 0 else None

    return PortfolioSummary(
        total_portfolios=len(portfolios),
        total_invested=round(total_invested, 2),
        total_current_value=round(total_current_value, 2),
        total_pnl=round(pnl, 2),
        pnl_pct=round(pnl_pct, 2) if pnl_pct is not None else None,
    )


def _get_alert_summary(db: Session, user_id: int) -> AlertSummary:
    """Summarize user's alert status."""
    total_active = (
        db.query(func.count(Alert.id))
        .filter(Alert.user_id == user_id, Alert.is_active == True)
        .scalar()
    ) or 0

    unread_triggered = (
        db.query(func.count(Alert.id))
        .filter(
            Alert.user_id == user_id,
            Alert.is_triggered == True,
            Alert.is_read == False,
        )
        .scalar()
    ) or 0

    # Get 5 most recent triggered alerts
    recent = (
        db.query(Alert)
        .filter(Alert.user_id == user_id, Alert.is_triggered == True)
        .order_by(desc(Alert.triggered_at))
        .limit(5)
        .all()
    )

    recent_triggered = [
        {
            "id": a.id,
            "company_id": a.company_id,
            "alert_type": a.alert_type,
            "message": a.message,
            "triggered_at": a.triggered_at.isoformat() if a.triggered_at else None,
            "is_read": a.is_read,
        }
        for a in recent
    ]

    return AlertSummary(
        total_active=total_active,
        unread_triggered=unread_triggered,
        recent_triggered=recent_triggered,
    )


def _get_watchlist_summary(db: Session, user_id: int) -> WatchlistSummary:
    """Count user's watchlists and total items."""
    watchlists = db.query(Watchlist).filter(Watchlist.user_id == user_id).all()
    total_items = sum(len(w.items) for w in watchlists)

    return WatchlistSummary(
        total_watchlists=len(watchlists),
        total_items=total_items,
    )


def _get_top_undervalued(db: Session, limit: int = 5) -> list[TopMover]:
    """Get top undervalued stocks by margin of safety.

    Returns companies with the highest positive MOS that have been
    valued recently.
    """
    # Get latest valuation per company with positive MOS
    # Using a subquery to get the latest valuation date per company
    from sqlalchemy import and_

    latest_valuations = (
        db.query(IntrinsicValue)
        .filter(
            IntrinsicValue.margin_of_safety_pct.isnot(None),
            IntrinsicValue.margin_of_safety_pct > 0,
        )
        .order_by(desc(IntrinsicValue.margin_of_safety_pct))
        .limit(limit * 2)  # Fetch extra to filter duplicates
        .all()
    )

    # Deduplicate by company (keep highest MOS per company)
    seen_companies: set[int] = set()
    top_movers: list[TopMover] = []

    for iv in latest_valuations:
        if iv.company_id in seen_companies:
            continue
        seen_companies.add(iv.company_id)

        company = db.query(Company).filter(Company.id == iv.company_id).first()
        if company is None:
            continue

        top_movers.append(TopMover(
            company_id=company.id,
            ticker=company.ticker_symbol,
            company_name=company.company_name,
            margin_of_safety_pct=round(float(iv.margin_of_safety_pct) * 100, 1),
            intrinsic_value=round(float(iv.weighted_intrinsic_value), 2) if iv.weighted_intrinsic_value else None,
            market_price=round(float(iv.current_market_price), 2) if iv.current_market_price else None,
            recommendation=iv.recommendation,
        ))

        if len(top_movers) >= limit:
            break

    return top_movers


def _get_market_stats(db: Session) -> dict[str, Any]:
    """Get overall market statistics."""
    total_companies = (
        db.query(func.count(Company.id))
        .filter(Company.is_active == True)
        .scalar()
    ) or 0

    # Latest price date
    latest_price = (
        db.query(func.max(PriceHistory.price_date)).scalar()
    )

    # Total price records
    total_prices = db.query(func.count(PriceHistory.id)).scalar() or 0

    # Companies with valuations
    companies_with_valuations = (
        db.query(func.count(func.distinct(IntrinsicValue.company_id))).scalar()
    ) or 0

    return {
        "total_companies": total_companies,
        "latest_price_date": latest_price.isoformat() if latest_price else None,
        "total_price_records": total_prices,
        "companies_with_valuations": companies_with_valuations,
    }


def _get_latest_prices(db: Session, company_ids: list[int]) -> dict[int, float]:
    """Get the latest closing price for each company."""
    from sqlalchemy import and_

    prices: dict[int, float] = {}
    for cid in company_ids:
        latest = (
            db.query(PriceHistory)
            .filter(PriceHistory.company_id == cid)
            .order_by(desc(PriceHistory.price_date))
            .first()
        )
        if latest:
            prices[cid] = float(latest.close_price)
    return prices
