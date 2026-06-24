"""Portfolio router — CRUD, transactions, holdings, and performance.

Endpoints:
    GET    /api/portfolio/                      — List user portfolios
    POST   /api/portfolio/                      — Create portfolio
    GET    /api/portfolio/{id}                  — Portfolio detail
    PUT    /api/portfolio/{id}                  — Update portfolio
    DELETE /api/portfolio/{id}                  — Delete portfolio
    POST   /api/portfolio/{id}/transactions     — Record buy/sell
    GET    /api/portfolio/{id}/transactions     — Transaction history
    GET    /api/portfolio/{id}/holdings         — Current holdings with cost basis
    GET    /api/portfolio/{id}/performance      — Performance metrics
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import case, desc, func
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.company import Company
from app.models.portfolio import Portfolio, PortfolioTransaction
from app.models.price_history import PriceHistory
from app.models.user import User
from app.schemas.portfolio import (
    AllocationItem,
    HoldingResponse,
    HoldingsListResponse,
    PerformanceResponse,
    PortfolioCreate,
    PortfolioResponse,
    PortfolioUpdate,
    RealizedListResponse,
    RealizedPositionResponse,
    TransactionCreate,
    TransactionResponse,
    TransactionUpdate,
)

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


# ---------------------------------------------------------------------------
# Portfolio CRUD (Step 36)
# ---------------------------------------------------------------------------

@router.get("", response_model=list[PortfolioResponse])
def list_portfolios(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all portfolios for the current user."""
    portfolios = (
        db.query(Portfolio)
        .filter(Portfolio.user_id == current_user.id)
        .order_by(desc(Portfolio.created_at))
        .all()
    )
    return [_portfolio_to_response(p) for p in portfolios]


@router.post("", response_model=PortfolioResponse, status_code=status.HTTP_201_CREATED)
def create_portfolio(
    data: PortfolioCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new portfolio."""
    portfolio = Portfolio(
        user_id=current_user.id,
        name=data.name,
        description=data.description,
        initial_capital=data.initial_capital,
        currency=data.currency,
    )
    db.add(portfolio)
    db.commit()
    db.refresh(portfolio)
    return _portfolio_to_response(portfolio)


@router.get("/{portfolio_id}", response_model=PortfolioResponse)
def get_portfolio(
    portfolio_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get a single portfolio by ID (must belong to current user)."""
    portfolio = _get_user_portfolio(db, portfolio_id, current_user.id)
    return _portfolio_to_response(portfolio)


@router.put("/{portfolio_id}", response_model=PortfolioResponse)
def update_portfolio(
    portfolio_id: int,
    data: PortfolioUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update an existing portfolio."""
    portfolio = _get_user_portfolio(db, portfolio_id, current_user.id)

    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(portfolio, key, value)

    db.commit()
    db.refresh(portfolio)
    return _portfolio_to_response(portfolio)


@router.delete("/{portfolio_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_portfolio(
    portfolio_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a portfolio and all its transactions."""
    portfolio = _get_user_portfolio(db, portfolio_id, current_user.id)
    db.delete(portfolio)
    db.commit()
    return None


# ---------------------------------------------------------------------------
# Transactions (Step 37)
# ---------------------------------------------------------------------------

@router.post(
    "/{portfolio_id}/transactions",
    response_model=TransactionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_transaction(
    portfolio_id: int,
    data: TransactionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Record a buy or sell transaction in a portfolio."""
    portfolio = _get_user_portfolio(db, portfolio_id, current_user.id)

    # Validate company exists
    company = db.query(Company).filter(Company.id == data.company_id).first()
    if company is None:
        raise HTTPException(status_code=404, detail="Company not found")

    # For sell transactions, validate sufficient shares
    if data.transaction_type == "sell":
        current_shares = _get_current_shares(db, portfolio_id, data.company_id)
        if current_shares < data.quantity:
            raise HTTPException(
                status_code=400,
                detail=f"Insufficient shares: have {current_shares}, trying to sell {data.quantity}",
            )

    # Auto-calculate total_amount if not provided
    total_amount = data.total_amount
    if total_amount is None:
        total_amount = data.quantity * data.price_per_share

    txn = PortfolioTransaction(
        portfolio_id=portfolio.id,
        company_id=data.company_id,
        transaction_type=data.transaction_type,
        quantity=data.quantity,
        price_per_share=data.price_per_share,
        total_amount=total_amount,
        fees=data.fees,
        transaction_date=data.transaction_date,
        notes=data.notes,
    )
    db.add(txn)
    db.commit()
    db.refresh(txn)
    return _transaction_to_response(txn, company)


@router.get("/{portfolio_id}/transactions", response_model=list[TransactionResponse])
def list_transactions(
    portfolio_id: int,
    company_id: int | None = Query(None, description="Filter by company"),
    transaction_type: str | None = Query(None, description="Filter: buy or sell"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List transactions for a portfolio with optional filters."""
    _get_user_portfolio(db, portfolio_id, current_user.id)

    query = db.query(PortfolioTransaction).filter(
        PortfolioTransaction.portfolio_id == portfolio_id
    )

    if company_id is not None:
        query = query.filter(PortfolioTransaction.company_id == company_id)
    if transaction_type is not None:
        query = query.filter(PortfolioTransaction.transaction_type == transaction_type)

    transactions = query.order_by(desc(PortfolioTransaction.transaction_date)).all()

    # Preload companies
    company_ids = {t.company_id for t in transactions}
    companies = {
        c.id: c for c in db.query(Company).filter(Company.id.in_(company_ids)).all()
    } if company_ids else {}

    return [_transaction_to_response(t, companies.get(t.company_id)) for t in transactions]


@router.put(
    "/{portfolio_id}/transactions/{transaction_id}",
    response_model=TransactionResponse,
)
def update_transaction(
    portfolio_id: int,
    transaction_id: int,
    payload: TransactionUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update an existing transaction."""
    _get_user_portfolio(db, portfolio_id, current_user.id)

    txn = (
        db.query(PortfolioTransaction)
        .filter(
            PortfolioTransaction.id == transaction_id,
            PortfolioTransaction.portfolio_id == portfolio_id,
        )
        .first()
    )
    if txn is None:
        raise HTTPException(status_code=404, detail="Transaction not found")

    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(txn, field, value)

    # Recalculate total_amount if quantity or price changed
    if "quantity" in update_data or "price_per_share" in update_data:
        txn.total_amount = txn.quantity * txn.price_per_share

    db.commit()
    db.refresh(txn)

    company = db.query(Company).filter(Company.id == txn.company_id).first()
    return _transaction_to_response(txn, company)


@router.delete(
    "/{portfolio_id}/transactions/{transaction_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_transaction(
    portfolio_id: int,
    transaction_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a transaction."""
    _get_user_portfolio(db, portfolio_id, current_user.id)

    txn = (
        db.query(PortfolioTransaction)
        .filter(
            PortfolioTransaction.id == transaction_id,
            PortfolioTransaction.portfolio_id == portfolio_id,
        )
        .first()
    )
    if txn is None:
        raise HTTPException(status_code=404, detail="Transaction not found")

    db.delete(txn)
    db.commit()


# ---------------------------------------------------------------------------
# Holdings (Step 38)
# ---------------------------------------------------------------------------

@router.get("/{portfolio_id}/holdings", response_model=HoldingsListResponse)
def get_holdings(
    portfolio_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get current holdings with average cost basis for a portfolio."""
    portfolio = _get_user_portfolio(db, portfolio_id, current_user.id)

    # Get all transactions for this portfolio
    transactions = (
        db.query(PortfolioTransaction)
        .filter(PortfolioTransaction.portfolio_id == portfolio_id)
        .order_by(PortfolioTransaction.transaction_date)
        .all()
    )

    # Calculate holdings per company using weighted average cost basis
    holdings_data = _calculate_holdings(transactions)

    # Load company info and current prices
    company_ids = list(holdings_data.keys())
    companies = {
        c.id: c for c in db.query(Company).filter(Company.id.in_(company_ids)).all()
    } if company_ids else {}

    # Get latest prices for all companies in portfolio
    latest_prices = _get_latest_prices(db, company_ids)

    # Build response
    holdings: list[HoldingResponse] = []
    total_invested = 0.0
    total_current_value = 0.0
    total_unrealized_pnl = 0.0
    has_prices = False

    for company_id, h_data in holdings_data.items():
        if h_data["shares"] <= 0:
            continue

        company = companies.get(company_id)
        if company is None:
            continue

        current_price = latest_prices.get(company_id)
        current_value = None
        unrealized_pnl = None
        unrealized_pnl_pct = None

        if current_price is not None:
            has_prices = True
            current_value = h_data["shares"] * current_price
            unrealized_pnl = current_value - h_data["total_cost"]
            if h_data["total_cost"] > 0:
                unrealized_pnl_pct = (unrealized_pnl / h_data["total_cost"]) * 100
            total_current_value += current_value
            total_unrealized_pnl += unrealized_pnl

        total_invested += h_data["total_cost"]

        holdings.append(HoldingResponse(
            company_id=company_id,
            company_name=company.name,
            company_ticker=company.ticker_symbol,
            total_shares=h_data["shares"],
            average_cost_basis=h_data["avg_cost"],
            total_cost=h_data["total_cost"],
            current_price=current_price,
            current_value=current_value,
            unrealized_pnl=unrealized_pnl,
            unrealized_pnl_pct=unrealized_pnl_pct,
        ))

    return HoldingsListResponse(
        portfolio_id=portfolio.id,
        portfolio_name=portfolio.name,
        holdings=holdings,
        total_invested=total_invested,
        total_current_value=total_current_value if has_prices else None,
        total_unrealized_pnl=total_unrealized_pnl if has_prices else None,
    )


# ---------------------------------------------------------------------------
# Realized positions (closed / partially-closed)
# ---------------------------------------------------------------------------

@router.get("/{portfolio_id}/realized", response_model=RealizedListResponse)
def get_realized_positions(
    portfolio_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Per-company realized P&L for sold shares (closed or partially closed)."""
    portfolio = _get_user_portfolio(db, portfolio_id, current_user.id)

    transactions = (
        db.query(PortfolioTransaction)
        .filter(PortfolioTransaction.portfolio_id == portfolio_id)
        .order_by(PortfolioTransaction.transaction_date)
        .all()
    )

    realized_by_company = _calculate_realized_by_company(transactions)
    if not realized_by_company:
        return RealizedListResponse(
            portfolio_id=portfolio.id,
            portfolio_name=portfolio.name,
        )

    company_ids = list(realized_by_company.keys())
    companies = {
        c.id: c for c in db.query(Company).filter(Company.id.in_(company_ids)).all()
    }

    positions: list[RealizedPositionResponse] = []
    total_pnl = 0.0
    total_proceeds = 0.0
    total_cost = 0.0

    for cid, data in realized_by_company.items():
        company = companies.get(cid)
        if company is None or data["quantity_sold"] <= 0:
            continue

        cost = data["total_buy_cost"]
        proceeds = data["total_sell_proceeds"]
        fees = data["realized_fees"]
        pnl = proceeds - cost - fees
        denom = cost + max(data["prorated_buy_fees"], 0)
        pct = (pnl / denom * 100) if denom > 0 else 0.0
        avg_buy = (cost / data["quantity_sold"]) if data["quantity_sold"] > 0 else 0.0
        avg_sell = (proceeds / data["quantity_sold"]) if data["quantity_sold"] > 0 else 0.0

        positions.append(RealizedPositionResponse(
            company_id=cid,
            company_name=company.name,
            company_ticker=company.ticker_symbol,
            quantity_sold=data["quantity_sold"],
            remaining_shares=data["remaining_shares"],
            avg_buy_price=avg_buy,
            avg_sell_price=avg_sell,
            total_buy_cost=cost,
            total_sell_proceeds=proceeds,
            realized_fees=fees,
            realized_pnl=pnl,
            realized_pnl_pct=pct,
            first_buy_date=data["first_buy_date"],
            last_sell_date=data["last_sell_date"],
            fully_closed=data["remaining_shares"] <= 0,
        ))
        total_pnl += pnl
        total_proceeds += proceeds
        total_cost += cost

    # Sort by absolute realized P&L impact, biggest first
    positions.sort(key=lambda p: abs(p.realized_pnl), reverse=True)

    return RealizedListResponse(
        portfolio_id=portfolio.id,
        portfolio_name=portfolio.name,
        positions=positions,
        total_realized_pnl=total_pnl,
        total_realized_proceeds=total_proceeds,
        total_realized_cost=total_cost,
    )


# ---------------------------------------------------------------------------
# Performance (Step 39)
# ---------------------------------------------------------------------------

@router.get("/{portfolio_id}/performance", response_model=PerformanceResponse)
def get_performance(
    portfolio_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get performance metrics for a portfolio: P&L, CAGR, allocation."""
    portfolio = _get_user_portfolio(db, portfolio_id, current_user.id)

    # Get all transactions
    transactions = (
        db.query(PortfolioTransaction)
        .filter(PortfolioTransaction.portfolio_id == portfolio_id)
        .order_by(PortfolioTransaction.transaction_date)
        .all()
    )

    # Calculate holdings
    holdings_data = _calculate_holdings(transactions)

    # Calculate realized P&L and other stats
    realized_pnl = 0.0
    total_invested = 0.0
    cash_from_sales = 0.0
    total_fees = 0.0
    first_txn_date: date | None = None

    for txn in transactions:
        total_fees += float(txn.fees) if txn.fees else 0.0
        if first_txn_date is None:
            first_txn_date = txn.transaction_date

    # Calculate realized P&L from sell transactions
    # We track cost basis per company to compute realized gains
    realized_pnl = _calculate_realized_pnl(transactions)

    # Total cost of current positions
    company_ids = [cid for cid, h in holdings_data.items() if h["shares"] > 0]
    latest_prices = _get_latest_prices(db, company_ids)

    companies = {
        c.id: c for c in db.query(Company).filter(Company.id.in_(company_ids)).all()
    } if company_ids else {}

    # Current portfolio value
    total_current_value = 0.0
    has_prices = False
    unrealized_pnl = 0.0
    allocations: list[AllocationItem] = []

    for company_id, h_data in holdings_data.items():
        if h_data["shares"] <= 0:
            continue
        total_invested += h_data["total_cost"]
        current_price = latest_prices.get(company_id)
        if current_price is not None:
            has_prices = True
            value = h_data["shares"] * current_price
            total_current_value += value
            unrealized_pnl += value - h_data["total_cost"]

    # Calculate cash from sales (sum of total_amount for sells)
    for txn in transactions:
        if txn.transaction_type == "sell":
            cash_from_sales += float(txn.total_amount)

    # Allocation percentages
    if has_prices and total_current_value > 0:
        for company_id, h_data in holdings_data.items():
            if h_data["shares"] <= 0:
                continue
            current_price = latest_prices.get(company_id)
            if current_price is not None:
                value = h_data["shares"] * current_price
                company = companies.get(company_id)
                if company:
                    allocations.append(AllocationItem(
                        company_id=company_id,
                        company_name=company.name,
                        company_ticker=company.ticker_symbol,
                        current_value=value,
                        allocation_pct=(value / total_current_value) * 100,
                    ))

    # CAGR calculation
    cagr = None
    if has_prices and first_txn_date and total_invested > 0:
        # Portfolio "ending value" = current holdings value + cash from sales
        ending_value = total_current_value + cash_from_sales
        beginning_value = total_invested + total_fees
        days = (date.today() - first_txn_date).days
        years = days / 365.25
        if years > 0 and beginning_value > 0 and ending_value > 0:
            cagr = ((ending_value / beginning_value) ** (1.0 / years)) - 1.0

    # Total P&L
    total_pnl = None
    total_return_pct = None
    if has_prices:
        total_pnl = unrealized_pnl + realized_pnl - total_fees
        if total_invested > 0:
            total_return_pct = (total_pnl / total_invested) * 100

    return PerformanceResponse(
        portfolio_id=portfolio.id,
        portfolio_name=portfolio.name,
        initial_capital=float(portfolio.initial_capital) if portfolio.initial_capital else None,
        total_invested=total_invested,
        total_current_value=total_current_value if has_prices else None,
        cash_from_sales=cash_from_sales,
        total_fees_paid=total_fees,
        unrealized_pnl=unrealized_pnl if has_prices else None,
        realized_pnl=realized_pnl,
        total_pnl=total_pnl,
        total_return_pct=total_return_pct,
        cagr=cagr,
        allocations=allocations,
    )


# ---------------------------------------------------------------------------
# Internal Helpers
# ---------------------------------------------------------------------------

def _get_user_portfolio(db: Session, portfolio_id: int, user_id: int) -> Portfolio:
    """Get portfolio ensuring it belongs to the user; raises 404 if not found."""
    portfolio = (
        db.query(Portfolio)
        .filter(Portfolio.id == portfolio_id, Portfolio.user_id == user_id)
        .first()
    )
    if portfolio is None:
        raise HTTPException(status_code=404, detail="Portfolio not found")
    return portfolio


def _get_current_shares(db: Session, portfolio_id: int, company_id: int) -> float:
    """Get current share count for a company in a portfolio."""
    result = db.query(
        func.coalesce(
            func.sum(
                case(
                    (PortfolioTransaction.transaction_type == "buy", PortfolioTransaction.quantity),
                    else_=-PortfolioTransaction.quantity,
                )
            ),
            0,
        )
    ).filter(
        PortfolioTransaction.portfolio_id == portfolio_id,
        PortfolioTransaction.company_id == company_id,
    ).scalar()
    return float(result)


def _calculate_holdings(
    transactions: list[PortfolioTransaction],
) -> dict[int, dict]:
    """Calculate current holdings from transaction history.

    Uses weighted average cost basis method:
    - On buy: avg_cost = (old_total_cost + new_cost) / total_shares
    - On sell: shares and total_cost decrease, avg_cost stays the same

    Returns dict: {company_id: {shares, avg_cost, total_cost}}
    """
    holdings: dict[int, dict] = defaultdict(lambda: {"shares": 0.0, "avg_cost": 0.0, "total_cost": 0.0})

    for txn in sorted(transactions, key=lambda t: t.transaction_date):
        cid = txn.company_id
        qty = float(txn.quantity)
        price = float(txn.price_per_share)
        h = holdings[cid]

        if txn.transaction_type == "buy":
            new_cost = qty * price
            total_shares = h["shares"] + qty
            if total_shares > 0:
                h["total_cost"] = h["total_cost"] + new_cost
                h["avg_cost"] = h["total_cost"] / total_shares
            h["shares"] = total_shares

        elif txn.transaction_type == "sell":
            if h["shares"] > 0:
                # Reduce shares and cost proportionally at average cost
                cost_reduction = qty * h["avg_cost"]
                h["shares"] = h["shares"] - qty
                h["total_cost"] = h["total_cost"] - cost_reduction
                # avg_cost stays the same
                if h["shares"] <= 0:
                    h["shares"] = 0.0
                    h["total_cost"] = 0.0
                    h["avg_cost"] = 0.0

    return dict(holdings)


def _calculate_realized_pnl(transactions: list[PortfolioTransaction]) -> float:
    """Calculate realized P&L from sell transactions.

    For each sell, realized P&L = (sell_price - avg_cost_at_time) × quantity
    """
    # Track cost basis per company as we process transactions chronologically
    holdings: dict[int, dict] = defaultdict(lambda: {"shares": 0.0, "avg_cost": 0.0, "total_cost": 0.0})
    realized = 0.0

    for txn in sorted(transactions, key=lambda t: t.transaction_date):
        cid = txn.company_id
        qty = float(txn.quantity)
        price = float(txn.price_per_share)
        h = holdings[cid]

        if txn.transaction_type == "buy":
            new_cost = qty * price
            total_shares = h["shares"] + qty
            if total_shares > 0:
                h["total_cost"] = h["total_cost"] + new_cost
                h["avg_cost"] = h["total_cost"] / total_shares
            h["shares"] = total_shares

        elif txn.transaction_type == "sell":
            if h["shares"] > 0:
                # Realized P&L for this sell
                realized += (price - h["avg_cost"]) * qty
                # Reduce position
                cost_reduction = qty * h["avg_cost"]
                h["shares"] = h["shares"] - qty
                h["total_cost"] = h["total_cost"] - cost_reduction
                if h["shares"] <= 0:
                    h["shares"] = 0.0
                    h["total_cost"] = 0.0
                    h["avg_cost"] = 0.0

    return realized


def _calculate_realized_by_company(
    transactions: list[PortfolioTransaction],
) -> dict[int, dict]:
    """Per-company realized aggregates using weighted-average cost basis.

    For each company:
      - quantity_sold, total_buy_cost (basis of sold shares), total_sell_proceeds
      - realized_fees = all sell fees + buys' fees prorated by qty_sold/qty_bought
      - remaining_shares, first_buy_date, last_sell_date
    """
    state: dict[int, dict] = defaultdict(lambda: {
        # running position
        "shares": 0.0,
        "avg_cost": 0.0,
        "total_cost": 0.0,
        # accumulators
        "quantity_sold": 0.0,
        "total_buy_cost": 0.0,
        "total_sell_proceeds": 0.0,
        "sell_fees": 0.0,
        "total_buy_fees": 0.0,
        "total_bought": 0.0,
        "first_buy_date": None,
        "last_sell_date": None,
    })

    for txn in sorted(transactions, key=lambda t: t.transaction_date):
        cid = txn.company_id
        qty = float(txn.quantity)
        price = float(txn.price_per_share)
        fees = float(txn.fees or 0)
        s = state[cid]

        if txn.transaction_type == "buy":
            if s["first_buy_date"] is None:
                s["first_buy_date"] = txn.transaction_date
            new_cost = qty * price
            total_shares = s["shares"] + qty
            if total_shares > 0:
                s["total_cost"] = s["total_cost"] + new_cost
                s["avg_cost"] = s["total_cost"] / total_shares
            s["shares"] = total_shares
            s["total_buy_fees"] += fees
            s["total_bought"] += qty

        elif txn.transaction_type == "sell":
            if s["shares"] <= 0:
                continue
            sell_qty = min(qty, s["shares"])
            cost_of_sold = sell_qty * s["avg_cost"]
            s["quantity_sold"] += sell_qty
            s["total_buy_cost"] += cost_of_sold
            s["total_sell_proceeds"] += sell_qty * price
            s["sell_fees"] += fees
            s["last_sell_date"] = txn.transaction_date
            # reduce position
            s["shares"] -= sell_qty
            s["total_cost"] -= cost_of_sold
            if s["shares"] <= 0:
                s["shares"] = 0.0
                s["total_cost"] = 0.0
                s["avg_cost"] = 0.0

    # Finalize: compute prorated buy fees + realized_fees and drop pure-buy positions
    result: dict[int, dict] = {}
    for cid, s in state.items():
        if s["quantity_sold"] <= 0:
            continue
        prorated_buy_fees = (
            s["total_buy_fees"] * (s["quantity_sold"] / s["total_bought"])
            if s["total_bought"] > 0 else 0.0
        )
        result[cid] = {
            "quantity_sold": s["quantity_sold"],
            "remaining_shares": s["shares"],
            "total_buy_cost": s["total_buy_cost"],
            "total_sell_proceeds": s["total_sell_proceeds"],
            "prorated_buy_fees": prorated_buy_fees,
            "realized_fees": s["sell_fees"] + prorated_buy_fees,
            "first_buy_date": s["first_buy_date"],
            "last_sell_date": s["last_sell_date"],
        }
    return result


def _get_latest_prices(db: Session, company_ids: list[int]) -> dict[int, float]:
    """Get latest closing price for each company. Returns {company_id: price}."""
    if not company_ids:
        return {}

    prices = {}
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


def _portfolio_to_response(portfolio: Portfolio) -> PortfolioResponse:
    """Convert Portfolio model to response schema."""
    return PortfolioResponse(
        id=portfolio.id,
        user_id=portfolio.user_id,
        name=portfolio.name,
        description=portfolio.description,
        initial_capital=float(portfolio.initial_capital) if portfolio.initial_capital else None,
        currency=portfolio.currency,
        created_at=portfolio.created_at,
        updated_at=portfolio.updated_at,
    )


def _transaction_to_response(
    txn: PortfolioTransaction, company: Company | None = None
) -> TransactionResponse:
    """Convert PortfolioTransaction model to response schema."""
    return TransactionResponse(
        id=txn.id,
        portfolio_id=txn.portfolio_id,
        company_id=txn.company_id,
        company_name=company.name if company else None,
        company_ticker=company.ticker_symbol if company else None,
        transaction_type=txn.transaction_type,
        quantity=float(txn.quantity),
        price_per_share=float(txn.price_per_share),
        total_amount=float(txn.total_amount),
        fees=float(txn.fees) if txn.fees else 0,
        transaction_date=txn.transaction_date,
        notes=txn.notes,
        created_at=txn.created_at,
    )
