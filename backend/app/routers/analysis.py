"""Analysis router — saved analysis snapshots + valuation computation trigger.

Provides:
- CRUD for user analysis snapshots (saved reports per company)
- Trigger endpoint for computing valuations on-demand
- Recommendation endpoint
"""

from __future__ import annotations

from datetime import date
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user, get_optional_user
from app.models.analysis_snapshot import AnalysisSnapshot
from app.models.company import Company
from app.models.financial_statement import FinancialStatement
from app.models.intrinsic_value import IntrinsicValue
from app.models.portfolio import Portfolio, PortfolioTransaction
from app.models.price_history import PriceHistory
from app.models.user import User
from app.routers.alerts import check_and_trigger_alerts
from app.schemas.analysis import (
    AnalysisSnapshotCreate,
    AnalysisSnapshotResponse,
    RecommendationResponse,
    ValuationComputeRequest,
)
from app.schemas.stocks import ValuationResponse
from app.services import valuation_engine, recommendation_engine
from app.services.recommendation_dimensions import (
    PortfolioContext,
    compute_dimensions,
)

router = APIRouter(prefix="/api/analysis", tags=["analysis"])


# ---------------------------------------------------------------------------
# Valuation Computation
# ---------------------------------------------------------------------------

@router.post(
    "/companies/{company_id}/compute",
    response_model=ValuationResponse,
    status_code=status.HTTP_201_CREATED,
)
def compute_valuation(
    company_id: int,
    body: ValuationComputeRequest | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Trigger a valuation computation for a company.

    Uses default Kenyan market assumptions unless overridden in the request body.
    Stores the result as a valuation snapshot and triggers any matching alerts.
    """
    # Build custom assumptions from request body if provided
    assumptions = None
    if body:
        assumptions = {}
        if body.discount_rate is not None:
            assumptions["discount_rate"] = body.discount_rate
        if body.terminal_growth_rate is not None:
            assumptions["terminal_growth_rate"] = body.terminal_growth_rate
        if body.projection_years is not None:
            assumptions["projection_years"] = body.projection_years
        if body.dcf_weight is not None:
            assumptions["dcf_weight"] = body.dcf_weight
        if body.epv_weight is not None:
            assumptions["epv_weight"] = body.epv_weight
        if body.bv_weight is not None:
            assumptions["bv_weight"] = body.bv_weight
        if not assumptions:
            assumptions = None

    result = valuation_engine.compute_valuation(
        db, company_id, assumptions=assumptions
    )

    if result == "company_not_found":
        raise HTTPException(status_code=404, detail="Company not found")
    if result == "no_shares_outstanding":
        raise HTTPException(
            status_code=422,
            detail="Company has no shares outstanding data — cannot compute per-share values",
        )
    if result == "no_financial_data":
        raise HTTPException(
            status_code=422,
            detail="No financial statements available for this company",
        )
    if isinstance(result, str):
        raise HTTPException(status_code=422, detail=result)

    # Generate recommendation and update the record
    financials = (
        db.query(FinancialStatement)
        .filter(FinancialStatement.company_id == company_id)
        .order_by(FinancialStatement.fiscal_year)
        .all()
    )
    company = db.query(Company).filter(Company.id == company_id).first()
    rec = recommendation_engine.generate_recommendation(
        result.margin_of_safety_pct,
        financials,
        sector=company.sector if company else None,
    )

    # Update the latest IntrinsicValue record with recommendation
    latest_iv = (
        db.query(IntrinsicValue)
        .filter(IntrinsicValue.company_id == company_id)
        .order_by(desc(IntrinsicValue.valuation_date), desc(IntrinsicValue.id))
        .first()
    )
    if latest_iv:
        latest_iv.recommendation = rec.action
        latest_iv.recommendation_reason = rec.reason

    db.commit()

    # Check and trigger alerts
    check_and_trigger_alerts(db, company_id)
    db.commit()

    # Return the valuation response
    if latest_iv:
        return _iv_to_response(latest_iv)

    raise HTTPException(status_code=500, detail="Valuation computed but record not found")


@router.get(
    "/companies/{company_id}/recommendation",
    response_model=RecommendationResponse,
)
def get_recommendation(
    company_id: int,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_optional_user),
):
    """Get the current recommendation for a company based on latest valuation.

    Anonymous callers get the classical MOS+quality verdict plus the
    Valuation / Quality / Trend dimensions. Authenticated callers also get
    the Position dimension scored against their portfolio.
    """
    company = db.query(Company).filter(Company.id == company_id).first()
    if company is None:
        raise HTTPException(status_code=404, detail="Company not found")

    latest_iv = (
        db.query(IntrinsicValue)
        .filter(IntrinsicValue.company_id == company_id)
        .order_by(desc(IntrinsicValue.valuation_date), desc(IntrinsicValue.id))
        .first()
    )

    mos = float(latest_iv.margin_of_safety_pct) if latest_iv and latest_iv.margin_of_safety_pct else None

    financials = (
        db.query(FinancialStatement)
        .filter(FinancialStatement.company_id == company_id)
        .order_by(FinancialStatement.fiscal_year)
        .all()
    )

    rec = recommendation_engine.generate_recommendation(mos, financials, sector=company.sector)

    # ---- 4-dimensional scorecard ----
    prices = (
        db.query(PriceHistory)
        .filter(PriceHistory.company_id == company_id)
        .order_by(PriceHistory.price_date)
        .all()
    )
    valuation_extras: dict[str, Any] = {}
    if latest_iv is not None:
        if latest_iv.weighted_intrinsic_value is not None:
            valuation_extras["weighted_intrinsic_value"] = float(latest_iv.weighted_intrinsic_value)
        if latest_iv.current_market_price is not None:
            valuation_extras["current_market_price"] = float(latest_iv.current_market_price)

    portfolio_ctx = _build_portfolio_context(
        db, current_user, company_id, company.sector,
    )

    dims = compute_dimensions(
        mos=mos,
        quality_score=rec.quality.score,
        quality_max_score=rec.quality.max_score,
        quality_subscores=rec.quality.subscores(),
        prices=prices,
        financials=financials,
        position=portfolio_ctx,
        sector=company.sector,
        valuation_extras=valuation_extras or None,
    )

    return RecommendationResponse(
        action=rec.action,
        reason=rec.reason,
        margin_of_safety_pct=rec.margin_of_safety_pct,
        quality_score=rec.quality.score,
        quality_max_score=rec.quality.max_score,
        quality_factors=[f.to_dict() for f in rec.quality.factors],
        quality_subscores=rec.quality.subscores(),
        sector_kind=rec.quality.sector_kind,
        dimensions=dims.to_dict(),
    )


def _build_portfolio_context(
    db: Session,
    user: User | None,
    company_id: int,
    sector: str | None,
) -> PortfolioContext | None:
    """Aggregate the user's live position + portfolio context for one company.

    Returns None if there's no authenticated user. If the user is authenticated
    but doesn't hold the security, returns a context with ``net_qty = 0`` so
    the Position scorer can render the "no position" tile.
    """
    if user is None:
        return None

    # All user portfolios (usually one, but portfolios are a first-class table).
    portfolio_ids = [
        p.id for p in db.query(Portfolio).filter(Portfolio.user_id == user.id).all()
    ]
    if not portfolio_ids:
        return PortfolioContext(net_qty=0.0)

    # Aggregate net qty and cost basis for THIS company.
    txns = (
        db.query(PortfolioTransaction)
        .filter(
            PortfolioTransaction.portfolio_id.in_(portfolio_ids),
            PortfolioTransaction.company_id == company_id,
        )
        .order_by(PortfolioTransaction.transaction_date)
        .all()
    )
    net_qty = 0.0
    total_cost = 0.0
    for t in txns:
        qty = float(t.quantity)
        price = float(t.price_per_share)
        if t.transaction_type == "buy":
            net_qty += qty
            total_cost += qty * price
        elif t.transaction_type == "sell":
            # Reduce cost basis proportionally.
            if net_qty > 0:
                avg = total_cost / net_qty
                total_cost -= min(qty, net_qty) * avg
            net_qty -= qty
    avg_cost = (total_cost / net_qty) if net_qty > 0 else None

    # Current price for this company.
    latest_price_row = (
        db.query(PriceHistory)
        .filter(PriceHistory.company_id == company_id)
        .order_by(desc(PriceHistory.price_date))
        .first()
    )
    current_price = (
        float(latest_price_row.close_price) if latest_price_row is not None else None
    )

    # Portfolio + sector totals mark-to-market.
    all_txns = (
        db.query(PortfolioTransaction)
        .filter(PortfolioTransaction.portfolio_id.in_(portfolio_ids))
        .all()
    )
    # net qty per company
    per_company: dict[int, float] = {}
    for t in all_txns:
        delta = float(t.quantity) if t.transaction_type == "buy" else -float(t.quantity)
        per_company[t.company_id] = per_company.get(t.company_id, 0.0) + delta

    portfolio_value = 0.0
    sector_value = 0.0
    if per_company:
        held_ids = [cid for cid, q in per_company.items() if q > 0]
        if held_ids:
            # Latest prices for held companies.
            latest_prices: dict[int, float] = {}
            for cid in held_ids:
                p = (
                    db.query(PriceHistory)
                    .filter(PriceHistory.company_id == cid)
                    .order_by(desc(PriceHistory.price_date))
                    .first()
                )
                if p is not None:
                    latest_prices[cid] = float(p.close_price)
            # Companies for sector lookup.
            sector_by_id: dict[int, str | None] = {}
            if sector is not None:
                held_companies = (
                    db.query(Company).filter(Company.id.in_(held_ids)).all()
                )
                sector_by_id = {c.id: c.sector for c in held_companies}
            for cid in held_ids:
                price = latest_prices.get(cid)
                if price is None:
                    continue
                mv = per_company[cid] * price
                portfolio_value += mv
                if sector is not None and sector_by_id.get(cid) == sector:
                    sector_value += mv

    return PortfolioContext(
        net_qty=net_qty,
        avg_cost=avg_cost,
        current_price=current_price,
        portfolio_value=portfolio_value or None,
        sector_value=sector_value if sector is not None else None,
    )


# ---------------------------------------------------------------------------
# Analysis Snapshots CRUD
# ---------------------------------------------------------------------------

@router.get("/snapshots", response_model=list[AnalysisSnapshotResponse])
def list_snapshots(
    company_id: Optional[int] = Query(None, description="Filter by company"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all analysis snapshots for the current user."""
    query = db.query(AnalysisSnapshot).filter(
        AnalysisSnapshot.user_id == current_user.id
    )
    if company_id is not None:
        query = query.filter(AnalysisSnapshot.company_id == company_id)

    snapshots = query.order_by(desc(AnalysisSnapshot.created_at)).all()
    return [_snapshot_to_response(s) for s in snapshots]


@router.post(
    "/snapshots",
    response_model=AnalysisSnapshotResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_snapshot(
    data: AnalysisSnapshotCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Save a new analysis snapshot."""
    # Validate company exists
    company = db.query(Company).filter(Company.id == data.company_id).first()
    if company is None:
        raise HTTPException(status_code=404, detail="Company not found")

    snapshot = AnalysisSnapshot(
        company_id=data.company_id,
        user_id=current_user.id,
        title=data.title,
        analysis_type=data.analysis_type,
        analysis_text=data.analysis_text,
        data_snapshot=data.data_snapshot,
        valuation_at_time=data.valuation_at_time,
    )
    db.add(snapshot)
    db.commit()
    db.refresh(snapshot)
    return _snapshot_to_response(snapshot)


@router.get("/snapshots/{snapshot_id}", response_model=AnalysisSnapshotResponse)
def get_snapshot(
    snapshot_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get a single analysis snapshot."""
    snapshot = _get_user_snapshot(db, snapshot_id, current_user.id)
    return _snapshot_to_response(snapshot)


@router.delete("/snapshots/{snapshot_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_snapshot(
    snapshot_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete an analysis snapshot."""
    snapshot = _get_user_snapshot(db, snapshot_id, current_user.id)
    db.delete(snapshot)
    db.commit()
    return None


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _get_user_snapshot(db: Session, snapshot_id: int, user_id: int) -> AnalysisSnapshot:
    """Get snapshot ensuring it belongs to the user."""
    snapshot = (
        db.query(AnalysisSnapshot)
        .filter(AnalysisSnapshot.id == snapshot_id, AnalysisSnapshot.user_id == user_id)
        .first()
    )
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Snapshot not found")
    return snapshot


def _snapshot_to_response(snapshot: AnalysisSnapshot) -> AnalysisSnapshotResponse:
    """Convert AnalysisSnapshot model to response schema."""
    return AnalysisSnapshotResponse(
        id=snapshot.id,
        company_id=snapshot.company_id,
        user_id=snapshot.user_id,
        title=snapshot.title,
        analysis_type=snapshot.analysis_type,
        analysis_text=snapshot.analysis_text,
        data_snapshot=snapshot.data_snapshot,
        valuation_at_time=snapshot.valuation_at_time,
        created_at=snapshot.created_at,
    )


def _iv_to_response(iv) -> ValuationResponse:
    """Convert IntrinsicValue model to ValuationResponse schema."""
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
        model_used=getattr(iv, "model_used", None),
        scenario_values=getattr(iv, "scenario_values", None),
        assumptions=iv.assumptions,
        calculation_details=iv.calculation_details,
        calculated_at=iv.calculated_at,
    )
