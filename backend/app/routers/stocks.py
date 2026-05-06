"""Stocks router — markets, companies, prices, financials, and valuations.

Covers all endpoints defined in the architecture under ``/api/stocks``.
"""

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.schemas.stocks import (
    CompanyDetail,
    CompanyListItem,
    FinancialStatementCreate,
    FinancialStatementResponse,
    FinancialStatementUpdate,
    MarketResponse,
    PriceRecord,
    ValuationHistoryPoint,
    ValuationResponse,
)
from app.services import stock_service

router = APIRouter(prefix="/api/stocks", tags=["stocks"])


# ---------------------------------------------------------------------------
# Markets
# ---------------------------------------------------------------------------

@router.get("/markets", response_model=list[MarketResponse])
def list_markets(db: Session = Depends(get_db)):
    """List all markets with company counts."""
    return stock_service.list_markets(db)


@router.get("/markets/{market_id}/companies", response_model=list[CompanyListItem])
def list_market_companies(market_id: int, db: Session = Depends(get_db)):
    """List all active companies in a specific market."""
    result = stock_service.list_market_companies(db, market_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Market not found")
    return result


# ---------------------------------------------------------------------------
# Companies
# ---------------------------------------------------------------------------

@router.get("/companies", response_model=list[CompanyListItem])
def list_companies(
    sector: Optional[str] = Query(None, description="Filter by sector"),
    search: Optional[str] = Query(None, description="Search by name or ticker"),
    db: Session = Depends(get_db),
):
    """List all active companies with optional sector / search filters."""
    return stock_service.list_companies(db, sector=sector, search=search)


@router.get("/companies/sectors", response_model=list[str])
def list_sectors(db: Session = Depends(get_db)):
    """List all unique sector names."""
    return stock_service.list_sectors(db)


@router.get("/companies/{company_id}", response_model=CompanyDetail)
def get_company(company_id: int, db: Session = Depends(get_db)):
    """Get a single company with latest price and latest valuation."""
    result = stock_service.get_company_detail(db, company_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Company not found")
    return result


# ---------------------------------------------------------------------------
# Prices
# ---------------------------------------------------------------------------

@router.get("/companies/{company_id}/prices", response_model=list[PriceRecord])
def get_company_prices(
    company_id: int,
    start_date: Optional[date] = Query(None, alias="start", description="Start date (YYYY-MM-DD)"),
    end_date: Optional[date] = Query(None, alias="end", description="End date (YYYY-MM-DD)"),
    limit: int = Query(365, ge=1, le=5000, description="Max records to return"),
    db: Session = Depends(get_db),
):
    """Get historical prices for a company."""
    result = stock_service.get_company_prices(
        db, company_id, start_date=start_date, end_date=end_date, limit=limit
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Company not found")
    return result


# ---------------------------------------------------------------------------
# Financial Statements
# ---------------------------------------------------------------------------

@router.get(
    "/companies/{company_id}/financials",
    response_model=list[FinancialStatementResponse],
)
def list_financials(company_id: int, db: Session = Depends(get_db)):
    """List all financial statements for a company (newest fiscal year first)."""
    result = stock_service.list_financials(db, company_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Company not found")
    return result


@router.post(
    "/companies/{company_id}/financials",
    response_model=FinancialStatementResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_financial(
    company_id: int,
    data: FinancialStatementCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Add a new financial statement for a company (manual entry)."""
    result = stock_service.create_financial(db, company_id, data, current_user.id)
    if result is None:
        raise HTTPException(status_code=404, detail="Company not found")
    return result


@router.put(
    "/companies/{company_id}/financials/{financial_id}",
    response_model=FinancialStatementResponse,
)
def update_financial(
    company_id: int,
    financial_id: int,
    data: FinancialStatementUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update an existing financial statement."""
    result = stock_service.update_financial(db, company_id, financial_id, data)
    if result == "company_not_found":
        raise HTTPException(status_code=404, detail="Company not found")
    if result == "financial_not_found":
        raise HTTPException(status_code=404, detail="Financial statement not found")
    return result


@router.delete(
    "/companies/{company_id}/financials/{financial_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_financial(
    company_id: int,
    financial_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a financial statement."""
    result = stock_service.delete_financial(db, company_id, financial_id)
    if result == "company_not_found":
        raise HTTPException(status_code=404, detail="Company not found")
    if result == "financial_not_found":
        raise HTTPException(status_code=404, detail="Financial statement not found")
    return None


# ---------------------------------------------------------------------------
# Valuations
# ---------------------------------------------------------------------------

@router.get(
    "/companies/{company_id}/valuations",
    response_model=list[ValuationResponse],
)
def list_valuations(company_id: int, db: Session = Depends(get_db)):
    """Get intrinsic value history for a company (newest first)."""
    result = stock_service.list_valuations(db, company_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Company not found")
    return result


@router.get(
    "/companies/{company_id}/valuation-trend",
    response_model=list[ValuationHistoryPoint],
)
def get_valuation_trend(
    company_id: int,
    days: int = 365,
    db: Session = Depends(get_db),
):
    """Get merged price + intrinsic value history for trend chart.

    Returns daily data points with market_price and forward-filled intrinsic_value.
    Use days parameter to control lookback period (default: 365 days).
    """
    return stock_service.get_valuation_trend(db, company_id, days=days)


@router.get(
    "/companies/{company_id}/valuations/latest",
    response_model=ValuationResponse,
)
def get_latest_valuation(company_id: int, db: Session = Depends(get_db)):
    """Get the latest valuation with explanation for a company."""
    result = stock_service.get_latest_valuation(db, company_id)
    if result == "company_not_found":
        raise HTTPException(status_code=404, detail="Company not found")
    if result == "no_valuation":
        raise HTTPException(
            status_code=404,
            detail="No valuation found for this company",
        )
    return result
