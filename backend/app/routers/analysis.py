"""Analysis router — saved analysis snapshots + valuation computation trigger.

Provides:
- CRUD for user analysis snapshots (saved reports per company)
- Trigger endpoint for computing valuations on-demand
- Recommendation endpoint
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.analysis_snapshot import AnalysisSnapshot
from app.models.company import Company
from app.models.financial_statement import FinancialStatement
from app.models.intrinsic_value import IntrinsicValue
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
    rec = recommendation_engine.generate_recommendation(
        result.margin_of_safety_pct,
        financials,
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
):
    """Get the current recommendation for a company based on latest valuation."""
    company = db.query(Company).filter(Company.id == company_id).first()
    if company is None:
        raise HTTPException(status_code=404, detail="Company not found")

    latest_iv = (
        db.query(IntrinsicValue)
        .filter(IntrinsicValue.company_id == company_id)
        .order_by(desc(IntrinsicValue.valuation_date))
        .first()
    )

    mos = float(latest_iv.margin_of_safety_pct) if latest_iv and latest_iv.margin_of_safety_pct else None

    financials = (
        db.query(FinancialStatement)
        .filter(FinancialStatement.company_id == company_id)
        .order_by(FinancialStatement.fiscal_year)
        .all()
    )

    rec = recommendation_engine.generate_recommendation(mos, financials)

    return RecommendationResponse(
        action=rec.action,
        reason=rec.reason,
        margin_of_safety_pct=rec.margin_of_safety_pct,
        quality_score=rec.quality.score,
        quality_max_score=rec.quality.max_score,
        quality_factors=[f.to_dict() for f in rec.quality.factors],
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
        assumptions=iv.assumptions,
        calculation_details=iv.calculation_details,
        calculated_at=iv.calculated_at,
    )
